#!/usr/bin/env python3
from __future__ import annotations
import argparse, ast, hashlib, importlib.util, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REGISTRY = HERE / "scope_registry.json"
BASE = HERE / "fixture_base.py"
GOOD = HERE / "fixture_local_good.py"
REGRESSIVE = HERE / "fixture_local_regressive.py"

def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def fn_map(path):
    tree = ast.parse(path.read_text())
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = ast.dump(node, include_attributes=False)
    return out

def touched_symbols(base, candidate):
    a, b = fn_map(base), fn_map(candidate)
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))

def scope_for(symbols, registry):
    if not symbols:
        return []
    scopes = []
    for symbol in symbols:
        entry = registry["symbols"].get(symbol)
        if entry is None:
            return list(registry["metrics"])
        scopes.extend(entry["metrics"])
    return sorted(set(scopes))

def metrics(mod):
    # Prospectively frozen synthetic metrics. Higher is better.
    slug_cases = [
        ("  Hello   World  ", "hello-world"),
        ("A B C", "a-b-c"),
        ("single", "single"),
        ("Hello_world", "hello-world"),
    ]
    slug_score = sum(mod.slugify(x) == y for x, y in slug_cases)

    sum_cases = [
        (([1,2,3], 10), 6),
        (([5,7], 8), 8),
        (([], 2), 0),
    ]
    sum_score = sum(mod.bounded_sum(*args) == expected for args, expected in sum_cases)

    median_cases = [
        (([3,1,2],), 2),
        (([1,2,3,4],), 2.5),
        (([9],), 9),
    ]
    median_score = sum(mod.median(*args) == expected for args, expected in median_cases)

    return {"slugify": slug_score, "bounded_sum": sum_score, "median": median_score}

def protected(mod):
    checks = {
        "slugify_contract": mod.slugify("  Hello   World  ") == "hello-world",
        "bounded_sum_contract": mod.bounded_sum([5, 7], 8) == 8,
        "median_contract": mod.median([1,2,3,4]) == 2.5,
    }
    return checks

def far002(base_m, cand_m):
    # Frozen global rule from FAR-002: every metric must strictly improve.
    return all(cand_m[k] > base_m[k] for k in base_m)

def far003(base_path, cand_path, registry):
    touched = touched_symbols(base_path, cand_path)
    scope = scope_for(touched, registry)
    base_mod = load_module(base_path, "far003_base")
    cand_mod = load_module(cand_path, "far003_candidate")
    bmet, cmet = metrics(base_mod), metrics(cand_mod)
    bprot, cprot = protected(base_mod), protected(cand_mod)

    protected_ok = all((not bprot[k]) or cprot[k] for k in bprot)
    improved = bool(scope) and all(cmet[k] >= bmet[k] for k in scope) and any(cmet[k] > bmet[k] for k in scope)
    return {
        "touched_symbols": touched,
        "scope": scope,
        "baseline_metrics": bmet,
        "candidate_metrics": cmet,
        "baseline_protected": bprot,
        "candidate_protected": cprot,
        "protected_ok": protected_ok,
        "scope_improved": improved,
        "decision": "ACCEPT" if protected_ok and improved else "REJECT",
    }

def main():
    registry = json.loads(REGISTRY.read_text())
    base = load_module(BASE, "far003_base_global")
    base_m = metrics(base)

    good = load_module(GOOD, "far003_good_global")
    regressive = load_module(REGRESSIVE, "far003_bad_global")

    good_far002 = "ACCEPT" if far002(base_m, metrics(good)) else "REJECT"
    good_far003 = far003(BASE, GOOD, registry)
    bad_far003 = far003(BASE, REGRESSIVE, registry)

    fallback_checks = {
        "unknown_symbol_defaults_global": sorted(scope_for(["new_unregistered_helper"], registry)) == sorted(registry["metrics"]),
        "shared_helper_uses_registered_union": scope_for(["_normalize"], registry) == sorted(registry["metrics"]),
        "multi_symbol_uses_union": scope_for(["slugify", "median"], registry) == ["median", "slugify"],
    }

    outcome = {
        "schema": "airlock.far003.result.v1",
        "frozen_inputs": {
            "scope_registry_sha256": sha256(REGISTRY),
            "evaluator_sha256": sha256(Path(__file__)),
        },
        "results": {
            "same_candidate_far002": good_far002,
            "same_candidate_far003": good_far003["decision"],
            "regressive_candidate_far003": bad_far003["decision"],
        },
        "details": {
            "good": good_far003,
            "regressive": bad_far003,
        },
        "fallback_checks": fallback_checks,
    }
    outcome["earned"] = all(fallback_checks.values()) and outcome["results"] == {
        "same_candidate_far002": "REJECT",
        "same_candidate_far003": "ACCEPT",
        "regressive_candidate_far003": "REJECT",
    }
    print(json.dumps(outcome, indent=2, sort_keys=True))
    return 0 if outcome["earned"] else 3

if __name__ == "__main__":
    raise SystemExit(main())
