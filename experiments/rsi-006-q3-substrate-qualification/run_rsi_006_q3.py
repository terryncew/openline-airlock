"""RSI-006-Q3 Stage 2: scientific contact (irreversible).

Lineage: RSI-006-Q2 froze INCONCLUSIVE_RSI_006_Q2_PRECONDITION_FAILURE
(proof-only PR #158): the single-shot runner burned the one-run
authorization on an environment defect (no pytest on the host) before any
mutant was generated or observed. Q3 splits the protocol:

  Stage 1 (env_qualify.py --qualify-env): repeatable environment
  qualification. May verify the interpreter, install/freeze dependencies,
  clone and pin repositories, and run untouched baselines -- repairing and
  repeating until green. Never generates mutants, never consumes the
  scientific authorization.

  Stage 2 (this module --qualify): irreversible scientific contact.
  Refuses to start unless a frozen environment receipt still matches the
  live environment exactly. The one-run authorization is consumed only
  when the first mutant-observation process is actually started.

Authorization-consumption boundary (mechanical): a single receiver-owned
``contact.ContactGate`` over ``scientific-contact.json``. The gate's sole
mutating entry point, ``note_process_started``, is invoked by
``observe.run_suite_once`` immediately after ``subprocess.Popen`` returns
on the mutant path -- only once the mutant-observation process has
actually started. Receipt verification, feasibility guards, mutation
generation, executor creation, and failed submissions all precede any
mutant Popen, so none of them can consume authorization; the baseline
path never receives the hook. After the contact marker exists there is
no code path back to environment repair: this module contains no repair
logic and never imports env_qualify.

Usage:
  python run_rsi_006_q3.py --self-check
  python run_rsi_006_q3.py --qualify --env-receipt PATH \\
      --work-dir /tmp/rsi-006-q3 --workers 2

This stage performs NO scientific experiment beyond substrate
qualification. There are no researcher arms, no hypotheses, no predictions,
no model access, and no scientific verdicts. It qualifies the external
discovery substrate for RSI-006: generic, receiver-owned perturbations of
untouched real repositories must yield stable, reproducible,
signal-bearing observations.

Causal order (enforced):
  0. verify the frozen environment receipt against the live environment
     (no test execution, no mutant work; refuse on any drift)
  1. verify pinned repo SHAs; run the feasibility guard (static: frozen
     generator + frozen seeds + frozen budgets; NO test execution)
  2. load the frozen baseline vectors from the receipt
     (baselines ran in Stage 1; repos re-verified intact here)
  3. AUTHORIZATION CONSUMED at first mutant-observation dispatch:
     generate discovery mutants from FROZEN seeds, observe, persist
     canonical records + launch sidecars, SEAL the archive
  4. only then: fresh OS-entropy nonce -> confirmation mutants, observe,
     persist canonical records
  5. determinism rerun subset -> persist rerun pairs -> agreement check
  6. metrics vs frozen thresholds -> verdict -> report
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

import contact as contact_mod
import observe
import perturb
import pool_config
import receipt as receipt_mod

EXP_DIR = Path(__file__).resolve().parent
SPEC_PATH = EXP_DIR / "RSI_006_Q3_SPEC.md"

# Frozen discovery seeds. UNCHANGED from RSI-006-Q / Q2.
SEED_A = "RSI-006-Q-discovery-A"
SEED_B = "RSI-006-Q-discovery-B"

# Frozen mutant budgets per repo: (discovery_A, discovery_B, det_rerun,
# confirmation). UNCHANGED from RSI-006-Q2.
BUDGETS = {
    "more-itertools": (72, 72, 10, 20),
    "cachetools": (102, 102, 20, 60),
    "boltons": (70, 70, 20, 60),
    "pluggy": (51, 51, 20, 60),
}

POOL = pool_config.POOL

# Frozen thresholds. UNCHANGED from RSI-006-Q / Q2.
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

CONTACT_MARKER = "scientific-contact.json"


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


def discovery_seal_input(rows: list[dict]) -> bytes:
    """Bytes the discovery seal covers.

    The \\n-joined canonical observation bytes with no trailing newline.
    The persisted {repo}-discovery.jsonl file is exactly these bytes plus
    one trailing \\n (see persist_records).
    """
    return b"\n".join(canonical_bytes(o) for o in rows)


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


def persist_records(records_dir: Path, record_digests: dict[str, str],
                    filename: str, rows: list[dict]) -> None:
    """Write canonical per-mutant records as JSONL and bind by SHA-256.

    Each line is canonical_bytes(row): json.dumps(sort_keys=True,
    separators=(",", ":")), the same canonical form the discovery seal
    covers. Observability only: never an acceptance input.
    """
    records_dir.mkdir(parents=True, exist_ok=True)
    blob = b"\n".join(canonical_bytes(r) for r in rows) + b"\n"
    (records_dir / filename).write_bytes(blob)
    record_digests[filename] = hashlib.sha256(blob).hexdigest()


def persist_launch(launches_dir: Path, mutant_id: str, launch: dict) -> None:
    """Persist one mutant-observation launch sidecar (never canonical)."""
    launches_dir.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(launch, indent=1, sort_keys=True).encode("utf-8")
    (launches_dir / f"{mutant_id}.json").write_bytes(blob + b"\n")


def feasibility_guard(package_dir: Path, budget: int) -> dict:
    """Static pre-observation check (RSI_006_Q3_SPEC.md).

    Uses only the frozen generator, the frozen discovery seeds, and the
    frozen budget: enumerate mutation sites (static repository structure),
    shuffle with each frozen seed, take the first `budget` sites, and count
    selected mutants per operator. Passes iff BOTH halves yield at least
    THRESH["stab_min_operators"] operators with at least
    THRESH["stab_min_per_half"] selected mutants. No test execution, no
    outcome data.
    """
    detail: dict[str, dict[str, int]] = {}
    for half, seed in (("A", SEED_A), ("B", SEED_B)):
        muts = perturb.generate_mutants(package_dir, seed, budget,
                                        f"guard-{half}")
        counts: dict[str, int] = {}
        for m in muts:
            counts[m["operator"]] = counts.get(m["operator"], 0) + 1
        detail[half] = counts
    qualifying = [
        op for op in perturb.OPERATORS
        if all(detail[half].get(op, 0) >= THRESH["stab_min_per_half"]
               for half in ("A", "B"))
    ]
    return {
        "passed": len(qualifying) >= THRESH["stab_min_operators"],
        "qualifying_operators": qualifying,
        "per_half_counts": detail,
    }


# --------------------------------------------------------------------------
# self-check (non-executing w.r.t. the substrate)
# --------------------------------------------------------------------------

def _assert_no_import_of(path: Path, banned: tuple[str, ...]) -> None:
    tree = ast.parse(path.read_bytes())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods = [node.module or ""]
        else:
            continue
        for mod in mods:
            assert not any(mod == b or mod.startswith(b + ".")
                           for b in banned), \
                f"forbidden import {mod} in {path.name}"


def self_check() -> None:
    # 1. Spec exists and carries the frozen thresholds and the Q3 lineage.
    text = SPEC_PATH.read_text()
    for needle in ("RSI-006-Q3", "QUALIFIED_RSI_006_Q3_SUBSTRATE", "1.0 exact",
                   "[0.05, 0.95]", "0.25", "0.7", "0.10",
                   "INCONCLUSIVE_RSI_006_Q2_PRECONDITION_FAILURE",
                   "feasibility guard", "environment receipt",
                   "scientific contact"):
        assert needle in text, f"spec missing frozen marker: {needle}"
    for repo, budgets in (("more-itertools", "(72, 72, 10, 20)"),
                          ("cachetools", "(102, 102, 20, 60)"),
                          ("boltons", "(70, 70, 20, 60)"),
                          ("pluggy", "(51, 51, 20, 60)")):
        assert budgets in text, f"spec missing frozen budget for {repo}"
        assert BUDGETS[repo] == tuple(int(x) for x in
                                      budgets.strip("()").split(", ")), repo

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
        ov = Path(td) / "ov" / "tinypkg"
        shutil.copytree(pkg, ov)
        perturb.apply_mutant(pkg, m1[0], ov)
        changed = (ov / "mod.py").read_text() != (pkg / "mod.py").read_text()
        assert changed, "mutant application changed nothing"
        ast.parse((ov / "mod.py").read_text())

    # 4. No researcher/model-access imports anywhere in this stage.
    for path in EXP_DIR.glob("*.py"):
        _assert_no_import_of(path, FORBIDDEN_IMPORTS)

    # 5. Stage separation, statically enforced:
    #    - Stage 1 (env_qualify) never imports the mutation substrate.
    #    - Stage 2 (this runner) never imports the Stage 1 repair module.
    _assert_no_import_of(EXP_DIR / "env_qualify.py", ("perturb",))
    _assert_no_import_of(EXP_DIR / "run_rsi_006_q3.py", ("env_qualify",))

    # 6. No scientific-primary-style flags exist in this orchestrator.
    src = Path(__file__).read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and \
                getattr(node.func, "attr", "") == "add_argument":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    assert "primary" not in arg.value, arg.value
    assert ("night" + "shift") not in src.lower()

    # 7. Feasibility guard mechanics on the fixture package.
    with tempfile.TemporaryDirectory() as td:
        pkg = Path(td) / "guardpkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        flines = ["def f():"]
        for i in range(60):
            flines.append(f"    a{i} = {i} + {i+1} if x{i} > 0 else {i} - 1")
        (pkg / "mod.py").write_text("\n".join(flines) + "\n")
        small = feasibility_guard(pkg, 5)
        assert small["passed"] is False, small
        big = feasibility_guard(pkg, 90)
        assert big["passed"] is True, big
        assert len(big["qualifying_operators"]) >= 3
        assert set(big["qualifying_operators"]) <= set(perturb.OPERATORS)

    # 8. The contact boundary is mechanical and single-sited: exactly one
    #    note_process_started call exists in the whole stage, inside the
    #    dispatch hook in run_rsi_006_q3.py. The hook is invoked by
    #    observe.run_suite_once after the Popen that starts the suite
    #    subprocess -- i.e. only at actual process start. The Stage 2
    #    runner never consumes authorization anywhere else; the baseline
    #    path never receives the hook.
    def _callee(node: ast.Call) -> str:
        func = node.func
        if isinstance(func, ast.Attribute):
            return func.attr
        if isinstance(func, ast.Name):
            return func.id
        return ""

    boundary_calls: list[tuple[str, int]] = []
    for mod_path in EXP_DIR.glob("*.py"):
        mod_tree = ast.parse(mod_path.read_bytes())
        for node in ast.walk(mod_tree):
            if isinstance(node, ast.Call) \
                    and _callee(node) == "note_process_started":
                boundary_calls.append((mod_path.name, node.lineno))
    assert len(boundary_calls) == 1, \
        f"expected exactly one note_process_started call site, found {boundary_calls}"
    assert boundary_calls[0][0] == "run_rsi_006_q3.py", boundary_calls

    obs_src = (EXP_DIR / "observe.py").read_text()
    obs_tree = ast.parse(obs_src)
    fns = {n.name: n for n in ast.walk(obs_tree)
           if isinstance(n, ast.FunctionDef)}
    run_suite_fn = fns["run_suite_once"]
    popen_line = hook_line = None
    for node in ast.walk(run_suite_fn):
        if isinstance(node, ast.Call):
            name = _callee(node)
            if name == "Popen":
                popen_line = node.lineno
            elif name == "on_process_start":
                hook_line = node.lineno
    assert popen_line is not None and hook_line is not None, \
        "run_suite_once must Popen the suite and fire the contact hook"
    assert hook_line > popen_line, \
        "contact hook must fire after Popen returns (actual process start)"
    assert "on_process_start" in ast.get_source_segment(obs_src, run_suite_fn)
    baseline_seg = ast.get_source_segment(obs_src, fns["observe_baseline"])
    assert "on_process_start" not in baseline_seg, \
        "observe_baseline must never touch the contact hook"
    # The dispatch wrapper hands the hook to the mutant path.
    dispatch_fn = next(n for n in ast.walk(ast.parse(src))
                       if isinstance(n, ast.FunctionDef)
                       and n.name == "_dispatch_discovery_observations")
    dispatch_seg = ast.get_source_segment(src, dispatch_fn)
    assert "observe.observe_mutant" in dispatch_seg \
        and "_contact_hook" in dispatch_seg, \
        "dispatch must pass the contact hook to observe_mutant"

    print("RSI-006-Q3 self-check clean: spec frozen, generator deterministic, "
          "operator set bound, budgets bound to spec, feasibility guard "
          "mechanics verified, stage separation verified, contact boundary "
          "verified, no researcher code path. "
          "Substrate NOT qualified (Stage 2 --qualify only when authorized, "
          "and only with a frozen environment receipt).")


# --------------------------------------------------------------------------
# qualification run (Stage 2)
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


def _dispatch_discovery_observations(ex, futs, name, cfg, mutants, base,
                                     work_dir, python, half, gate,
                                     receipt_sha):
    """Dispatch mutant observations through the contact gate.

    Authorization is consumed by the gate, not by this dispatch: each
    observation worker invokes ``gate.note_process_started`` only after
    its mutant-observation subprocess has actually started
    (``subprocess.Popen`` returned inside ``observe.run_suite_once``).
    Executor creation here, and a failed ``submit``, never reach a
    worker, so neither can consume authorization.
    """
    for m in mutants:
        # The hook below is the stage's single authorization-consumption
        # call site. It runs inside the observation worker, and only after
        # that worker's mutant-observation subprocess has actually started
        # (observe.run_suite_once invokes it after Popen returns).
        def _contact_hook(pid: int, _mutant_id: str = m["mutant_id"]) -> None:
            gate.note_process_started(_mutant_id, receipt_sha, pid)
        fut = ex.submit(observe.observe_mutant, cfg, m, base,
                        work_dir, python, _contact_hook)
        futs[fut] = (name, half, m)


def qualify_science(work_dir: Path, pool_dir: Path, workers: int, python: str,
                    receipt_path: Path) -> dict:
    # -- step 0: environment receipt gate (no test execution, no mutants) --
    try:
        receipt = receipt_mod.verify_receipt(receipt_path, pool_dir, python)
    except receipt_mod.ReceiptError as e:
        print(f"[q3] ENVIRONMENT RECEIPT INVALID: {e}", flush=True)
        print("[q3] Stage 2 refuses to start: repair and repeat Stage 1, "
              "then freeze a new receipt.", flush=True)
        sys.exit(3)
    receipt_sha = receipt_mod.receipt_sha256(receipt_path)
    print(f"[q3] environment receipt verified: {receipt_sha[:16]}",
          flush=True)

    t0 = time.time()
    pool_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    # Observation artifact directories are created only after the
    # pre-contact guard passes: a failed guard must leave no observation
    # residue behind (the report is the only artifact).
    obs_dir = work_dir / "observations"
    launches_dir = work_dir / "launches"

    report: dict = {
        "schema": "airlock.rsi-006-q3.report.v1",
        "experiment": "RSI-006-Q3 substrate qualification",
        "stage": "scientific-contact",
        "environment_receipt_sha256": receipt_sha,
        "spec_sha256": sha256_file(SPEC_PATH),
        "perturb_py_sha256": sha256_file(EXP_DIR / "perturb.py"),
        "observe_py_sha256": sha256_file(EXP_DIR / "observe.py"),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "discovery_seed_a": SEED_A,
        "discovery_seed_b": SEED_B,
        "thresholds": THRESH,
        "budgets": BUDGETS,
        "repos": {},
    }
    precondition_failures: list[str] = []
    records_dir = work_dir / "records"
    record_digests: dict[str, str] = {}

    # -- step 1: pool, SHAs ------------------------------------------------
    cfgs: dict[str, dict] = {}
    for entry in POOL:
        repo_root = setup_repo(entry, pool_dir)
        cfg = repo_cfg(entry, repo_root)
        cfgs[entry["name"]] = cfg
        cfg["tree_hash_pre"] = tree_hash(repo_root)

    # -- step 1b: feasibility guard (static; NO test execution) ------------
    guard_report: dict[str, dict] = {}
    for name, cfg in cfgs.items():
        da_n, db_n, _, _ = BUDGETS[name]
        assert da_n == db_n, f"{name}: halves must share one budget"
        result = feasibility_guard(Path(cfg["package_dir"]), da_n)
        guard_report[name] = result
        status = "PASS" if result["passed"] else "FAIL"
        print(f"[{name}] feasibility guard: {status} "
              f"(qualifying operators: "
              f"{','.join(result['qualifying_operators']) or 'none'})",
              flush=True)
        if not result["passed"]:
            precondition_failures.append(
                f"{name}: feasibility guard failed: only "
                f"{len(result['qualifying_operators'])} operators reach "
                f"10/half (< 3); Q-STAB unreachable before any test execution"
            )
    report["feasibility_guard"] = guard_report

    # -- step 2: baselines loaded from the frozen receipt -------------------
    # Baselines ran in Stage 1 (untouched repos, green + deterministic);
    # the receipt binds their vectors. Repos are re-verified intact here
    # (tree hashes); no baseline re-execution in Stage 2.
    baselines: dict[str, dict[str, str]] = {}
    if not precondition_failures:
        for name in cfgs:
            baselines[name] = receipt["baseline_vectors"][name]
            n = receipt["baseline_evidence"][name]["n_tests"]
            print(f"[{name}] baseline loaded from receipt ({n} tests)",
                  flush=True)

    # -- step 3: discovery mutants from frozen seeds, observe, persist, seal
    # AUTHORIZATION CONSUMED only when the first mutant-observation
    # subprocess actually starts (contact gate, worker-side).
    discoveries: dict[str, dict[str, list[dict]]] = {}
    if not precondition_failures:
        obs_dir.mkdir(parents=True, exist_ok=True)
        launches_dir.mkdir(parents=True, exist_ok=True)
        records_dir.mkdir(parents=True, exist_ok=True)
        gate = contact_mod.ContactGate(work_dir / CONTACT_MARKER)
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
                _dispatch_discovery_observations(
                    ex, futs, name, cfg, mut_a, base, work_dir, python,
                    "A", gate, receipt_sha)
                _dispatch_discovery_observations(
                    ex, futs, name, cfg, mut_b, base, work_dir, python,
                    "B", gate, receipt_sha)
            for fut in concurrent.futures.as_completed(futs):
                name, half, m = futs[fut]
                outcome = fut.result()
                discoveries[name][half].append(outcome["record"])
                persist_launch(launches_dir, m["mutant_id"], outcome["launch"])
            for name in discoveries:
                for half in ("A", "B"):
                    discoveries[name][half].sort(key=lambda o: o["mutant_id"])
        for name in discoveries:
            both = discoveries[name]["A"] + discoveries[name]["B"]
            blob = discovery_seal_input(both)
            seal = hashlib.sha256(blob).hexdigest()
            (obs_dir / f"{name}-discovery.seal").write_text(seal + "\n")
            discoveries[name]["seal"] = seal
            persist_records(records_dir, record_digests,
                            f"{name}-discovery.jsonl", both)
            print(f"[{name}] discovery sealed: {seal[:16]} "
                  f"({len(both)} observations)", flush=True)

    # -- step 4: fresh nonce, confirmation mutants, persist ----------------
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
                    pkg, f"RSI-006-Q3-confirmation-{nonce}", conf_n,
                    f"{name}-C")
                confirmations[name] = []
                base = baselines[name]
                for m in mutants:
                    futs[ex.submit(observe.observe_mutant, cfg, m, base,
                                   work_dir, python)] = (name, m)
            for fut in concurrent.futures.as_completed(futs):
                name, m = futs[fut]
                outcome = fut.result()
                confirmations[name].append(outcome["record"])
                persist_launch(launches_dir, m["mutant_id"], outcome["launch"])
            for name in confirmations:
                confirmations[name].sort(key=lambda o: o["mutant_id"])
                persist_records(records_dir, record_digests,
                                f"{name}-confirmation.jsonl",
                                confirmations[name])
        print(f"[{name}] confirmation observed ({len(confirmations[name])}) "
              f"for each repo", flush=True)

    # -- step 5: determinism rerun, persist pairs --------------------------
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
                outcome = fut.result()
                reruns[name].append((m["mutant_id"], outcome["record"]))
                persist_launch(launches_dir, m["mutant_id"] + "-rerun",
                               outcome["launch"])
        for name in cfgs:
            orig = {o["mutant_id"]: o for o in discoveries[name]["A"]}
            pairs = []
            agree = 0
            for mid, ro in reruns[name]:
                oo = orig.get(mid)
                a = (oo is not None
                     and canonical_bytes(oo) == canonical_bytes(ro))
                agree += 1 if a else 0
                pairs.append({"mutant_id": mid,
                              "original": oo,
                              "rerun": ro,
                              "agree": a})
            pairs.sort(key=lambda p: p["mutant_id"])
            persist_records(records_dir, record_digests,
                            f"{name}-det-reruns.jsonl", pairs)
            det_agreement[name] = agree / len(reruns[name]) if reruns[name] else 0.0
            print(f"[{name}] determinism rerun agreement: "
                  f"{det_agreement[name]:.3f}", flush=True)

    # -- step 6: metrics + verdict -----------------------------------------
    report["record_digests"] = record_digests
    contact_path = work_dir / CONTACT_MARKER
    if contact_path.exists():
        report["scientific_contact"] = json.loads(contact_path.read_bytes())
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
        report["verdict"] = "INCONCLUSIVE_RSI_006_Q3_PRECONDITION_FAILURE"
        report["precondition_failures"] = precondition_failures
    elif causes:
        report["verdict"] = "NOT_QUALIFIED_RSI_006_Q3_SUBSTRATE"
        report["causes"] = causes
    else:
        report["verdict"] = "QUALIFIED_RSI_006_Q3_SUBSTRATE"

    elapsed = time.time() - t0
    total_obs = sum(
        r.get("n_discovery", 0) + r.get("n_confirmation", 0)
        for r in report["repos"].values()
    )
    report["elapsed_s"] = round(elapsed, 1)
    report["observations_total"] = total_obs
    report["observations_per_min"] = round(total_obs / (elapsed / 60), 1) \
        if elapsed > 0 else 0.0

    (work_dir / "rsi-006-q3-report.json").write_text(
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
    ap = argparse.ArgumentParser(
        description="RSI-006-Q3 Stage 2: scientific contact (irreversible; "
                    "requires a frozen environment receipt)")
    ap.add_argument("--self-check", action="store_true")
    ap.add_argument("--qualify", action="store_true")
    ap.add_argument("--env-receipt", default=None)
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
    if not args.env_receipt:
        print("[q3] --env-receipt is required: Stage 2 cannot start without "
              "a frozen environment receipt.", flush=True)
        sys.exit(2)
    work_dir = Path(args.work_dir or tempfile.mkdtemp(prefix="rsi-006-q3-"))
    work_dir.mkdir(parents=True, exist_ok=True)
    pool_dir = Path(args.pool_dir) if args.pool_dir else work_dir / "pool"
    qualify_science(work_dir, pool_dir, args.workers, sys.executable,
                    Path(args.env_receipt))


if __name__ == "__main__":
    main()
