"""RSI-006-Q substrate qualification orchestrator.

Usage:
  python run_rsi_006_q.py --self-check
  python run_rsi_006_q.py --qualify --work-dir /tmp/rsi-006-q [--pool-dir DIR] [--workers 2]

This stage performs NO scientific experiment. There are no researcher arms,
no hypotheses, no predictions, no model access, and no scientific verdicts.
It qualifies the external discovery substrate for RSI-006: generic,
receiver-owned perturbations of untouched real repositories must yield
stable, reproducible, signal-bearing observations.

Causal order (enforced):
  1. verify pinned repo SHAs + green deterministic baselines
  2. generate discovery mutants from FROZEN seeds, observe, SEAL the archive
  3. only then: fresh OS-entropy nonce -> confirmation mutants, observe
  4. determinism rerun subset -> byte-identity check
  5. metrics vs frozen thresholds -> verdict -> report
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import observe
import perturb

EXP_DIR = Path(__file__).resolve().parent
SPEC_PATH = EXP_DIR / "RSI_006_Q_SPEC.md"

# Frozen discovery seeds (RSI_006_Q_SPEC.md).
SEED_A = "RSI-006-Q-discovery-A"
SEED_B = "RSI-006-Q-discovery-B"

# Frozen mutant budgets per repo: (discovery_A, discovery_B, det_rerun, confirmation)
BUDGETS = {
    "more-itertools": (20, 20, 10, 20),
    "cachetools": (60, 60, 20, 60),
    "boltons": (60, 60, 20, 60),
    "pluggy": (60, 60, 20, 60),
}

POOL = [
    {
        "name": "more-itertools",
        "url": "https://github.com/more-itertools/more-itertools.git",
        "sha": "b2f3aff7633057d234ec9186c18a53f4df306d08",
        "pkg": "more_itertools",
        "src_layout": False,
        "tests": "tests",
    },
    {
        "name": "cachetools",
        "url": "https://github.com/tkem/cachetools.git",
        "sha": "4500e3d04288738d25acbb4973eb3c3e1bf41db9",
        "pkg": "cachetools",
        "src_layout": True,
        "tests": "tests",
    },
    {
        "name": "boltons",
        "url": "https://github.com/mahmoud/boltons.git",
        "sha": "961dcff3f42e73b245aef65e377fe82763b257bb",
        "pkg": "boltons",
        "src_layout": False,
        "tests": "tests",
    },
    {
        "name": "pluggy",
        "url": "https://github.com/pytest-dev/pluggy.git",
        "sha": "0a4974175aa2d873f401345b151297af2e74c851",
        "pkg": "pluggy",
        "src_layout": True,
        "tests": "testing",
    },
]

# Frozen thresholds (RSI_006_Q_SPEC.md).
THRESH = {
    "qdet_agreement": 1.0,
    "kill_rate_lo": 0.05,
    "kill_rate_hi": 0.95,
    "stab_abs_tol": 0.25,
    "stab_spearman_min": 0.7,
    "stab_min_operators": 3,
    "stab_min_per_half": 10,
    "fresh_op_tol": 0.30,
    "fresh_overall_tol": 0.15,
    "collection_error_max": 0.10,
}

FORBIDDEN_IMPORTS = ("openai", "anthropic", "google.generativeai", "boto3",
                     "langchain", "transformers", "huggingface_hub")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if ".git" in path.parts or not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        h.update(rel.encode("utf-8") + b"\x00" + path.read_bytes() + b"\x00")
    return h.hexdigest()


def canonical_bytes(obs: dict) -> bytes:
    return json.dumps(obs, sort_keys=True, separators=(",", ":")).encode("utf-8")


def spearman(xs: list[float], ys: list[float]) -> float:
    def ranks(vs: list[float]) -> list[float]:
        order = sorted(range(len(vs)), key=lambda i: vs[i])
        r = [0.0] * len(vs)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vs[order[j + 1]] == vs[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx)
    dy = sum((b - my) ** 2 for b in ry)
    if dx == 0 and dy == 0:
        return 1.0 if all(a == b for a, b in zip(xs, ys)) else 0.0
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx ** 0.5 * dy ** 0.5)


def kill_rate(observations: list[dict]) -> float:
    if not observations:
        return 0.0
    return sum(1 for o in observations if o["kill"]) / len(observations)


def op_kill_rates(observations: list[dict]) -> dict[str, float]:
    by_op: dict[str, list[dict]] = {}
    for o in observations:
        by_op.setdefault(o["operator"], []).append(o)
    return {op: kill_rate(v) for op, v in by_op.items()}


# --------------------------------------------------------------------------
# self-check (non-executing w.r.t. the substrate)
# --------------------------------------------------------------------------

def self_check() -> None:
    # 1. Spec exists and carries the frozen thresholds.
    text = SPEC_PATH.read_text()
    for needle in ("RSI-006-Q", "QUALIFIED_RSI_006_SUBSTRATE", "1.0 exact",
                   "[0.05, 0.95]", "0.25", "0.7", "0.10"):
        assert needle in text, f"spec missing frozen marker: {needle}"

    # 2. Operator set matches the spec.
    assert tuple(perturb.OPERATORS) == (
        "CMP_SWAP", "ARITH_SWAP", "BOOL_FLIP",
        "NUM_DELTA", "LOGIC_SWAP", "NOT_DROP",
    ), perturb.OPERATORS

    # 3. Generator determinism: same seed -> identical mutant descriptors.
    with tempfile.TemporaryDirectory() as td:
        pkg = Path(td) / "tinypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "mod.py").write_text(
            "def f(x):\n    return x + 1 if x > 0 else x - 1\n"
        )
        m1 = perturb.generate_mutants(pkg, "seed-1", 10, "t")
        m2 = perturb.generate_mutants(pkg, "seed-1", 10, "t")
        m3 = perturb.generate_mutants(pkg, "seed-2", 10, "t")
        assert [m["site_key"] for m in m1] == [m["site_key"] for m in m2]
        assert [m["site_key"] for m in m1] != [m["site_key"] for m in m3]
        # Mutant application changes exactly one site and stays parseable.
        ov = Path(td) / "ov" / "tinypkg"
        shutil.copytree(pkg, ov)
        perturb.apply_mutant(pkg, m1[0], ov)
        changed = (ov / "mod.py").read_text() != (pkg / "mod.py").read_text()
        assert changed, "mutant application changed nothing"
        ast.parse((ov / "mod.py").read_text())

    # 4. No researcher/model-access imports anywhere in this stage.
    for path in EXP_DIR.glob("*.py"):
        tree = ast.parse(path.read_bytes())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""]
            else:
                continue
            for mod in mods:
                assert not any(
                    mod == f or mod.startswith(f + ".") or f in mod
                    for f in FORBIDDEN_IMPORTS
                ), f"forbidden import {mod} in {path.name}"

    # 5. No scientific-primary-style flags exist in this orchestrator.
    # (AST-based so the check itself cannot trip on a string literal.)
    src = Path(__file__).read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and \
                getattr(node.func, "attr", "") == "add_argument":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    assert "primary" not in arg.value, arg.value
    # ("night"+"shift" split so this very check cannot trip on its literal.)
    assert ("night" + "shift") not in src.lower()

    print("RSI-006-Q self-check clean: spec frozen, generator deterministic, "
          "operator set bound, no researcher code path. "
          "Substrate NOT qualified (pass --qualify only when authorized).")


# --------------------------------------------------------------------------
# qualification run
# --------------------------------------------------------------------------

def setup_repo(entry: dict, pool_dir: Path) -> Path:
    dest = pool_dir / entry["name"]
    if dest.exists():
        head = subprocess.run(
            ["git", "-C", str(dest), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if head != entry["sha"]:
            raise RuntimeError(
                f"{entry['name']}: existing checkout at {head}, want {entry['sha']}"
            )
    else:
        subprocess.run(
            ["git", "clone", "-q", entry["url"], str(dest)], check=True
        )
        subprocess.run(
            ["git", "-C", str(dest), "checkout", "-q", entry["sha"]], check=True
        )
        head = subprocess.run(
            ["git", "-C", str(dest), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert head == entry["sha"], f"{entry['name']}: SHA mismatch {head}"
    return dest


def repo_cfg(entry: dict, repo_root: Path) -> dict:
    if entry["src_layout"]:
        package_dir = repo_root / "src" / entry["pkg"]
        import_root = repo_root / "src"
    else:
        package_dir = repo_root / entry["pkg"]
        import_root = repo_root
    return {
        "name": entry["name"],
        "repo_root": str(repo_root),
        "package_dir": str(package_dir),
        "import_root": str(import_root),
        "tests_dir": str(repo_root / entry["tests"]),
    }


def qualify(work_dir: Path, pool_dir: Path, workers: int, python: str) -> dict:
    t0 = time.time()
    pool_dir.mkdir(parents=True, exist_ok=True)
    obs_dir = work_dir / "observations"
    obs_dir.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "schema": "airlock.rsi-006-q.report.v1",
        "experiment": "RSI-006 substrate qualification",
        "spec_sha256": sha256_file(SPEC_PATH),
        "perturb_py_sha256": sha256_file(EXP_DIR / "perturb.py"),
        "observe_py_sha256": sha256_file(EXP_DIR / "observe.py"),
        "runner_sha256": sha256_file(EXP_DIR / "run_rsi_006_q.py"),
        "discovery_seed_a": SEED_A,
        "discovery_seed_b": SEED_B,
        "thresholds": THRESH,
        "repos": {},
    }
    precondition_failures: list[str] = []

    # -- step 1: pool, SHAs, baselines -------------------------------------
    cfgs: dict[str, dict] = {}
    for entry in POOL:
        repo_root = setup_repo(entry, pool_dir)
        cfg = repo_cfg(entry, repo_root)
        cfgs[entry["name"]] = cfg
        cfg["tree_hash_pre"] = tree_hash(repo_root)

    baselines: dict[str, dict[str, str]] = {}
    for name, cfg in cfgs.items():
        try:
            b1 = observe.observe_baseline(cfg, work_dir, python)
            b2 = observe.observe_baseline(cfg, work_dir, python)
        except RuntimeError as e:
            precondition_failures.append(f"{name}: baseline run failed: {e}")
            continue
        if b1 != b2:
            precondition_failures.append(f"{name}: baseline not deterministic")
            continue
        bad = [t for t, o in b1.items() if o in ("failed", "error")]
        if bad:
            precondition_failures.append(
                f"{name}: baseline not green ({len(bad)} failing)"
            )
            continue
        baselines[name] = b1
        print(f"[{name}] baseline green + deterministic ({len(b1)} tests)",
              flush=True)

    # -- step 2: discovery mutants from frozen seeds, observe, seal --------
    discoveries: dict[str, dict[str, list[dict]]] = {}
    if not precondition_failures:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {}
            for name, cfg in cfgs.items():
                da_n, db_n, det_n, conf_n = BUDGETS[name]
                pkg = Path(cfg["package_dir"])
                mut_a = perturb.generate_mutants(pkg, SEED_A, da_n, f"{name}-A")
                mut_b = perturb.generate_mutants(pkg, SEED_B, db_n, f"{name}-B")
                discoveries[name] = {"A": [], "B": [],
                                     "mutants_A": mut_a, "mutants_B": mut_b,
                                     "det_n": det_n, "conf_n": conf_n}
                base = baselines[name]
                for m in mut_a:
                    futs[ex.submit(observe.observe_mutant, cfg, m, base,
                                   work_dir, python)] = (name, "A", m)
                for m in mut_b:
                    futs[ex.submit(observe.observe_mutant, cfg, m, base,
                                   work_dir, python)] = (name, "B", m)
            for fut in concurrent.futures.as_completed(futs):
                name, half, m = futs[fut]
                discoveries[name][half].append(fut.result())
            for name in discoveries:
                for half in ("A", "B"):
                    discoveries[name][half].sort(key=lambda o: o["mutant_id"])
        for name in discoveries:
            both = discoveries[name]["A"] + discoveries[name]["B"]
            blob = b"\n".join(canonical_bytes(o) for o in both)
            seal = hashlib.sha256(blob).hexdigest()
            (obs_dir / f"{name}-discovery.seal").write_text(seal + "\n")
            discoveries[name]["seal"] = seal
            print(f"[{name}] discovery sealed: {seal[:16]} "
                  f"({len(both)} observations)", flush=True)

    # -- step 3: fresh nonce, confirmation mutants -------------------------
    confirmations: dict[str, list[dict]] = {}
    nonce = None
    if not precondition_failures:
        nonce = os.urandom(32).hex()  # created ONLY after the seal exists
        report["confirmation_nonce"] = nonce
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {}
            for name, cfg in cfgs.items():
                conf_n = discoveries[name]["conf_n"]
                pkg = Path(cfg["package_dir"])
                mutants = perturb.generate_mutants(
                    pkg, f"RSI-006-Q-confirmation-{nonce}", conf_n,
                    f"{name}-C")
                confirmations[name] = []
                base = baselines[name]
                for m in mutants:
                    futs[ex.submit(observe.observe_mutant, cfg, m, base,
                                   work_dir, python)] = (name, m)
            for fut in concurrent.futures.as_completed(futs):
                name, m = futs[fut]
                confirmations[name].append(fut.result())
            for name in confirmations:
                confirmations[name].sort(key=lambda o: o["mutant_id"])
        print(f"[{name}] confirmation observed ({len(confirmations[name])}) "
              f"for each repo", flush=True)

    # -- step 4: determinism rerun -----------------------------------------
    det_agreement: dict[str, float] = {}
    if not precondition_failures:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {}
            for name, cfg in cfgs.items():
                det_n = discoveries[name]["det_n"]
                base = baselines[name]
                for m in discoveries[name]["mutants_A"][:det_n]:
                    futs[ex.submit(observe.observe_mutant, cfg, m, base,
                                   work_dir, python)] = (name, m)
            reruns: dict[str, list[dict]] = {n: [] for n in cfgs}
            for fut in concurrent.futures.as_completed(futs):
                name, m = futs[fut]
                reruns[name].append((m["mutant_id"], fut.result()))
        for name in cfgs:
            orig = {o["mutant_id"]: canonical_bytes(o)
                    for o in discoveries[name]["A"]}
            agree = sum(
                1 for mid, ro in reruns[name]
                if orig.get(mid) == canonical_bytes(ro)
            )
            det_agreement[name] = agree / len(reruns[name]) if reruns[name] else 0.0
            print(f"[{name}] determinism rerun agreement: "
                  f"{det_agreement[name]:.3f}", flush=True)

    # -- step 5: metrics + verdict -----------------------------------------
    causes: list[str] = []
    for name, cfg in cfgs.items():
        entry_report: dict = {"tree_hash_pre": cfg["tree_hash_pre"]}
        if precondition_failures:
            entry_report["status"] = "precondition_failed"
        else:
            disc = discoveries[name]["A"] + discoveries[name]["B"]
            conf = confirmations[name]
            kr = kill_rate(disc)
            entry_report["n_discovery"] = len(disc)
            entry_report["n_confirmation"] = len(conf)
            entry_report["kill_rate_discovery"] = kr
            entry_report["kill_rate_confirmation"] = kill_rate(conf)
            entry_report["det_rerun_agreement"] = det_agreement[name]
            entry_report["collection_error_rate"] = sum(
                1 for o in disc if o["collection_error"]) / len(disc)
            entry_report["discovery_seal"] = discoveries[name]["seal"]

            op_a = op_kill_rates(discoveries[name]["A"])
            op_b = op_kill_rates(discoveries[name]["B"])
            op_c = op_kill_rates(conf)
            entry_report["op_kill_rates"] = {"A": op_a, "B": op_b,
                                             "confirmation": op_c}
            counts_a = {o["operator"] for o in discoveries[name]["A"]}
            from collections import Counter
            ca, cb = Counter(o["operator"] for o in discoveries[name]["A"]), \
                     Counter(o["operator"] for o in discoveries[name]["B"])
            shared = [op for op in op_a
                      if ca[op] >= THRESH["stab_min_per_half"]
                      and cb.get(op, 0) >= THRESH["stab_min_per_half"]]
            entry_report["stab_operators"] = shared
            if len(shared) >= THRESH["stab_min_operators"]:
                xs = [op_a[op] for op in shared]
                ys = [op_b[op] for op in shared]
                entry_report["stab_spearman"] = spearman(xs, ys)
                entry_report["stab_max_abs_diff"] = max(
                    abs(a - b) for a, b in zip(xs, ys))
            else:
                entry_report["stab_spearman"] = None
                entry_report["stab_max_abs_diff"] = None

            # --- threshold checks ---
            if det_agreement[name] < THRESH["qdet_agreement"]:
                causes.append(f"{name}: Q-DET agreement "
                              f"{det_agreement[name]} < 1.0")
            if not (THRESH["kill_rate_lo"] <= kr <= THRESH["kill_rate_hi"]):
                causes.append(f"{name}: Q-SIG kill rate {kr:.3f} outside "
                              f"[0.05, 0.95]")
            if len(shared) < THRESH["stab_min_operators"]:
                causes.append(f"{name}: Q-STAB only {len(shared)} qualifying "
                              f"operators (< 3)")
            else:
                if entry_report["stab_max_abs_diff"] > THRESH["stab_abs_tol"]:
                    causes.append(
                        f"{name}: Q-STAB max |dA-dB| "
                        f"{entry_report['stab_max_abs_diff']:.3f} > 0.25")
                if entry_report["stab_spearman"] < THRESH["stab_spearman_min"]:
                    causes.append(
                        f"{name}: Q-STAB spearman "
                        f"{entry_report['stab_spearman']:.3f} < 0.7")
            for op in shared:
                if abs(op_c.get(op, 0.0) - (op_a[op] + op_b[op]) / 2) > \
                        THRESH["fresh_op_tol"]:
                    causes.append(f"{name}: Q-FRESH operator {op} drifted")
            if abs(entry_report["kill_rate_confirmation"] - kr) > \
                    THRESH["fresh_overall_tol"]:
                causes.append(f"{name}: Q-FRESH overall kill rate drifted")
            if entry_report["collection_error_rate"] >= \
                    THRESH["collection_error_max"]:
                causes.append(f"{name}: collection-error rate "
                              f"{entry_report['collection_error_rate']:.3f} "
                              f">= 0.10")

        cfg_post = tree_hash(Path(cfg["repo_root"]))
        entry_report["tree_hash_post"] = cfg_post
        entry_report["repo_intact"] = cfg_post == cfg["tree_hash_pre"]
        if not entry_report["repo_intact"]:
            causes.append(f"{name}: Q-INTACT tree hash changed")
        report["repos"][name] = entry_report

    if precondition_failures:
        report["verdict"] = "INCONCLUSIVE_RSI_006_Q_PRECONDITION_FAILURE"
        report["precondition_failures"] = precondition_failures
    elif causes:
        report["verdict"] = "NOT_QUALIFIED_RSI_006_SUBSTRATE"
        report["causes"] = causes
    else:
        report["verdict"] = "QUALIFIED_RSI_006_SUBSTRATE"

    elapsed = time.time() - t0
    total_obs = sum(
        r.get("n_discovery", 0) + r.get("n_confirmation", 0)
        for r in report["repos"].values()
    )
    report["elapsed_s"] = round(elapsed, 1)
    report["observations_total"] = total_obs
    report["observations_per_min"] = round(total_obs / (elapsed / 60), 1) \
        if elapsed > 0 else 0.0

    (work_dir / "rsi-006-q-report.json").write_text(
        json.dumps(report, indent=1, sort_keys=True))
    print(f"\nverdict: {report['verdict']}")
    if causes:
        for c in causes:
            print(f"  - {c}")
    if precondition_failures:
        for p in precondition_failures:
            print(f"  ! {p}")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="RSI-006-Q substrate qualification")
    ap.add_argument("--self-check", action="store_true")
    ap.add_argument("--qualify", action="store_true")
    ap.add_argument("--work-dir", default=None)
    ap.add_argument("--pool-dir", default=None)
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()

    if args.self_check:
        self_check()
        return
    if not args.qualify:
        ap.print_help()
        sys.exit(2)
    work_dir = Path(args.work_dir or tempfile.mkdtemp(prefix="rsi-006-q-"))
    work_dir.mkdir(parents=True, exist_ok=True)
    pool_dir = Path(args.pool_dir) if args.pool_dir else work_dir / "pool"
    qualify(work_dir, pool_dir, args.workers, sys.executable)


if __name__ == "__main__":
    main()
