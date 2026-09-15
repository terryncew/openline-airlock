"""RSI-006-Q5 Stage 1: environment qualification (repeatable until green).

This module owns the pre-contact qualification of the Q5 execution
environment and freezes the ``airlock.rsi-006-q5.env-receipt.v1`` receipt
through :mod:`environment_receipt`. It preserves Q3's Stage 1 contract:

* repeatable until green; repairs environment/setup failures and repeats
  after a documented repair;
* selects/verifies the interpreter, installs missing test dependencies
  only when explicitly allowed, clones exact pinned repos, verifies
  exact checkout/tree, runs untouched baselines twice (green +
  deterministic admission), and persists full launch evidence.

Stage 1 may NEVER: import/load ``perturb``; generate mutants; execute
mutant outcomes; use discovery/confirmation seeds in an outcome-bearing
way; import or begin Q4 ``ScientificTransaction``; import Q5
``q5_adapter`` or ``execution_ledger``; create ContactGate state; create
scientific-contact state; or create a tx/confirmation nonce. Hashing
execution files is allowed; importing or executing them is not.

Before ANY environment mutation, Stage 1 preflights (pure reads only):
  a. Q3 live files are byte-identical to the frozen Q3 receipt;
  b. the merged Q4 transaction file is unchanged;
  c. the production execution manifest is valid and complete;
  d. every required execution file is present -- the Q5 Stage 2
     runner (``run_rsi_006_q5.py``) is present and listed, so the
     execution surface is complete. Completeness is not authorization:
     no production Stage 1 run has occurred, no environment receipt
     exists, and scientific contact requires a separately authorized
     invocation against a verified receipt;
  e. the qualification-critical implementation files
     (``stage1/env_qualify.py``, ``environment_receipt.py``,
     ``execution_manifest.json``) are byte-identical to the declared
     source commit -- the receipt binds what decided admissibility,
     not just what may later execute. Binding the commit SHA alone is
     insufficient: a dirty working tree can execute bytes that are
     not in that commit.

Q3 is read-only. This module reuses Q3's already-tested helpers
(interpreter probing, dependency install evidence, repo setup at exact
pins, untouched baseline launches) but implements its own two-run
admission loop: Q3's ``run_baseline_checks`` persists both baseline runs
to the same evidence filename, so run 2 overwrites run 1's launch
record (and both recorded hashes describe run 2). Q5 keeps Q3's
admission semantics while persisting each run's launch record to its
own file.

Usage:
  python stage1/env_qualify.py --arm-storage --durable-root DIR
  python stage1/env_qualify.py --qualify-env --durable-root DIR
      [--python EXE] [--install-deps | --no-install-deps]

There is deliberately no --manifest / --pool / --boot-id flag: the
production execution manifest cannot be replaced or weakened from the
CLI, and boot identity cannot be overridden.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import fcntl
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

STAGE1_DIR = Path(__file__).resolve().parent
Q5_DIR = STAGE1_DIR.parent
Q3_DIR = Q5_DIR.parent / "rsi-006-q3-substrate-qualification"
REPO_ROOT = Q5_DIR.parent.parent

sys.path.insert(0, str(Q3_DIR))
import pool_config as q3_pool  # noqa: E402  (frozen pool facts; read-only)
import receipt as q3_receipt_mod  # noqa: E402  (frozen helpers; read-only)
import env_qualify as q3_env  # noqa: E402  (frozen helpers; read-only)
import observe as q3_observe  # noqa: E402  (frozen baseline launches)
sys.path.insert(0, str(Q5_DIR))
import environment_receipt as q5_receipt  # noqa: E402

# Frozen pins the preflight checks enforce (pure reads, no mutation).
FROZEN_Q3_RECEIPT_SHA256 = \
    "d89327dcceb1536d7f66c5d1257a15f9b0de3b9f4c19ef75549eadaa7515acaa"
FROZEN_Q4_STRANSACTION_SHA256 = \
    "d7a54c1b4a658d7e566464d6ed5ebaf194ab868a70544c2155053a9a90797b04"

VOLATILE_ROOTS = ("/tmp", "/var/tmp", "/dev/shm")
RECEIPT_NAME = "q5-environment-receipt.json"
WITNESS_NAME = "storage-witness.json"
ATTEMPTS_DIR = "stage1-attempts"
LOCK_NAME = "stage1.lock"
POOL_DIR_NAME = "repo-pool"

Q3_RECEIPT_REL = "proofs/rsi-006-q3/environment-receipt.json"
Q4_STRANSACTION_REL = \
    "experiments/rsi-006-q4-durable-transaction/stransaction.py"
Q5_RECEIPT_MODULE_REL = \
    "experiments/rsi-006-q5-durable-substrate-qualification/environment_receipt.py"


class Stage1Error(RuntimeError):
    """Stage 1 refused or failed; evidence was preserved."""


class ManifestLockedError(Stage1Error):
    """The execution surface is incomplete; refusing before mutation."""


class QualifierBindingError(Stage1Error):
    """A qualification-critical file does not match its declared source."""


class WitnessError(Stage1Error):
    """The durable-storage witness is missing, corrupt, or unproven."""


class SourceDriftError(Stage1Error):
    """Source or environment binding drifted mid-qualification: the
    pre-freeze preflight did not reproduce the initial binding, or the
    Airlock HEAD moved during qualification."""


class Stage1Locked(Stage1Error):
    """Another Stage 1 qualifier holds the exclusion lock."""


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        json.dumps(obj, indent=1, sort_keys=True).encode("utf-8") + b"\n")


def resolve_durable_root(raw: str | Path) -> Path:
    """Resolve the durable root; reject known volatile roots (pure)."""
    root = Path(raw).expanduser().resolve()
    for volatile in VOLATILE_ROOTS:
        v = Path(volatile).resolve()
        if root == v or v in root.parents:
            raise Stage1Error(
                f"durable root {root} is volatile ({volatile}); Q5 must "
                f"not entrust post-contact continuation to ephemeral "
                f"storage (Q3's exact failure). Choose a durable path.")
    return root


def _production_paths() -> dict:
    return {
        "repo_root": REPO_ROOT,
        "q3_dir": REPO_ROOT / "experiments"
        / "rsi-006-q3-substrate-qualification",
        "q3_receipt_path": REPO_ROOT / Q3_RECEIPT_REL,
        "q4_path": REPO_ROOT / Q4_STRANSACTION_REL,
        "manifest_path": Q5_DIR / "execution_manifest.json",
    }


def _resolve_layout(manifest_path=None, repo_root=None, q3_dir=None,
                    q3_receipt_path=None, q4_path=None,
                    q3_receipt_sha256=None, q4_sha256=None) -> dict:
    """Resolve production-or-fixture paths and frozen pins.

    All parameters default to the production layout; tests inject
    fixtures through these internal parameters only. There is no CLI
    override for any of them by design.
    """
    prod = _production_paths()
    return {
        "repo_root": Path(repo_root) if repo_root else prod["repo_root"],
        "q3_dir": Path(q3_dir) if q3_dir else prod["q3_dir"],
        "q3_receipt_path": Path(q3_receipt_path) if q3_receipt_path
        else prod["q3_receipt_path"],
        "q4_path": Path(q4_path) if q4_path else prod["q4_path"],
        "manifest_path": Path(manifest_path) if manifest_path
        else prod["manifest_path"],
        "q3_receipt_sha256": q3_receipt_sha256 or FROZEN_Q3_RECEIPT_SHA256,
        "q4_sha256": q4_sha256 or FROZEN_Q4_STRANSACTION_SHA256,
    }


def preflight(repo_root: Path, q3_dir: Path, q3_receipt_path: Path,
              q4_path: Path, manifest_path: Path, *,
              q3_receipt_sha256: str = FROZEN_Q3_RECEIPT_SHA256,
              q4_sha256: str = FROZEN_Q4_STRANSACTION_SHA256,
              manifest_required: tuple[str, ...] | None = None,
              qualifier_provenance: dict | None = None) -> dict:
    """Pre-contact checks; pure reads, no mutation of any kind.

    a. Q3 live files byte-identical to the frozen Q3 receipt;
    b. merged Q4 transaction file unchanged;
    c. execution manifest valid;
    d. every required execution file present;
    e. qualification-critical implementation files byte-identical to
       the declared source commit.

    ``qualifier_provenance`` is the fixture-only injection
    (``{"root", "source_commit", "code_hashes"}``); production callers
    pass nothing and get the git-based HEAD correspondence check.
    There is no CLI override for either path by design.

    Raises ManifestLockedError (naming the missing files) when the
    execution surface is incomplete, and QualifierBindingError when the
    qualifier implementation does not match its declared source -- both
    before dependency installation, repo clone/update, baseline
    execution, witness mutation, receipt creation, contact state, or
    transaction state.
    """
    repo_root, q3_dir = Path(repo_root), Path(q3_dir)
    q3_receipt_path, q4_path = Path(q3_receipt_path), Path(q4_path)
    manifest_path = Path(manifest_path)

    # (a) Q3 byte-identical to its frozen receipt.
    if q5_receipt.sha256_file(q3_receipt_path) != q3_receipt_sha256:
        raise Stage1Error(
            f"frozen Q3 receipt drifted: {q3_receipt_path}")
    q3_receipt = json.loads(q3_receipt_path.read_bytes())
    if q3_receipt.get("schema") != "airlock.rsi-006-q3.env-receipt.v1":
        raise Stage1Error("frozen Q3 receipt schema unexpected")
    for name, frozen_hash in q3_receipt["code_hashes"].items():
        live = q5_receipt.sha256_file(q3_dir / name)
        if live != frozen_hash:
            raise Stage1Error(f"Q3 file changed since freeze: {name}")

    # (b) Merged Q4 transaction layer unchanged.
    live_q4 = q5_receipt.sha256_file(q4_path)
    if live_q4 != q4_sha256:
        raise Stage1Error(
            f"Q4 stransaction.py changed since merge: {live_q4}")

    # (c/d) Execution manifest valid and complete.
    try:
        binding = q5_receipt.validate_manifest(
            manifest_path, repo_root,
            required=(manifest_required
                      if manifest_required is not None
                      else q5_receipt.REQUIRED_MANIFEST_FILES))
    except q5_receipt.ManifestIncomplete as e:
        raise ManifestLockedError(
            "execution surface incomplete: refusing BEFORE any "
            "environment mutation (no dependency install, no repo "
            f"clone/update, no baseline, no receipt): missing: {e.missing}"
        ) from None

    # (e) Qualifier implementation binding: the exact bytes that decide
    #     admissibility must correspond to the declared source commit.
    #     Runs after the manifest lock so the missing-runner refusal
    #     keeps its exact identity on the production path.
    qualifier_binding = _qualifier_preflight(qualifier_provenance)

    return {
        "q3_receipt": q3_receipt,
        "manifest_binding": binding,
        "qualifier_binding": qualifier_binding,
    }


def _require_stable_binding(initial_binding: dict, initial_head: str,
                            final_binding: dict, final_head: str) -> None:
    """Fail closed unless the pre-freeze preflight exactly reproduces the
    initial source/environment binding and the Airlock HEAD is unchanged.

    Pure comparison. A qualification must never span two source states:
    on any drift no receipt may be frozen, the completed attempt
    evidence is preserved exactly as produced, and a new Stage 1
    attempt is required once the source state is stable. The receipt's
    ``airlock_commit`` must come from the binding that survived both
    checks, never from an unpaired final ``git rev-parse HEAD``.
    """
    problems = []
    if final_head != initial_head:
        problems.append(
            "airlock source commit moved mid-qualification: "
            f"initial={initial_head} at-freeze={final_head}")
    if final_binding != initial_binding:
        problems.append(
            "source/environment binding drifted mid-qualification: "
            "the final preflight does not reproduce the initial binding")
    if problems:
        raise SourceDriftError(
            "; ".join(problems) + " -- refusing to freeze a receipt "
            "spanning two source states; no receipt frozen, attempt "
            "evidence preserved; repeat Stage 1 after the source state "
            "is stable")


def production_preflight() -> dict:
    """Preflight against the production layout (no overrides exist)."""
    p = _production_paths()
    return preflight(p["repo_root"], p["q3_dir"], p["q3_receipt_path"],
                     p["q4_path"], p["manifest_path"])


def _git_bytes(args: list[str], cwd: Path) -> bytes:
    """Run a git plumbing command; fail closed (pure read)."""
    out = subprocess.run(["git", "-C", str(cwd), *args],
                         capture_output=True)
    if out.returncode != 0:
        detail = (out.stdout + out.stderr).decode(
            errors="replace").strip()[:200]
        raise QualifierBindingError(
            f"git {' '.join(args)} failed at {cwd}: {detail}")
    return out.stdout


def _qualifier_preflight(qualifier_provenance: dict | None = None) -> dict:
    """Bind the exact qualifier implementation bytes; fail closed on dirty source.

    Fixture path (``qualifier_provenance`` given): the live bytes of
    each qualification-critical file under ``provenance["root"]`` must
    equal the declared ``provenance["code_hashes"]``; the declared
    ``source_commit`` is recorded as-is.

    Production path (``None``): every qualification-critical tracked
    file beneath the experiment directory must be byte-identical to the
    bytes committed at HEAD -- ``git show HEAD:path`` output is hashed
    and compared against the live file. A dirty, staged-but-different,
    or untracked file fails closed: the source commit SHA alone cannot
    prove which bytes executed.

    Pure reads only. Returns ``{"source_commit", "code_hashes"}`` for
    the receipt.
    """
    critical = q5_receipt.QUALIFIER_CRITICAL_FILES
    if qualifier_provenance is not None:
        root = Path(qualifier_provenance["root"])
        declared = qualifier_provenance.get("code_hashes")
        live: dict[str, str] = {}
        for rel in critical:
            p = root / rel
            if not p.is_file():
                raise QualifierBindingError(
                    f"qualification-critical file missing: {p}")
            live[rel] = q5_receipt.sha256_file(p)
        if (not isinstance(declared, dict)
                or set(declared) != set(live)
                or any(live[r] != declared[r] for r in live)):
            bad = [r for r in live
                   if not isinstance(declared, dict)
                   or live[r] != declared.get(r)]
            raise QualifierBindingError(
                "qualification-critical file bytes differ from the "
                "declared source binding while the declared "
                "source_commit "
                f"({qualifier_provenance.get('source_commit')!r}) is "
                f"unchanged: {sorted(bad)}; refusing before any "
                f"environment mutation")
        return {"source_commit": qualifier_provenance["source_commit"],
                "code_hashes": live}

    exp_dir = Q5_DIR
    top = _git_bytes(["rev-parse", "--show-toplevel"], exp_dir)
    repo = Path(top.decode().strip()).resolve()
    head = _git_bytes(["rev-parse", "HEAD"], exp_dir).decode().strip()
    live = {}
    for rel in critical:
        f = (exp_dir / rel).resolve()
        try:
            repo_rel = f.relative_to(repo).as_posix()
        except ValueError:
            raise QualifierBindingError(
                f"qualification-critical file {f} is not inside the git "
                f"repository at {repo}") from None
        try:
            _git_bytes(["ls-files", "--error-unmatch", "--", repo_rel],
                       repo)
        except QualifierBindingError:
            raise QualifierBindingError(
                f"qualification-critical file {rel} is not tracked at "
                f"HEAD; refusing before any environment mutation") from None
        committed = _git_bytes(["show", f"HEAD:{repo_rel}"], repo)
        live_hash = q5_receipt.sha256_file(f)
        if q5_receipt.sha256_bytes(committed) != live_hash:
            raise QualifierBindingError(
                f"qualification-critical file {rel} differs from HEAD "
                f"({head[:12]}): the working tree is dirty or the file "
                f"differs from its committed bytes; refusing before any "
                f"environment mutation")
        live[rel] = live_hash
    return {"source_commit": head, "code_hashes": live}


# ---------------------------------------------------------------------------
# Durable-storage witness (two-boot proof)
# ---------------------------------------------------------------------------

def read_boot_id() -> str:
    """Current Linux boot ID (no override exists by design)."""
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError as e:
        raise Stage1Error(f"cannot read Linux boot ID: {e}") from None


def _fs_identity(root: Path) -> dict:
    # Single implementation lives in the receipt module (the verifier
    # needs it too); this stays as the Stage 1-local name.
    return q5_receipt.fs_identity(root)


def _atomic_write_json(path: Path, obj: dict) -> None:
    """Atomic replace + fsync (arming may re-arm; the receipt may not)."""
    tmp = path.parent / f".{path.name}.tmp-{os.getpid()}"
    with open(tmp, "wb") as f:
        data = json.dumps(obj, indent=1, sort_keys=True).encode("utf-8") \
            + b"\n"
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def arm_storage(durable_root: str | Path, *,
                boot_id_reader=read_boot_id,
                manifest_path=None, repo_root=None, q3_dir=None,
                q3_receipt_path=None, q4_path=None,
                q3_receipt_sha256=None, q4_sha256=None,
                manifest_required=None,
                qualifier_provenance=None) -> dict:
    """Arm the durable-storage witness (no scientific work of any kind).

    Preflights the execution manifest and the qualifier implementation
    binding first -- the same common preflight as --qualify-env -- then
    generates a random witness nonce, records the current boot ID, and
    atomically persists the witness beneath the durable root. Performs
    NO repo clone, dependency install, baseline execution, or scientific
    work. The operator must reboot the host and then run --qualify-env:
    only a witness that survived a real boot transition is accepted.
    """
    root = resolve_durable_root(durable_root)
    layout = _resolve_layout(manifest_path, repo_root, q3_dir,
                             q3_receipt_path, q4_path,
                             q3_receipt_sha256, q4_sha256)
    preflight(layout["repo_root"], layout["q3_dir"],
              layout["q3_receipt_path"], layout["q4_path"],
              layout["manifest_path"],
              q3_receipt_sha256=layout["q3_receipt_sha256"],
              q4_sha256=layout["q4_sha256"],
              manifest_required=manifest_required,
              qualifier_provenance=qualifier_provenance)  # common preflight; refuses before any write
    root.mkdir(parents=True, exist_ok=True)
    with stage1_lock(root):
        witness = {
            "schema": q5_receipt.WITNESS_SCHEMA,
            "witness_nonce": secrets.token_hex(32),
            "armed_boot_id": boot_id_reader(),
            "armed_at": time.time(),
            "durable_root": str(root),
            "fs": _fs_identity(root),
        }
        _atomic_write_json(root / WITNESS_NAME, witness)
    return witness


def _load_witness(root: Path) -> dict:
    path = root / WITNESS_NAME
    if not path.is_file():
        raise WitnessError(
            f"no storage witness at {path}: arm with --arm-storage, "
            f"reboot the host, then repeat --qualify-env")
    try:
        witness = json.loads(path.read_bytes())
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise WitnessError(f"storage witness corrupted: {e}") from None
    if witness.get("schema") != q5_receipt.WITNESS_SCHEMA:
        raise WitnessError(
            f"storage witness schema mismatch: {witness.get('schema')!r}")
    for key in ("witness_nonce", "armed_boot_id", "armed_at", "durable_root"):
        if key not in witness:
            raise WitnessError(f"storage witness missing {key!r}")
    return witness


@contextlib.contextmanager
def stage1_lock(root: Path):
    """Non-blocking exclusion: one qualifier per durable root.

    A second concurrent qualifier fails here, before any mutation of
    the repo pool, evidence, witness, or receipt.
    """
    lock_path = Path(root) / LOCK_NAME
    f = open(lock_path, "w")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        raise Stage1Locked(
            f"another Stage 1 qualifier holds {lock_path}; refusing to "
            f"mutate the same pool/evidence concurrently") from None
    try:
        yield
    finally:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()


def next_attempt_id(root: Path) -> str:
    """Next append-only attempt id (call only while holding the lock)."""
    d = Path(root) / ATTEMPTS_DIR
    d.mkdir(parents=True, exist_ok=True)
    ids = [p.name for p in d.iterdir()
           if p.is_dir() and len(p.name) == 6 and p.name.isdigit()]
    return f"{(max((int(i) for i in ids), default=0) + 1):06d}"


# ---------------------------------------------------------------------------
# Two-run baseline admission (Q3 semantics, per-run evidence files)
# ---------------------------------------------------------------------------

def _persist_run_evidence(evidence_dir: Path, repo: str, run: int,
                          launch: dict, n_tests: int) -> Path:
    record = {
        "classification": "baseline_launch_ok",
        "repo": repo,
        "run": run,
        "n_tests": n_tests,
        "launch": launch,
    }
    path = evidence_dir / f"{repo}-baseline-run-{run}.json"
    _write_json(path, record)
    return path


def run_baseline_checks(cfgs: dict[str, dict], work_dir: Path, python: str,
                        evidence_dir: Path) -> tuple[dict, dict]:
    """Run each untouched baseline twice; admit only green+deterministic.

    Same admission contract as Q3's Stage 1 (two untouched runs, every
    test green, identical outcome vectors, repair-and-repeat on failure --
    never a blind same-environment retry), but each run's full launch
    record persists to its own file. Q3's helper persists both runs to
    one filename, so run 2 overwrites run 1's record; Q5 does not repeat
    that. Launches go through Q3's tested ``observe_baseline`` helper.
    """
    vectors: dict[str, dict[str, str]] = {}
    evidence: dict[str, dict] = {}
    for name, cfg in cfgs.items():
        try:
            v1, launch1 = q3_observe.observe_baseline(cfg, work_dir, python)
            v2, launch2 = q3_observe.observe_baseline(cfg, work_dir, python)
        except q3_observe.LaunchError as e:
            p = evidence_dir / f"{name}-baseline-run-failed.json"
            _write_json(p, {"classification": "baseline_launch_failed",
                            "repo": name, "launch": e.launch})
            raise q3_env.EnvironmentNotReady(
                f"{name}: baseline launch failed; evidence: {p.name}; "
                f"repair the environment and repeat Stage 1") from e
        p1 = _persist_run_evidence(evidence_dir, name, 1, launch1, len(v1))
        p2 = _persist_run_evidence(evidence_dir, name, 2, launch2, len(v2))
        if v1 != v2:
            raise q3_env.EnvironmentNotReady(
                f"{name}: baseline not deterministic; repair and repeat "
                f"Stage 1 (evidence: {p1.name}, {p2.name})")
        bad = [t for t, o in v1.items() if o in ("failed", "error")]
        if bad:
            raise q3_env.EnvironmentNotReady(
                f"{name}: baseline not green ({len(bad)} failing); repair "
                f"and repeat Stage 1 (evidence: {p1.name}, {p2.name})")
        vectors[name] = v1
        evidence[name] = {
            "n_tests": len(v1),
            "deterministic": True,
            "vector_sha256": q5_receipt.sha256_bytes(
                q5_receipt.canonical_bytes(v1)),
            "launch_paths": {"run1": p1, "run2": p2},
        }
        print(f"[stage1] {name}: baseline green + deterministic "
              f"({len(v1)} tests)", flush=True)
    return vectors, evidence


# ---------------------------------------------------------------------------
# Qualification orchestrator
# ---------------------------------------------------------------------------

def _attempt_evidence_files(attempt_dir: Path, root: Path) -> dict:
    files: dict[str, str] = {}
    for p in sorted(attempt_dir.rglob("*")):
        if p.is_file() and p.name != "attempt-manifest.json":
            files[p.relative_to(root).as_posix()] = \
                q5_receipt.sha256_file(p)
    return files


def qualify_env(
    durable_root: str | Path,
    *,
    python: str | None = None,
    install_deps: bool = True,
    pool: list[dict] | None = None,
    manifest_path: str | Path | None = None,
    repo_root: str | Path | None = None,
    q3_dir: str | Path | None = None,
    q3_receipt_path: str | Path | None = None,
    q4_path: str | Path | None = None,
    q3_receipt_sha256: str | None = None,
    q4_sha256: str | None = None,
    manifest_required: tuple[str, ...] | None = None,
    qualifier_provenance: dict | None = None,
    boot_id_reader=read_boot_id,
) -> dict:
    """Run Stage 1 to green and freeze the Q5 environment receipt.

    ``pool``/``manifest_path``/``repo_root``/``q3_*``/``q4_path``,
    the frozen pins, the manifest required-file set, and the qualifier
    provenance default to the production layout; tests pass fixtures
    through these internal parameters (there is no CLI override by
    design). Raises ManifestLockedError before any environment mutation
    when the execution surface is incomplete, and QualifierBindingError
    when the qualifier implementation does not match its declared
    source.
    """
    python = python or sys.executable
    layout = _resolve_layout(manifest_path, repo_root, q3_dir,
                             q3_receipt_path, q4_path,
                             q3_receipt_sha256, q4_sha256)
    repo_root = layout["repo_root"]
    q3_dir = layout["q3_dir"]
    q3_receipt_path = layout["q3_receipt_path"]
    q4_path = layout["q4_path"]
    manifest_path = layout["manifest_path"]

    root = resolve_durable_root(durable_root)

    # Preflight: pure reads. Refuses (ManifestLockedError /
    # QualifierBindingError) before any dependency install, repo
    # clone/update, baseline, or receipt work.
    pf = preflight(repo_root, q3_dir, q3_receipt_path, q4_path, manifest_path,
                   q3_receipt_sha256=layout["q3_receipt_sha256"],
                   q4_sha256=layout["q4_sha256"],
                   manifest_required=manifest_required,
                   qualifier_provenance=qualifier_provenance)
    # Snapshot the initial source/environment binding: the Airlock HEAD,
    # the execution-manifest binding, the qualifier-code binding, the
    # frozen Q3 receipt/code binding, and the frozen Q4 binding. The
    # receipt may only freeze a binding that survives BOTH this
    # preflight and the final pre-freeze revalidation -- a qualification
    # must never span two source states.
    initial_binding = copy.deepcopy(pf)
    initial_head = q5_receipt.git_head(repo_root)
    manifest_binding = pf["manifest_binding"]
    qualifier_binding = pf["qualifier_binding"]
    preflight_note = {"manifest_sha256":
                      manifest_binding["manifest_sha256"],
                      "qualifier": qualifier_binding}

    # Storage witness: must exist intact, from a *previous* boot, and
    # bound to this exact durable root -- before any environment work.
    witness = _load_witness(root)
    boot_now = boot_id_reader()
    if boot_now == witness["armed_boot_id"]:
        raise WitnessError(
            "storage witness was armed on this same boot; the durable "
            "root has not yet proven it survives a boot transition. "
            "Reboot the host, then repeat --qualify-env.")
    if witness["durable_root"] != str(root):
        raise WitnessError(
            f"storage witness is bound to {witness['durable_root']}, not "
            f"the selected durable root {root}")
    # The witness must still sit on the filesystem it was armed on: a
    # moved or copied durable root has not proven *its* storage durable.
    live_fs = _fs_identity(root)
    if witness.get("fs") != live_fs:
        raise WitnessError(
            f"storage witness filesystem identity changed since arming: "
            f"armed={witness.get('fs')} live={live_fs}; the durable root "
            f"was moved or copied -- re-arm on the new storage")
    witness_digest = q5_receipt.sha256_file(root / WITNESS_NAME)

    # The selected interpreter must live beneath the durable root: the
    # qualified environment (interpreter, repos, evidence) is one
    # durable unit. Checked before any environment work.
    if not q5_receipt.interpreter_path_under_root(python, root):
        raise Stage1Error(
            f"selected interpreter {python} is not beneath the durable "
            f"root {root}; create the qualification venv inside the "
            f"durable root (e.g. {root}/venv) and pass its python")

    # An already-frozen receipt is never re-qualified: verify-only.
    receipt_path = root / RECEIPT_NAME
    if receipt_path.exists():
        receipt = q5_receipt.verify_receipt(
            receipt_path, pool_dir=root / POOL_DIR_NAME, python=python,
            manifest_path=manifest_path, repo_root=repo_root,
            q3_receipt_path=q3_receipt_path, q3_code_dir=q3_dir,
            q4_path=q4_path, durable_root=root, stage2_work_dir=root,
            manifest_required=manifest_required)
        return {"status": "already_frozen",
                "receipt_sha256": q5_receipt.receipt_sha256(receipt_path),
                "receipt": receipt}

    pool_dir = root / POOL_DIR_NAME
    with stage1_lock(root):
        # Re-check under the lock: a racing qualifier may have frozen.
        if receipt_path.exists():
            receipt = q5_receipt.verify_receipt(
                receipt_path, pool_dir=root / POOL_DIR_NAME, python=python,
                manifest_path=manifest_path, repo_root=repo_root,
                q3_receipt_path=q3_receipt_path, q3_code_dir=q3_dir,
                q4_path=q4_path, durable_root=root, stage2_work_dir=root,
            manifest_required=manifest_required)
            return {"status": "already_frozen",
                    "receipt_sha256":
                        q5_receipt.receipt_sha256(receipt_path),
                    "receipt": receipt}

        attempt_id = next_attempt_id(root)
        attempt_dir = root / ATTEMPTS_DIR / attempt_id
        attempt_dir.mkdir(parents=True)
        evidence_dir = attempt_dir / "evidence"
        evidence_dir.mkdir(parents=True)
        print(f"[stage1] attempt {attempt_id} -> {attempt_dir}", flush=True)
        _write_json(attempt_dir / "preflight.json", preflight_note)

        # Interpreter identity (probed, never trusted from this process).
        try:
            ident = q3_env.verify_interpreter(python)
        except q3_env.EnvironmentNotReady as e:
            if e.evidence is not None:
                _write_json(attempt_dir / "00-interpreter-probe.json",
                            e.evidence)
            raise
        _write_json(attempt_dir / "interpreter.json", ident)
        print(f"[stage1] interpreter: {ident['executable']} "
              f"({ident['implementation']} {ident['version']})", flush=True)

        # Dependencies (install only when explicitly allowed).
        dep_lock = q3_env.ensure_dependencies(
            python, q3_pool.REQUIRED_PACKAGES, install_deps, evidence_dir)
        print(f"[stage1] dependency lock: {dep_lock}", flush=True)

        # Repos at exact pins; checkout SHA + tree hash bound.
        cfgs: dict[str, dict] = {}
        repos: dict[str, dict] = {}
        for entry in (pool if pool is not None else q3_pool.POOL):
            repo_root_path = q3_env.setup_repo(entry, pool_dir)
            cfg = q3_env.repo_cfg(entry, repo_root_path)
            cfgs[entry["name"]] = cfg
            repos[entry["name"]] = {
                "url": entry["url"],
                "pin": entry["sha"],
                "checkout_sha": q5_receipt.repo_checkout_sha(
                    repo_root_path),
                "tree_hash": q5_receipt.tree_hash(repo_root_path),
            }
        _write_json(attempt_dir / "repos.json", repos)

        # Untouched baselines, twice each; green + deterministic admission.
        vectors, baseline_evidence = run_baseline_checks(
            cfgs, attempt_dir, python, evidence_dir)

        # Attempt evidence manifest (append-only; never rewritten).
        evidence_files = _attempt_evidence_files(attempt_dir, root)
        _write_json(attempt_dir / "attempt-manifest.json",
                    {"attempt": attempt_id, "files": evidence_files})
        evidence_files[(attempt_dir / "attempt-manifest.json")
                       .relative_to(root).as_posix()] = \
            q5_receipt.sha256_file(attempt_dir / "attempt-manifest.json")

        # Baseline evidence with durable-root-relative launch bindings.
        frozen_baseline_evidence = {}
        for name, ev in baseline_evidence.items():
            frozen_baseline_evidence[name] = {
                "n_tests": ev["n_tests"],
                "deterministic": ev["deterministic"],
                "vector_sha256": ev["vector_sha256"],
                "launch_sha256": {
                    "run1": q5_receipt.sha256_file(ev["launch_paths"]["run1"]),
                    "run2": q5_receipt.sha256_file(ev["launch_paths"]["run2"]),
                },
                "launch_files": {
                    "run1": ev["launch_paths"]["run1"]
                    .relative_to(root).as_posix(),
                    "run2": ev["launch_paths"]["run2"]
                    .relative_to(root).as_posix(),
                },
            }

        q3_code_hashes = dict(pf["q3_receipt"]["code_hashes"])

        # Final preflight: re-run the exact same pure checks immediately
        # before freezing, after baselines and after all attempt evidence
        # is durable. Any mid-qualification source drift fails closed
        # here: no receipt is frozen, the completed attempt evidence is
        # preserved exactly as produced, and a new Stage 1 attempt is
        # required once the source state is stable. The receipt's
        # airlock_commit comes from the stable binding below, never
        # from an unpaired final `git rev-parse HEAD`.
        final_pf = preflight(
            repo_root, q3_dir, q3_receipt_path, q4_path, manifest_path,
            q3_receipt_sha256=layout["q3_receipt_sha256"],
            q4_sha256=layout["q4_sha256"],
            manifest_required=manifest_required,
            qualifier_provenance=qualifier_provenance)
        _require_stable_binding(initial_binding, initial_head,
                                final_pf, q5_receipt.git_head(repo_root))

        receipt = q5_receipt.build_receipt(
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
            q4_relpath=q4_path.relative_to(repo_root).as_posix(),
            q5_module_relpath=Q5_RECEIPT_MODULE_REL,
            q5_module_sha256=q5_receipt.sha256_file(
                REPO_ROOT / Q5_RECEIPT_MODULE_REL),
            witness_digest=witness_digest,
            witness_relpath=WITNESS_NAME,
            armed_boot_id=witness["armed_boot_id"],
            qualify_boot_id=boot_now,
            armed_at=witness["armed_at"],
            durable_root=str(root),
            witness_fs=dict(witness.get("fs", {})),
            host_platform=__import__("platform").platform(),
        )
        q5_receipt.freeze_receipt(receipt_path, receipt)
        print(f"[stage1] Q5 ENVIRONMENT RECEIPT frozen: {receipt_path}",
              flush=True)
        print(f"[stage1] receipt sha256: "
              f"{q5_receipt.receipt_sha256(receipt_path)}", flush=True)
        return {"status": "frozen",
                "attempt": attempt_id,
                "receipt_sha256": q5_receipt.receipt_sha256(receipt_path),
                "receipt": receipt}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="RSI-006-Q5 Stage 1: environment qualification "
                    "(pre-contact; repeatable until green)")
    ap.add_argument("--arm-storage", action="store_true",
                    help="arm the durable-storage witness (no env work)")
    ap.add_argument("--qualify-env", action="store_true",
                    help="run Stage 1 and freeze the Q5 environment receipt")
    ap.add_argument("--durable-root", required=True,
                    help="durable root holding Stage 1 evidence, the frozen "
                         "receipt, the repo pool, and the witness")
    ap.add_argument("--python", default=sys.executable,
                    help="selected interpreter; must live beneath "
                    "--durable-root (e.g. <root>/venv/bin/python)")
    ap.add_argument("--install-deps", dest="install_deps",
                    action="store_true", default=True)
    ap.add_argument("--no-install-deps", dest="install_deps",
                    action="store_false")
    args = ap.parse_args()

    if args.arm_storage == args.qualify_env:
        ap.error("exactly one of --arm-storage / --qualify-env is required")
    try:
        if args.arm_storage:
            witness = arm_storage(args.durable_root)
            print("[stage1] storage witness armed at "
                  f"{args.durable_root}; boot {witness['armed_boot_id'][:8]}",
                  flush=True)
            print("[stage1] REBOOT the host, then run --qualify-env: "
                  "qualification requires the witness to survive a later "
                  "boot.", flush=True)
        else:
            result = qualify_env(args.durable_root, python=args.python,
                                 install_deps=args.install_deps)
            if result["status"] == "already_frozen":
                print("[stage1] receipt already frozen and verified; "
                      "no re-qualification performed.", flush=True)
            else:
                print("[stage1] Stage 1 GREEN: receipt frozen; environment "
                      "immutable for the scientific run.", flush=True)
    except (Stage1Error, q3_env.EnvironmentNotReady,
            q5_receipt.ReceiptError, q5_receipt.ManifestError) as e:
        print(f"[stage1] NOT READY: {e}", flush=True)
        print("[stage1] evidence preserved under the attempt directory; "
              "repair and repeat Stage 1.", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
