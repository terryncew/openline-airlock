"""RSI-006-Q6 Stage 1: environment qualification wrapper (Gate 2A).

Thin additive layer over the frozen Q5/Q3 Stage-1 machinery (prereg
§9). It performs Q6-scoped constant checks (Q6 manifest schema, Q6
required files, Q6 qualifier binding) and delegates every
qualification operation to the existing helpers: durable-root
resolution, storage witness, interpreter probing, dependency lock,
repo setup at exact pins, two-run baseline admission, attempt
evidence, and the atomic freeze pattern. No Q5/Q4/Q3 file is
modified; no Q5 Stage-1 logic is duplicated.

The storage witness is shared with Q5's arming format: it proves the
*storage* survived a boot transition, and Q5 is terminal, so exactly
one qualifier (Q6) arms it.

Stage 1 may NEVER: generate mutants; execute mutant outcomes; import
or begin Q4 ScientificTransaction; import q5_adapter or
execution_ledger; create ContactGate state; create scientific-contact
state; or create a tx/confirmation nonce. Hashing execution files is
allowed; importing or executing them is not.
"""

import argparse
import copy
import json
import platform
import sys
import time
from pathlib import Path

Q6_DIR = Path(__file__).resolve().parent
Q5_DIR = Q6_DIR.parent / "rsi-006-q5-durable-substrate-qualification"
Q5_STAGE1_DIR = Q5_DIR / "stage1"
REPO_ROOT = Q6_DIR.parent.parent

for _p in (str(Q5_STAGE1_DIR), str(Q5_DIR), str(Q6_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import env_qualify as q5stage  # noqa: E402  (frozen; read-only reuse)
import environment_receipt as q5r  # noqa: E402  (frozen; read-only)
import q6_receipt as q6r  # noqa: E402  (Q6 binding layer)

Q6_RECEIPT_NAME = "q6-environment-receipt.json"


def q6_preflight(repo_root, q3_dir, q3_receipt_path, q4_path,
                 manifest_path, *, q3_receipt_sha256=None,
                 q4_sha256=None, qualifier_provenance=None) -> dict:
    """Pre-contact checks; pure reads, no mutation of any kind.

    a. Q3 live files byte-identical to the frozen Q3 receipt;
    b. merged Q4 transaction file unchanged;
    c/d. Q6 execution manifest valid and complete (Q6 schema, Q6
       required files);
    e. Q6 qualification-critical implementation files bound to the
       declared source (dirty working tree fails closed).

    ``qualifier_provenance`` is the fixture-only injection
    (``{"root", "source_commit", "code_hashes"}``); production
    callers pass nothing and get the git-based HEAD correspondence
    check. Raises the frozen Stage1 error types before any
    environment mutation.
    """
    repo_root = Path(repo_root)
    q3_receipt_path, q4_path = Path(q3_receipt_path), Path(q4_path)
    manifest_path = Path(manifest_path)
    q3_receipt_sha256 = (
        q3_receipt_sha256 or q5stage.FROZEN_Q3_RECEIPT_SHA256)
    q4_sha256 = q4_sha256 or q5stage.FROZEN_Q4_STRANSACTION_SHA256

    # (a) Q3 byte-identical to its frozen receipt.
    if q5r.sha256_file(q3_receipt_path) != q3_receipt_sha256:
        raise q5stage.Stage1Error(
            f"frozen Q3 receipt drifted: {q3_receipt_path}")
    q3_receipt = json.loads(q3_receipt_path.read_bytes())
    if q3_receipt.get("schema") != "airlock.rsi-006-q3.env-receipt.v1":
        raise q5stage.Stage1Error("frozen Q3 receipt schema unexpected")
    for name, frozen_hash in q3_receipt["code_hashes"].items():
        live = q5r.sha256_file(Path(q3_dir) / name)
        if live != frozen_hash:
            raise q5stage.Stage1Error(
                f"Q3 file changed since freeze: {name}")

    # (b) Merged Q4 transaction layer unchanged.
    live_q4 = q5r.sha256_file(q4_path)
    if live_q4 != q4_sha256:
        raise q5stage.Stage1Error(
            f"Q4 stransaction.py changed since merge: {live_q4}")

    # (c/d) Q6 execution manifest valid and complete. Q5's manifest
    # loader hardcodes the Q5 schema, so the Q6 wrapper performs its
    # own constant check (inside validate_q6_manifest) and delegates
    # only to the pure hashing helpers.
    try:
        binding = q6r.validate_q6_manifest(repo_root, manifest_path)
    except q5r.ManifestError as e:
        raise q5stage.ManifestLockedError(
            "Q6 execution surface invalid or incomplete: refusing "
            "BEFORE any environment mutation (no dependency install, "
            "no repo clone/update, no baseline, no receipt): "
            f"{e}"
        ) from None

    # (e) Q6 qualifier implementation binding.
    qualifier_binding = _q6_qualifier_preflight(qualifier_provenance)

    return {
        "q3_receipt": q3_receipt,
        "manifest_binding": binding,
        "qualifier_binding": qualifier_binding,
    }


def _q6_qualifier_preflight(qualifier_provenance=None) -> dict:
    """Bind the exact Q6 qualifier implementation bytes.

    Mirrors Q5's _qualifier_preflight over Q6's critical files. Pure
    reads only. Returns ``{"source_commit", "code_hashes"}``.
    """
    critical = q6r.Q6_QUALIFIER_CRITICAL_FILES
    if qualifier_provenance is not None:
        root = Path(qualifier_provenance["root"])
        declared = qualifier_provenance.get("code_hashes")
        live = {}
        for rel in critical:
            p = root / rel
            if not p.is_file():
                raise q5stage.QualifierBindingError(
                    f"Q6 qualification-critical file missing: {p}")
            live[rel] = q5r.sha256_file(p)
        if (not isinstance(declared, dict)
                or set(declared) != set(live)
                or any(live[r] != declared[r] for r in live)):
            bad = [r for r in live
                   if not isinstance(declared, dict)
                   or live[r] != declared.get(r)]
            raise q5stage.QualifierBindingError(
                "Q6 qualification-critical file bytes differ from the "
                "declared source binding while the declared "
                "source_commit "
                f"({qualifier_provenance.get('source_commit')!r}) is "
                f"unchanged: {sorted(bad)}; refusing before any "
                "environment mutation")
        return {"source_commit": qualifier_provenance["source_commit"],
                "code_hashes": live}

    exp_dir = Q6_DIR
    top = q5stage._git_bytes(["rev-parse", "--show-toplevel"], exp_dir)
    repo = Path(top.decode().strip()).resolve()
    head = q5stage._git_bytes(["rev-parse", "HEAD"], exp_dir).decode()
    head = head.strip()
    live = {}
    for rel in critical:
        f = (exp_dir / rel).resolve()
        try:
            repo_rel = f.relative_to(repo).as_posix()
        except ValueError:
            raise q5stage.QualifierBindingError(
                f"Q6 qualification-critical file {f} is not inside the "
                f"git repository at {repo}") from None
        try:
            q5stage._git_bytes(
                ["ls-files", "--error-unmatch", "--", repo_rel], repo)
        except q5stage.QualifierBindingError:
            raise q5stage.QualifierBindingError(
                f"Q6 qualification-critical file {rel} is not tracked "
                "at HEAD; refusing before any environment mutation"
            ) from None
        committed = q5stage._git_bytes(["show", f"HEAD:{repo_rel}"], repo)
        live_hash = q5r.sha256_file(f)
        if q5r.sha256_bytes(committed) != live_hash:
            raise q5stage.QualifierBindingError(
                f"Q6 qualification-critical file {rel} differs from "
                f"HEAD ({head[:12]}): the working tree is dirty or the "
                "file differs from its committed bytes; refusing "
                "before any environment mutation")
        live[rel] = live_hash
    return {"source_commit": head, "code_hashes": live}


def q6_arm_storage(durable_root, *, boot_id_reader=None,
                   repo_root=None, qualifier_provenance=None) -> dict:
    """Arm the durable-storage witness for Q6 (no scientific work).

    Mirrors Q5's arm_storage, but the common preflight is the Q6
    preflight (Q6 manifest + Q6 qualifier binding). The witness file
    itself is shared: it proves the storage, not the qualifier.
    """
    import secrets

    root = q5stage.resolve_durable_root(durable_root)
    repo_root = Path(repo_root or REPO_ROOT)
    manifest_path = repo_root / q6r.Q6_MANIFEST_RELPATH
    q3_dir = repo_root / "experiments" / "rsi-006-q3-substrate-qualification"
    q3_receipt_path = repo_root / q5stage.Q3_RECEIPT_REL
    q4_path = repo_root / q5stage.Q4_STRANSACTION_REL
    q6_preflight(repo_root, q3_dir, q3_receipt_path, q4_path,
                 manifest_path,
                 qualifier_provenance=qualifier_provenance)
    root.mkdir(parents=True, exist_ok=True)
    with q5stage.stage1_lock(root):
        witness = {
            "schema": q5r.WITNESS_SCHEMA,
            "witness_nonce": secrets.token_hex(32),
            "armed_boot_id": (boot_id_reader or q5stage.read_boot_id)(),
            "armed_at": time.time(),
            "durable_root": str(root),
            "fs": q5stage._fs_identity(root),
        }
        q5stage._atomic_write_json(root / q5stage.WITNESS_NAME, witness)
    return witness


def qualify_q6_env(
    durable_root,
    *,
    python: str | None = None,
    install_deps: bool = True,
    pool: list[dict] | None = None,
    repo_root=None,
    qualifier_provenance: dict | None = None,
    boot_id_reader=None,
) -> dict:
    """Run Q6 Stage 1 to green and freeze the Q6 environment receipt.

    The 20-point Stage-1 contract, executed by orchestration over the
    frozen helpers: pure Q6 preflight before any mutation; witness from
    a previous boot; interpreter beneath the durable root; exact pinned
    repos; untouched baselines twice with green+deterministic
    admission; append-only attempt evidence; final preflight
    reproducing the initial binding; exactly-once Q6 receipt freeze;
    the frozen receipt is returned (live re-verification is a
    separate, explicitly invoked step).
    """
    python = python or sys.executable
    repo_root = Path(repo_root or REPO_ROOT)
    manifest_path = repo_root / q6r.Q6_MANIFEST_RELPATH
    q3_dir = repo_root / "experiments" / "rsi-006-q3-substrate-qualification"
    q3_receipt_path = repo_root / q5stage.Q3_RECEIPT_REL
    q4_path = repo_root / q5stage.Q4_STRANSACTION_REL

    root = q5stage.resolve_durable_root(durable_root)

    # Preflight: pure reads, Q6 constants. Refuses before any
    # dependency install, repo clone/update, baseline, or receipt work.
    pf = q6_preflight(repo_root, q3_dir, q3_receipt_path, q4_path,
                      manifest_path,
                      qualifier_provenance=qualifier_provenance)
    initial_binding = copy.deepcopy(pf)
    initial_head = q5r.git_head(repo_root)
    manifest_binding = pf["manifest_binding"]
    qualifier_binding = pf["qualifier_binding"]
    preflight_note = {"manifest_sha256":
                      manifest_binding["manifest_sha256"],
                      "qualifier": qualifier_binding}

    # Storage witness: intact, from a previous boot, bound to this
    # exact durable root and its live filesystem identity.
    witness = q5stage._load_witness(root)
    boot_now = (boot_id_reader or q5stage.read_boot_id)()
    if boot_now == witness["armed_boot_id"]:
        raise q5stage.WitnessError(
            "storage witness was armed on this same boot; the durable "
            "root has not yet proven it survives a boot transition. "
            "Reboot the host, then repeat --qualify-env.")
    if witness["durable_root"] != str(root):
        raise q5stage.WitnessError(
            f"storage witness is bound to {witness['durable_root']}, "
            f"not the selected durable root {root}")
    live_fs = q5stage._fs_identity(root)
    if witness.get("fs") != live_fs:
        raise q5stage.WitnessError(
            f"storage witness filesystem identity changed since "
            f"arming: armed={witness.get('fs')} live={live_fs}")
    witness_digest = q5r.sha256_file(root / q5stage.WITNESS_NAME)

    if not q5r.interpreter_path_under_root(python, root):
        raise q5stage.Stage1Error(
            f"selected interpreter {python} is not beneath the durable "
            f"root {root}")

    # An already-frozen Q6 receipt is never re-qualified: verify-only.
    receipt_path = root / Q6_RECEIPT_NAME
    if receipt_path.exists():
        receipt = q6r.verify_q6_production_receipt(
            receipt_path, pool_dir=root / q5stage.POOL_DIR_NAME,
            python=python, stage2_work_dir=root)
        return {"status": "already_frozen",
                "receipt_sha256": q5r.receipt_sha256(receipt_path),
                "receipt": receipt}

    pool_dir = root / q5stage.POOL_DIR_NAME
    with q5stage.stage1_lock(root):
        if receipt_path.exists():
            receipt = q6r.verify_q6_production_receipt(
                receipt_path, pool_dir=pool_dir,
                python=python, stage2_work_dir=root)
            return {"status": "already_frozen",
                    "receipt_sha256": q5r.receipt_sha256(receipt_path),
                    "receipt": receipt}

        attempt_id = q5stage.next_attempt_id(root)
        attempt_dir = root / q5stage.ATTEMPTS_DIR / attempt_id
        attempt_dir.mkdir(parents=True)
        evidence_dir = attempt_dir / "evidence"
        evidence_dir.mkdir(parents=True)
        print(f"[q6-stage1] attempt {attempt_id} -> {attempt_dir}",
              flush=True)
        q5stage._write_json(attempt_dir / "preflight.json",
                            preflight_note)

        try:
            ident = q5stage.q3_env.verify_interpreter(python)
        except q5stage.q3_env.EnvironmentNotReady as e:
            if e.evidence is not None:
                q5stage._write_json(
                    attempt_dir / "00-interpreter-probe.json",
                    e.evidence)
            raise
        q5stage._write_json(attempt_dir / "interpreter.json", ident)
        print(f"[q6-stage1] interpreter: {ident['executable']}",
              flush=True)

        dep_lock = q5stage.q3_env.ensure_dependencies(
            python, q5stage.q3_pool.REQUIRED_PACKAGES, install_deps,
            evidence_dir)

        cfgs: dict[str, dict] = {}
        repos: dict[str, dict] = {}
        for entry in (pool if pool is not None else q5stage.q3_pool.POOL):
            repo_root_path = q5stage.q3_env.setup_repo(entry, pool_dir)
            cfg = q5stage.q3_env.repo_cfg(entry, repo_root_path)
            cfgs[entry["name"]] = cfg
            repos[entry["name"]] = {
                "url": entry["url"],
                "pin": entry["sha"],
                "checkout_sha": q5r.repo_checkout_sha(repo_root_path),
                "tree_hash": q5r.tree_hash(repo_root_path),
            }
        q5stage._write_json(attempt_dir / "repos.json", repos)

        vectors, baseline_evidence = q5stage.run_baseline_checks(
            cfgs, attempt_dir, python, evidence_dir)

        evidence_files = q5stage._attempt_evidence_files(
            attempt_dir, root)
        q5stage._write_json(attempt_dir / "attempt-manifest.json",
                            {"attempt": attempt_id,
                             "files": evidence_files})
        evidence_files[(attempt_dir / "attempt-manifest.json")
                       .relative_to(root).as_posix()] = \
            q5r.sha256_file(attempt_dir / "attempt-manifest.json")

        frozen_baseline_evidence = {}
        for name, ev in baseline_evidence.items():
            frozen_baseline_evidence[name] = {
                "n_tests": ev["n_tests"],
                "deterministic": ev["deterministic"],
                "vector_sha256": ev["vector_sha256"],
                "launch_sha256": {
                    "run1": q5r.sha256_file(
                        ev["launch_paths"]["run1"]),
                    "run2": q5r.sha256_file(
                        ev["launch_paths"]["run2"]),
                },
                "launch_files": {
                    "run1": ev["launch_paths"]["run1"]
                    .relative_to(root).as_posix(),
                    "run2": ev["launch_paths"]["run2"]
                    .relative_to(root).as_posix(),
                },
            }

        q3_code_hashes = dict(pf["q3_receipt"]["code_hashes"])

        final_pf = q6_preflight(
            repo_root, q3_dir, q3_receipt_path, q4_path, manifest_path,
            qualifier_provenance=qualifier_provenance)
        q5stage._require_stable_binding(initial_binding, initial_head,
                                        final_pf,
                                        q5r.git_head(repo_root))

        q4_rel = q4_path.relative_to(repo_root).as_posix()
        receipt = q6r.build_q6_receipt(
            frozen_at=time.time(),
            python=python,
            interpreter=ident,
            dep_lock=dep_lock,
            repos=repos,
            vectors=vectors,
            vector_hashes={n: baseline_evidence[n]["vector_sha256"]
                           for n in vectors},
            baseline_evidence=frozen_baseline_evidence,
            attempt_id=attempt_id,
            attempt_evidence_files=evidence_files,
            airlock_commit=initial_head,
            manifest_binding=manifest_binding,
            qualifier_binding=qualifier_binding,
            q3_code_hashes=q3_code_hashes,
            q4_relpath=q4_rel,
            q6_module_relpath=q6r.Q6_RECEIPT_MODULE_REL,
            q6_module_sha256=q5r.sha256_file(
                REPO_ROOT / q6r.Q6_RECEIPT_MODULE_REL),
            witness_digest=witness_digest,
            witness_relpath=q5stage.WITNESS_NAME,
            armed_boot_id=witness["armed_boot_id"],
            qualify_boot_id=boot_now,
            armed_at=witness["armed_at"],
            durable_root=str(root),
            witness_fs=dict(witness.get("fs", {})),
            host_platform=platform.platform(),
        )
        q6r.freeze_q6_receipt(receipt_path, receipt)
        print(f"[q6-stage1] Q6 ENVIRONMENT RECEIPT frozen: "
              f"{receipt_path}", flush=True)
        print(f"[q6-stage1] receipt sha256: "
              f"{q5r.receipt_sha256(receipt_path)}", flush=True)
        return {"status": "frozen",
                "attempt": attempt_id,
                "receipt_sha256": q5r.receipt_sha256(receipt_path),
                "receipt": receipt}


def make_q6_receipt_verifier(receipt_path, *, pool_dir, python,
                             stage2_work_dir):
    """Build the Stage2Runner-injectable Q6 production verifier.

    Returns a zero-argument callable returning ``(receipt, sha256)``.
    It performs no baselines, no mutation, and no scientific
    execution: it re-probes the live environment and compares every
    binding against the frozen Q6 receipt. This is the verifier to
    run BEFORE any future scientific child Popen.
    """
    def _verify():
        receipt = q6r.verify_q6_production_receipt(
            receipt_path, pool_dir=pool_dir, python=python,
            stage2_work_dir=stage2_work_dir)
        return receipt, q5r.receipt_sha256(receipt_path)

    return _verify


def main() -> None:
    ap = argparse.ArgumentParser(
        description="RSI-006-Q6 Stage 1: environment qualification "
                    "wrapper (pre-contact; repeatable until green)")
    ap.add_argument("--arm-storage", action="store_true",
                    help="arm the durable-storage witness (no env work)")
    ap.add_argument("--qualify-env", action="store_true",
                    help="run Q6 Stage 1 and freeze the Q6 environment "
                         "receipt")
    ap.add_argument("--durable-root", required=True,
                    help="durable root holding Stage 1 evidence, the "
                         "frozen Q6 receipt, the repo pool, and the "
                         "witness")
    ap.add_argument("--python", default=sys.executable,
                    help="selected interpreter; must live beneath "
                         "--durable-root")
    ap.add_argument("--install-deps", dest="install_deps",
                    action="store_true", default=True)
    ap.add_argument("--no-install-deps", dest="install_deps",
                    action="store_false")
    args = ap.parse_args()

    if args.arm_storage == args.qualify_env:
        ap.error("exactly one of --arm-storage / --qualify-env is required")
    try:
        if args.arm_storage:
            witness = q6_arm_storage(args.durable_root)
            print("[q6-stage1] storage witness armed at "
                  f"{args.durable_root}; boot "
                  f"{witness['armed_boot_id'][:8]}", flush=True)
            print("[q6-stage1] REBOOT the host, then run --qualify-env.",
                  flush=True)
        else:
            result = qualify_q6_env(
                args.durable_root, python=args.python,
                install_deps=args.install_deps)
            if result["status"] == "already_frozen":
                print("[q6-stage1] Q6 receipt already frozen and "
                      "verified; no re-qualification performed.",
                      flush=True)
            else:
                print("[q6-stage1] Q6 Stage 1 GREEN: receipt frozen; "
                      "environment immutable for the scientific run.",
                      flush=True)
    except (q5stage.Stage1Error, q5stage.q3_env.EnvironmentNotReady,
            q5r.ReceiptError, q5r.ManifestError) as e:
        print(f"[q6-stage1] NOT READY: {e}", flush=True)
        print("[q6-stage1] evidence preserved under the attempt "
              "directory; repair and repeat Stage 1.", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
