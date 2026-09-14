from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TACTICS = (
    "inspect_repo",
    "run_baseline",
    "read_tests",
    "trace_failure",
    "small_patch",
    "measure_hotspot",
    "adversarial_check",
    "preserve_invariants",
    "read_docs",
    "compare_history",
)
TACTIC_SET = frozenset(TACTICS)
MAX_TACTICS = 5
ALLOWED_IMPORT_ROOTS = {
    "__future__",
    "bisect",
    "collections",
    "functools",
    "itertools",
    "math",
    "re",
    "typing",
}
BANNED_NAMES = {"__import__", "compile", "eval", "exec", "open", "breakpoint"}
BANNED_IMPORT_ROOTS = {
    "importlib", "inspect", "os", "pathlib", "random", "requests", "socket",
    "subprocess", "sys", "urllib",
}


class PolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class Score:
    successes: int
    total: int
    by_kind: dict[str, dict[str, int]]

    @property
    def success_rate(self) -> float:
        return self.successes / self.total if self.total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "successes": self.successes,
            "total": self.total,
            "success_rate": self.success_rate,
            "by_kind": self.by_kind,
        }


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def validate_policy_source(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    source = p.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(p))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                imported.append(alias.name)
                if root in BANNED_IMPORT_ROOTS or root not in ALLOWED_IMPORT_ROOTS:
                    raise PolicyError(f"policy import is outside frozen allowlist: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".", 1)[0]
            imported.append(module)
            if not module or root in BANNED_IMPORT_ROOTS or root not in ALLOWED_IMPORT_ROOTS:
                raise PolicyError(f"policy import is outside frozen allowlist: {module!r}")
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            raise PolicyError(f"policy uses banned dynamic/file primitive: {node.id}")
    if not any(isinstance(n, ast.FunctionDef) and n.name == "choose_tactics" for n in tree.body):
        raise PolicyError("policy must define choose_tactics(context)")
    return {
        "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "imports": sorted(set(imported)),
        "bytes": len(source.encode("utf-8")),
        "lines": len(source.splitlines()),
    }


def load_policy(path: str | Path):
    validate_policy_source(path)
    p = Path(path)
    name = "ril001_policy_" + hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    spec = importlib.util.spec_from_file_location(name, p)
    if spec is None or spec.loader is None:
        raise PolicyError("could not load policy")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    choose = getattr(module, "choose_tactics", None)
    if not callable(choose):
        raise PolicyError("policy choose_tactics(context) is not callable")
    return choose


def normalize_tactics(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise PolicyError("choose_tactics must return a list")
    tactics = [str(x) for x in value]
    if len(tactics) > MAX_TACTICS:
        raise PolicyError(f"policy returned more than {MAX_TACTICS} tactics")
    if len(tactics) != len(set(tactics)):
        raise PolicyError("policy returned duplicate tactics")
    unknown = sorted(set(tactics) - TACTIC_SET)
    if unknown:
        raise PolicyError(f"unknown tactics: {unknown}")
    return tactics


_FAMILIES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "bug": (
        ("inspect_repo", "run_baseline", "read_tests", "trace_failure", "adversarial_check"),
        ("regression", "edge case", "unexpected output", "parser bug", "wrong branch"),
    ),
    "performance": (
        ("inspect_repo", "run_baseline", "measure_hotspot", "small_patch", "preserve_invariants"),
        ("hot path", "latency", "allocation spike", "slow loop", "throughput"),
    ),
    "constraint": (
        ("inspect_repo", "read_docs", "compare_history", "preserve_invariants", "small_patch"),
        ("maintainer constraint", "compatibility contract", "migration rule", "public API", "release promise"),
    ),
    "flaky": (
        ("inspect_repo", "run_baseline", "trace_failure", "adversarial_check", "preserve_invariants"),
        ("intermittent CI", "race-looking failure", "nondeterministic test", "timing-sensitive", "sporadic error"),
    ),
    "migration": (
        ("inspect_repo", "read_docs", "read_tests", "compare_history", "preserve_invariants"),
        ("upgrade dependency", "format transition", "schema migration", "deprecation", "version boundary"),
    ),
    "cleanup": (
        ("inspect_repo", "run_baseline", "read_tests", "small_patch", "preserve_invariants"),
        ("simplify code", "remove duplication", "small refactor", "cleanup", "reduce branches"),
    ),
}

_DISTRACTORS = (
    "Keep the patch bounded.",
    "The repository has unrelated files.",
    "Do not assume a deployment is authorized.",
    "The visible symptom may not be the root cause.",
    "There is a fixed evaluation budget.",
    "A reviewer will inspect the evidence later.",
)


def generate_tasks(seed_hex: str, per_kind: int) -> list[dict[str, Any]]:
    seed = int(hashlib.sha256(seed_hex.encode("utf-8")).hexdigest(), 16)
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    for family, (required, phrases) in _FAMILIES.items():
        for idx in range(per_kind):
            phrase = rng.choice(phrases)
            distractors = rng.sample(_DISTRACTORS, k=2)
            context = (
                f"Repository improvement request: {phrase}. "
                f"{distractors[0]} {distractors[1]} "
                f"Case variant {idx + 1}. Choose a search strategy before editing."
            )
            rows.append({"kind": family, "context": context, "required": list(required)})
    rng.shuffle(rows)
    return rows


def task_success(task: dict[str, Any], tactics: list[str]) -> bool:
    required = set(task["required"])
    chosen = set(tactics)
    hits = len(required & chosen)
    extras = len(chosen - required)
    # Four of five correct with at most one distractor is enough; exact matching is not required.
    return hits >= 4 and extras <= 1


def score_policy(policy_path: str | Path, tasks: list[dict[str, Any]]) -> tuple[Score, list[bool]]:
    choose = load_policy(policy_path)
    by_kind: dict[str, dict[str, int]] = {}
    outcomes: list[bool] = []
    for task in tasks:
        kind = str(task["kind"])
        bucket = by_kind.setdefault(kind, {"successes": 0, "total": 0})
        bucket["total"] += 1
        try:
            tactics = normalize_tactics(choose(str(task["context"])))
            ok = task_success(task, tactics)
        except Exception:
            ok = False
        outcomes.append(ok)
        if ok:
            bucket["successes"] += 1
    return Score(sum(outcomes), len(outcomes), by_kind), outcomes


def paired_descriptive(control: list[bool], recursive: list[bool]) -> dict[str, int]:
    """Within-run descriptive comparison only; cases from one batched call are not replications."""
    if len(control) != len(recursive):
        raise ValueError("paired outcomes must have equal length")
    recursive_only = sum((not c) and r for c, r in zip(control, recursive))
    control_only = sum(c and (not r) for c, r in zip(control, recursive))
    both_correct = sum(c and r for c, r in zip(control, recursive))
    both_wrong = sum((not c) and (not r) for c, r in zip(control, recursive))
    return {
        "recursive_only_wins": recursive_only,
        "control_only_wins": control_only,
        "both_correct": both_correct,
        "both_wrong": both_wrong,
        "cases": len(control),
    }
