#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / ".airlock" / "self-001" / "scope_registry.json"
TARGET_REL = "experiments/airlock-self-001/office_ops.py"


def run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CountingIterable:
    def __init__(self, length: int, value: int = 1):
        self.length = length
        self.value = value
        self.consumed = 0

    def __iter__(self):
        for _ in range(self.length):
            self.consumed += 1
            yield self.value


def protected(module) -> dict[str, bool]:
    return {
        "first_over_budget_none": module.first_over_budget([1, 2, 3], 10) is None,
        "first_over_budget_exact_not_over": module.first_over_budget([5, 5], 10) is None,
        "first_over_budget_first_cross": module.first_over_budget([4, 4, 4], 10) == 2,
        "first_over_budget_negative_then_cross": module.first_over_budget([-5, 20], 10) == 1,
        "first_over_budget_generator": module.first_over_budget((x for x in [3, 3, 5]), 10) == 2,
        "invoice_total_empty": module.invoice_total([]) == 0,
        "invoice_total_values": module.invoice_total([105, 200, -5]) == 300,
        "discount_zero": module.discount_amount(1000, 0) == 0,
        "discount_floor": module.discount_amount(999, 333) == 33,
        "discount_full": module.discount_amount(12345, 10_000) == 12345,
    }


def metrics(module) -> dict[str, float]:
    counter = CountingIterable(5000, 1)
    result = module.first_over_budget(counter, 10)
    if result != 10:
        consumed = 1_000_000.0
    else:
        consumed = float(counter.consumed)

    invoice_cases = [
        ([], 0),
        ([1, 2, 3], 6),
        ([105, 200, -5], 300),
        ([999_999, 1], 1_000_000),
    ]
    invoice_score = sum(module.invoice_total(values) == expected for values, expected in invoice_cases)

    discount_cases = [
        ((1000, 0), 0),
        ((999, 333), 33),
        ((12345, 10_000), 12345),
        ((10_001, 2500), 2500),
    ]
    discount_score = sum(module.discount_amount(*args) == expected for args, expected in discount_cases)

    return {
        "first_over_budget_consumed": consumed,
        "invoice_total_cases": float(invoice_score),
        "discount_cases": float(discount_score),
    }


def function_map(text: str) -> dict[str, str]:
    tree = ast.parse(text)
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = ast.dump(node, include_attributes=False)
    return out


def git_text(repo: Path, commit: str, path: str) -> str | None:
    cp = run(["git", "show", f"{commit}:{path}"], repo)
    if cp.returncode != 0:
        return None
    return cp.stdout


def changed_paths(repo: Path, base: str, candidate: str) -> list[str]:
    cp = run(["git", "diff", "--name-only", f"{base}..{candidate}"], repo)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or "git diff failed")
    return sorted(x.strip() for x in cp.stdout.splitlines() if x.strip())


def diff_stats(repo: Path, base: str, candidate: str) -> dict[str, int]:
    cp = run(["git", "diff", "--numstat", f"{base}..{candidate}"], repo)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or "git numstat failed")
    changed_files = added = deleted = binary = 0
    for line in cp.stdout.splitlines():
        if not line.strip():
            continue
        changed_files += 1
        left, right, *_ = line.split("\t")
        if left == "-" or right == "-":
            binary += 1
        else:
            added += int(left)
            deleted += int(right)
    return {
        "changed_files": changed_files,
        "lines_added": added,
        "lines_deleted": deleted,
        "changed_lines": added + deleted,
        "binary_files": binary,
    }


def touched_symbols(repo: Path, base: str, candidate: str, paths: Iterable[str]) -> list[str]:
    touched: list[str] = []
    for path in paths:
        if path != TARGET_REL:
            touched.append(f"{path}:*")
            continue
        before = git_text(repo, base, path)
        after = git_text(repo, candidate, path)
        if before is None or after is None:
            touched.append(f"{path}:*")
            continue
        a = function_map(before)
        b = function_map(after)
        for name in sorted(set(a) | set(b)):
            if a.get(name) != b.get(name):
                touched.append(f"{path}:{name}")
    return sorted(set(touched))


def scope_for(touched: list[str], registry: dict) -> list[str]:
    all_metrics = sorted(registry["metrics"])
    scope: set[str] = set()
    for symbol in touched:
        entry = registry["symbols"].get(symbol)
        if entry is None:
            return all_metrics
        scope.update(entry["metrics"])
    return sorted(scope)


def materialize(repo: Path, commit: str, path: str, destination: Path) -> None:
    text = git_text(repo, commit, path)
    if text is None:
        raise RuntimeError(f"{path} missing at {commit}")
    destination.write_text(text)


def metric_gain(base: float, candidate: float, direction: str) -> float:
    denom = max(abs(base), 1.0)
    if direction == "minimize":
        return (base - candidate) / denom
    return (candidate - base) / denom


def evaluate(repo: Path, base: str, candidate: str, registry: dict) -> dict:
    paths = changed_paths(repo, base, candidate)
    touched = touched_symbols(repo, base, candidate, paths)
    scope = scope_for(touched, registry)
    stats = diff_stats(repo, base, candidate)

    result = {
        "candidate_commit": candidate,
        "changed_paths": paths,
        "touched_symbols": touched,
        "scope": scope,
        "diff": stats,
        "disposition": "REJECT",
        "reason": None,
    }

    bounds = registry["bounds"]
    if stats["binary_files"]:
        result["reason"] = "BINARY_CHANGE"
        return result
    if stats["changed_files"] > int(bounds["max_changed_files"]):
        result["reason"] = "CHANGED_FILE_LIMIT"
        return result
    if stats["changed_lines"] > int(bounds["max_changed_lines"]):
        result["reason"] = "CHANGED_LINE_LIMIT"
        return result
    if TARGET_REL not in paths:
        result["reason"] = "NO_REGISTERED_MEASURABLE_CHANGE"
        return result

    with tempfile.TemporaryDirectory(prefix="airlock-self-001-eval-") as td:
        td = Path(td)
        base_file = td / "base.py"
        candidate_file = td / "candidate.py"
        materialize(repo, base, TARGET_REL, base_file)
        materialize(repo, candidate, TARGET_REL, candidate_file)
        base_mod = load_module(base_file, "self001_base")
        cand_mod = load_module(candidate_file, "self001_candidate")

        base_protected = protected(base_mod)
        cand_protected = protected(cand_mod)
        protected_ok = all((not base_protected[k]) or cand_protected[k] for k in base_protected)
        result["baseline_protected"] = base_protected
        result["candidate_protected"] = cand_protected
        result["protected_ok"] = protected_ok
        if not protected_ok:
            result["reason"] = "PROTECTED_REGRESSION"
            return result

        base_metrics = metrics(base_mod)
        cand_metrics = metrics(cand_mod)
        gains = {}
        for name in scope:
            spec = registry["metrics"][name]
            gains[name] = metric_gain(base_metrics[name], cand_metrics[name], spec["direction"])
        result["baseline_metrics"] = base_metrics
        result["candidate_metrics"] = cand_metrics
        result["relative_gains"] = gains

        if not scope:
            result["reason"] = "EMPTY_SCOPE"
            return result
        if any(value < 0 for value in gains.values()):
            result["reason"] = "SCOPED_REGRESSION"
            return result

        minimum = float(registry["minimum_relative_gain"])
        if max(gains.values()) < minimum:
            result["reason"] = "MINIMUM_GAIN_NOT_CLEARED"
            return result

        raw_score = max(gains.values())
        penalty = float(registry["complexity_penalty_per_changed_line"]) * stats["changed_lines"]
        score = raw_score - penalty
        result["raw_gain_score"] = raw_score
        result["complexity_penalty"] = penalty
        result["net_gain_score"] = score
        if score <= 0:
            result["reason"] = "NONPOSITIVE_NET_GAIN"
            return result

    result["disposition"] = "ACCEPT"
    result["reason"] = "SCOPED_GAIN_WITH_PROTECTED_BASELINE"
    return result


def self_test() -> int:
    registry = json.loads(REGISTRY_PATH.read_text())
    base = ROOT / "experiments" / "airlock-self-001" / "office_ops.py"
    good = ROOT / "experiments" / "airlock-self-001" / "fixtures" / "office_ops_good.py"
    bad = ROOT / "experiments" / "airlock-self-001" / "fixtures" / "office_ops_regressive.py"

    base_mod = load_module(base, "self001_test_base")
    good_mod = load_module(good, "self001_test_good")
    bad_mod = load_module(bad, "self001_test_bad")

    b = metrics(base_mod)
    g = metrics(good_mod)
    good_gain = metric_gain(
        b["first_over_budget_consumed"],
        g["first_over_budget_consumed"],
        "minimize",
    )
    checks = {
        "baseline_protected": all(protected(base_mod).values()),
        "good_protected": all(protected(good_mod).values()),
        "regressive_rejected_by_protected": not all(protected(bad_mod).values()),
        "good_clears_minimum_gain": good_gain >= float(registry["minimum_relative_gain"]),
        "unknown_defaults_global": scope_for(["unknown.py:*"], registry) == sorted(registry["metrics"]),
        "registered_scope_is_local": scope_for(
            [f"{TARGET_REL}:first_over_budget"], registry
        ) == ["first_over_budget_consumed"],
    }
    print(json.dumps({"schema": "airlock.self001.evaluator-selftest.v1", "checks": checks, "passed": all(checks.values())}, indent=2, sort_keys=True))
    return 0 if all(checks.values()) else 3


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base")
    parser.add_argument("--candidate")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.base or not args.candidate:
        parser.error("--base and --candidate are required unless --self-test is used")
    registry = json.loads(REGISTRY_PATH.read_text())
    result = evaluate(Path(args.repo).resolve(), args.base, args.candidate, registry)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["disposition"] == "ACCEPT" else 3


if __name__ == "__main__":
    raise SystemExit(main())
