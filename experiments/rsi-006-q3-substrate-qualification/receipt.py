"""RSI-006-Q3 environment receipt: freeze and verify.

The receipt is the executable boundary between Stage 1 (repeatable
environment qualification) and Stage 2 (irreversible scientific contact).
Stage 2 refuses to start unless a receipt exists whose bindings still
match the live environment exactly.

Binding rule: the receipt binds the *selected* interpreter, never the
process running the check. ``interpreter_identity(python)`` and
``dependency_lock(python, ...)`` interrogate the selected executable
through an observable subprocess; the running process's
``platform.python_version()`` / ``importlib.metadata`` are never used.

The receipt binds repository *contents* (pins, checkout SHAs, tree
hashes), not the pool directory path: two paths holding identical trees
are the same environment, and Stage 2 re-verifies every tree before any
scientific contact.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

EXP_DIR = Path(__file__).resolve().parent

RECEIPT_SCHEMA = "airlock.rsi-006-q3.env-receipt.v1"

# Q3 code files whose hashes bind the receipt to this exact implementation.
CODE_FILES = (
    "RSI_006_Q3_SPEC.md",
    "perturb.py",
    "observe.py",
    "pool_config.py",
    "receipt.py",
    "env_qualify.py",
    "run_rsi_006_q3.py",
    "contact.py",
)

_IDENTITY_PROBE = (
    "import sys, platform, json; print(json.dumps({"
    "'version': platform.python_version(), "
    "'implementation': platform.python_implementation(), "
    "'executable': sys.executable}))"
)

_LOCK_PROBE = (
    "import importlib.metadata, json, sys\n"
    "req = json.loads(sys.argv[1])\n"
    "lock, missing = {}, []\n"
    "for n in req:\n"
    "    try:\n"
    "        lock[n] = importlib.metadata.version(n)\n"
    "    except importlib.metadata.PackageNotFoundError:\n"
    "        missing.append(n)\n"
    "print(json.dumps({'lock': lock, 'missing': missing}))"
)


class ReceiptError(RuntimeError):
    """The environment receipt is missing or no longer matches."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if ".git" in path.parts or not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        h.update(rel.encode("utf-8") + b"\x00" + path.read_bytes() + b"\x00")
    return h.hexdigest()


def interpreter_identity(python: str) -> dict:
    """Probe the *selected* interpreter; never trust the running process.

    The binary is spawned exactly as given (a venv path must not be
    resolved before spawning: resolving ``venv/bin/python`` to
    ``/usr/bin/python3`` would escape the venv). The recorded
    ``executable`` is the resolved canonical path.

    Raises OSError if the binary cannot be spawned (the caller converts
    this into its own evidence-carrying error) and ReceiptError if the
    probe itself fails or is unparseable.
    """
    exe = str(Path(python).resolve())
    out = subprocess.run(
        [python, "-c", _IDENTITY_PROBE],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        raise ReceiptError(
            f"interpreter identity probe failed for {python}: "
            f"{(out.stdout + out.stderr).strip()[:500]}")
    try:
        info = json.loads(out.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as je:
        raise ReceiptError(
            f"interpreter identity probe unparseable for {python}: {je}"
        ) from None
    for key in ("version", "implementation", "executable"):
        if key not in info:
            raise ReceiptError(
                f"interpreter identity probe missing {key!r} for {python}")
    return {
        "executable": exe,
        "version": info["version"],
        "implementation": info["implementation"],
    }


def dependency_lock(python: str, packages: tuple[str, ...]) -> dict[str, str]:
    """Exact installed versions, read from the *selected* interpreter.

    The binary is spawned exactly as given (see interpreter_identity for
    why it must not be resolved first). Raises OSError if the binary
    cannot be spawned (the caller converts this) and ReceiptError if a
    required package is missing there.
    """
    out = subprocess.run(
        [python, "-c", _LOCK_PROBE, json.dumps(list(packages))],
        capture_output=True, text=True, timeout=60,
    )
    if out.returncode != 0:
        raise ReceiptError(
            f"dependency lock probe failed for {python}: "
            f"{(out.stdout + out.stderr).strip()[:500]}")
    try:
        info = json.loads(out.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as je:
        raise ReceiptError(
            f"dependency lock probe unparseable for {python}: {je}"
        ) from None
    missing = info.get("missing", [])
    if missing:
        raise ReceiptError(
            f"required package(s) not installed in {python}: {missing}")
    return dict(info.get("lock", {}))


def live_code_hashes() -> dict[str, str]:
    return {name: sha256_file(EXP_DIR / name) for name in CODE_FILES}


def repo_checkout_sha(repo_root: Path) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def freeze_receipt(
    path: Path,
    *,
    frozen_at: float,
    python: str,
    interpreter: dict,
    lock: dict[str, str],
    repos: dict[str, dict],
    vectors: dict[str, dict[str, str]],
    baseline_evidence: dict[str, dict],
    code_hashes: dict[str, str],
) -> dict:
    """Write the environment receipt; return it.

    ``repos`` maps name -> {url, pin, checkout_sha, tree_hash}.
    ``baseline_evidence`` maps name -> {vector_sha256, launch_sha256,
    n_tests, deterministic}.
    """
    import platform as _platform

    receipt = {
        "schema": RECEIPT_SCHEMA,
        "stage": "environment-qualification",
        "frozen_at": frozen_at,
        "python": python,
        "interpreter": interpreter,
        "dependency_lock": lock,
        "repos": repos,
        "baseline_vectors": vectors,
        "baseline_evidence": baseline_evidence,
        "code_hashes": code_hashes,
        "host": {
            "platform": _platform.platform(),
            "frozen_at": frozen_at,
        },
    }
    path.write_bytes(canonical_bytes(receipt) + b"\n")
    return receipt


def load_receipt(path: Path) -> dict:
    if not path.exists():
        raise ReceiptError(f"environment receipt not found: {path}")
    try:
        receipt = json.loads(path.read_bytes())
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ReceiptError(f"environment receipt unparseable: {e}")
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise ReceiptError(
            f"environment receipt schema mismatch: {receipt.get('schema')}")
    return receipt


def verify_receipt(path: Path, pool_dir: Path, python: str) -> dict:
    """Verify every live binding against the frozen receipt.

    Raises ReceiptError on any drift. Returns the receipt on success.
    Performs no test execution and no mutant work. The selected
    interpreter is probed directly; an unlaunchable binary is a refusal,
    not a traceback.
    """
    receipt = load_receipt(path)

    try:
        live_interp = interpreter_identity(python)
    except OSError as oe:
        raise ReceiptError(
            f"cannot probe selected interpreter {python}: {oe}") from None
    if receipt["interpreter"] != live_interp:
        raise ReceiptError(
            f"interpreter drift: receipt={receipt['interpreter']} "
            f"live={live_interp}")

    try:
        live_lock = dependency_lock(
            python, tuple(sorted(receipt["dependency_lock"])))
    except OSError as oe:
        raise ReceiptError(
            f"cannot probe dependency lock in {python}: {oe}") from None
    if receipt["dependency_lock"] != live_lock:
        raise ReceiptError(
            f"dependency lock drift: receipt={receipt['dependency_lock']} "
            f"live={live_lock}")

    live_code = live_code_hashes()
    if receipt["code_hashes"] != live_code:
        drifted = [k for k in live_code
                   if receipt["code_hashes"].get(k) != live_code[k]]
        raise ReceiptError(f"Q3 code drift: {drifted}")

    for name, frozen in receipt["repos"].items():
        root = pool_dir / name
        if not root.is_dir():
            raise ReceiptError(f"repo missing from pool: {name}")
        live_sha = repo_checkout_sha(root)
        if live_sha != frozen["checkout_sha"]:
            raise ReceiptError(
                f"repo {name} checkout drift: receipt={frozen['checkout_sha']} "
                f"live={live_sha}")
        live_tree = tree_hash(root)
        if live_tree != frozen["tree_hash"]:
            raise ReceiptError(f"repo {name} tree drift since receipt freeze")

    # Self-consistency: the frozen vectors must match their frozen hashes.
    # (The vectors themselves are trusted via the receipt; Stage 2 never
    # reruns baselines.)
    for name, vec in receipt["baseline_vectors"].items():
        ev = receipt["baseline_evidence"][name]
        if sha256_bytes(canonical_bytes(vec)) != ev["vector_sha256"]:
            raise ReceiptError(
                f"baseline vector hash mismatch for {name}: receipt tampered")

    return receipt


def receipt_sha256(path: Path) -> str:
    return sha256_file(path)
