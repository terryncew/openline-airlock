"""RSI-006-Q3 Stage 1: environment qualification (repeatable until green).

This module owns terminal execution of the environment. It may verify the
interpreter, install and freeze dependencies, clone and pin repositories,
and run untouched baselines -- repairing setup issues and repeating failed
checks as needed. It must never generate mutants, execute mutant outcomes,
issue a confirmation nonce, touch discovery/confirmation seeds in an
outcome-bearing way, or consume the one-run scientific authorization.

Structural guarantee: this module never imports ``perturb`` (asserted by
contract test, statically and dynamically). The observation harness it
uses loads the mutation substrate lazily, only inside the mutant path.

Every failed launch preserves its full evidence: exact argv, interpreter,
cwd, environment identity, exit status, stdout, stderr, JUnit report when
produced, start/end timestamps, and a classification/disposition.
``collection_error`` is a disposition only, never evidence by itself.

Usage:
  python env_qualify.py --qualify-env --work-dir DIR [--pool-dir DIR]
                        [--python EXE] [--install-deps | --no-install-deps]
                        [--receipt PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import observe
import pool_config
import receipt as receipt_mod

EXP_DIR = Path(__file__).resolve().parent

# Volatile receipt fields excluded when comparing two receipts for
# repeatability (bindings must be identical; timestamps may differ).
VOLATILE_RECEIPT_FIELDS = ("frozen_at",)


class EnvironmentNotReady(RuntimeError):
    """Stage 1 did not reach green; evidence was persisted."""

    def __init__(self, message: str, evidence: dict | None = None):
        super().__init__(message)
        self.evidence = evidence


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        json.dumps(obj, indent=1, sort_keys=True).encode("utf-8") + b"\n")


def _probe_failed_record(python: str, argv: list[str], oe: OSError,
                         start_ts: float) -> dict:
    """Build the launch record for an interpreter that cannot be spawned."""
    return {
        "schema": "airlock.rsi-006-q3.launch-evidence.v1",
        "classification": "interpreter_probe_failed",
        "launch": {
            "argv": argv,
            "interpreter": python,
            "cwd": os.getcwd(),
            "env_fingerprint": {},
            "exit_status": None,
            "stdout_sha256": None,
            "stderr_sha256": None,
            "stdout_len": 0,
            "stderr_len": 0,
            "start_ts": start_ts,
            "end_ts": time.time(),
            "disposition": "launch_spawn_failed",
            "error": str(oe),
        },
    }


def verify_interpreter(python: str) -> dict:
    """Record the exact interpreter identity (no execution of suites)."""
    start_ts = time.time()
    try:
        out = subprocess.run(
            [python, "--version"], capture_output=True, text=True, timeout=30)
    except OSError as oe:
        # The selected interpreter cannot even be spawned. Fail with the
        # probe preserved as a launch record: a bare "not found" is exactly
        # what Q2 could not diagnose.
        raise EnvironmentNotReady(
            f"interpreter probe failed for {python}: {oe}",
            evidence=_probe_failed_record(
                python, [python, "--version"], oe, start_ts)) from None
    try:
        ident = receipt_mod.interpreter_identity(python)
    except (OSError, receipt_mod.ReceiptError) as oe:
        # The selected interpreter cannot be interrogated. Fail with the
        # probe preserved as a launch record: a bare "not found" is exactly
        # what Q2 could not diagnose.
        raise EnvironmentNotReady(
            f"interpreter identity probe failed for {python}: {oe}",
            evidence=_probe_failed_record(
                python, [python, "-c", "<identity probe>"], oe,
                start_ts)) from None
    version_output = (out.stdout + out.stderr).strip()
    if out.returncode != 0:
        raise EnvironmentNotReady(
            f"interpreter failed --version: {python}")
    print(f"[env] interpreter --version: {version_output}", flush=True)
    return ident


def _check_import(python: str, package: str) -> bool:
    """Check package importability in the *selected* interpreter."""
    try:
        out = subprocess.run(
            [python, "-c", f"import {package}"],
            capture_output=True, timeout=30)
    except OSError as oe:
        raise EnvironmentNotReady(
            f"cannot probe imports in {python}: {oe}") from None
    return out.returncode == 0


def _pip_install(python: str, package: str, evidence_dir: Path) -> dict:
    """Install one package, preserving the full launch evidence.

    The evidence meets the same standard as suite launches: exact argv,
    interpreter, cwd, environment fingerprint, exit status, byte-exact
    stdout/stderr with hashes, and start/end timestamps -- plus the
    dependency-lock identity the install produced (the same binding the
    environment receipt freezes).
    """
    start_ts = time.time()
    argv = [python, "-m", "pip", "install", package]
    cwd = os.getcwd()
    env = dict(os.environ)
    try:
        proc = subprocess.run(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=cwd, env=env, timeout=600)
        exit_status: int | None = proc.returncode
        stdout_b, stderr_b = proc.stdout, proc.stderr
        disposition = "ok" if proc.returncode == 0 else "pip_install_failed"
        error = None
    except subprocess.TimeoutExpired as te:
        end_ts = time.time()
        stdout_b, stderr_b = te.stdout or b"", te.stderr or b""
        exit_status, disposition = None, "timeout"
        error = f"pip install timed out after 600s: {package}"
    except OSError as oe:
        end_ts = time.time()
        stdout_b, stderr_b = b"", f"pip launch failed to spawn: {oe}".encode()
        exit_status, disposition = None, "launch_spawn_failed"
        error = str(oe)
    else:
        end_ts = time.time()
    # On a successful install, bind the exact dependency-lock identity the
    # install produced; the evidence then carries the same binding the
    # environment receipt freezes.
    dep_lock = None
    if disposition == "ok":
        try:
            dep_lock = receipt_mod.dependency_lock(python, (package,))
        except (OSError, receipt_mod.ReceiptError):
            dep_lock = None
    evidence = {
        "schema": "airlock.rsi-006-q3.launch-evidence.v1",
        "classification": "dependency_install",
        "package": package,
        "dependency_lock": dep_lock,
        "launch": {
            "argv": argv,
            "interpreter": str(Path(python).resolve()),
            "cwd": cwd,
            "env_fingerprint": observe._env_fingerprint(env),
            "exit_status": exit_status,
            "stdout": observe._encode_bytes(stdout_b),
            "stderr": observe._encode_bytes(stderr_b),
            "start_ts": start_ts,
            "end_ts": end_ts,
            "disposition": disposition,
            "error": error,
        },
    }
    _write_json(evidence_dir / f"pip-install-{package}.json", evidence)
    if disposition != "ok":
        raise EnvironmentNotReady(
            f"pip install failed for {package}: {disposition} "
            f"(evidence: pip-install-{package}.json)")
    return evidence


def ensure_dependencies(python: str, packages: tuple[str, ...],
                        install: bool, evidence_dir: Path) -> dict:
    """Verify required packages import in the selected interpreter.

    Installs missing ones only when explicitly allowed. Returns the
    dependency lock probed from the selected interpreter (never the
    running process).
    """
    for package in packages:
        if not _check_import(python, package):
            if not install:
                raise EnvironmentNotReady(
                    f"required package missing in {python} and installs "
                    f"disabled: {package}")
            print(f"[env] installing missing dependency: {package}",
                  flush=True)
            _pip_install(python, package, evidence_dir)
    try:
        return receipt_mod.dependency_lock(python, packages)
    except (OSError, receipt_mod.ReceiptError) as oe:
        raise EnvironmentNotReady(
            f"dependency lock probe failed for {python}: {oe}") from None


def setup_repo(entry: dict, pool_dir: Path) -> Path:
    dest = pool_dir / entry["name"]
    if dest.exists():
        head = subprocess.run(
            ["git", "-C", str(dest), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if head != entry["sha"]:
            raise EnvironmentNotReady(
                f"{entry['name']}: existing checkout at {head}, "
                f"want {entry['sha']}")
    else:
        print(f"[env] cloning {entry['name']} @ {entry['sha'][:8]}...",
              flush=True)
        subprocess.run(
            ["git", "clone", "-q", entry["url"], str(dest)], check=True)
        subprocess.run(
            ["git", "-C", str(dest), "checkout", "-q", entry["sha"]], check=True)
        head = subprocess.run(
            ["git", "-C", str(dest), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if head != entry["sha"]:
            raise EnvironmentNotReady(
                f"{entry['name']}: SHA mismatch after clone: {head}")
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


def _persist_launch_evidence(evidence_dir: Path, repo: str, attempt: int,
                             classification: str, launch: dict,
                             extra: dict | None = None) -> Path:
    record = {
        "classification": classification,
        "repo": repo,
        "attempt": attempt,
        "launch": launch,
        **(extra or {}),
    }
    path = evidence_dir / f"{repo}-baseline-attempt-{attempt}.json"
    _write_json(path, record)
    return path


def run_baseline_checks(cfgs: dict[str, dict], work_dir: Path, python: str,
                        evidence_dir: Path
                        ) -> tuple[dict[str, dict[str, str]], dict]:
    """Run each untouched baseline twice (green + deterministic admission).

    Exactly one attempt per repo per invocation. On failure the launch
    evidence is persisted and EnvironmentNotReady is raised: the operator
    repairs the environment and invokes Stage 1 again. There is deliberately
    no blind same-environment retry -- repeating a failed launch without
    repair proves nothing. This function never consumes scientific
    authorization and never touches the mutation substrate.
    """
    vectors: dict[str, dict[str, str]] = {}
    evidence: dict[str, dict] = {}
    for name, cfg in cfgs.items():
        try:
            v1, launch1 = observe.observe_baseline(cfg, work_dir, python)
            v2, launch2 = observe.observe_baseline(cfg, work_dir, python)
        except observe.LaunchError as e:
            p = _persist_launch_evidence(
                evidence_dir, name, 1, "baseline_launch_failed", e.launch)
            raise EnvironmentNotReady(
                f"{name}: baseline launch failed; evidence: {p.name}; "
                f"repair the environment and repeat Stage 1") from e
        p1 = _persist_launch_evidence(
            evidence_dir, name, 1, "baseline_launch_ok",
            launch1, {"run": 1, "n_tests": len(v1)})
        p2 = _persist_launch_evidence(
            evidence_dir, name, 1, "baseline_launch_ok",
            launch2, {"run": 2, "n_tests": len(v2)})
        if v1 != v2:
            raise EnvironmentNotReady(
                f"{name}: baseline not deterministic; repair and repeat "
                f"Stage 1 (evidence: {p1.name}, {p2.name})")
        bad = [t for t, o in v1.items() if o in ("failed", "error")]
        if bad:
            raise EnvironmentNotReady(
                f"{name}: baseline not green ({len(bad)} failing); repair "
                f"and repeat Stage 1 (evidence: {p1.name}, {p2.name})")
        vectors[name] = v1
        evidence[name] = {
            "n_tests": len(v1),
            "deterministic": True,
            "vector_sha256": receipt_mod.sha256_bytes(
                receipt_mod.canonical_bytes(v1)),
            "launch_sha256": {
                "run1": receipt_mod.sha256_file(p1),
                "run2": receipt_mod.sha256_file(p2),
            },
        }
        print(f"[env] {name}: baseline green + deterministic "
              f"({len(v1)} tests)", flush=True)
    return vectors, evidence


def qualify_environment(pool: list[dict], work_dir: Path, pool_dir: Path,
                        python: str, install_deps: bool,
                        receipt_path: Path) -> dict:
    """Run Stage 1 to green and freeze the environment receipt."""
    work_dir.mkdir(parents=True, exist_ok=True)
    pool_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir = work_dir / "env-evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    try:
        ident = verify_interpreter(python)
    except EnvironmentNotReady as exc:
        # The interpreter could not even be probed: persist the probe
        # record before failing, so the failure is evidence, not a guess.
        if exc.evidence is not None:
            (evidence_dir / "00-interpreter-probe.json").write_text(
                json.dumps(exc.evidence, indent=2, sort_keys=True))
        raise
    print(f"[env] interpreter: {ident['executable']} "
          f"({ident['implementation']} {ident['version']})", flush=True)

    lock = ensure_dependencies(python, pool_config.REQUIRED_PACKAGES,
                               install_deps, evidence_dir)
    print(f"[env] dependency lock: {lock}", flush=True)

    cfgs: dict[str, dict] = {}
    repos: dict[str, dict] = {}
    for entry in pool:
        root = setup_repo(entry, pool_dir)
        cfg = repo_cfg(entry, root)
        cfgs[entry["name"]] = cfg
        sha = receipt_mod.repo_checkout_sha(root)
        repos[entry["name"]] = {
            "url": entry["url"],
            "pin": entry["sha"],
            "checkout_sha": sha,
            "tree_hash": receipt_mod.tree_hash(root),
        }

    vectors, baseline_evidence = run_baseline_checks(
        cfgs, work_dir, python, evidence_dir)

    frozen_at = time.time()
    receipt = receipt_mod.freeze_receipt(
        receipt_path,
        frozen_at=frozen_at,
        python=python,
        interpreter=ident,
        lock=lock,
        repos=repos,
        vectors=vectors,
        baseline_evidence=baseline_evidence,
        code_hashes=receipt_mod.live_code_hashes(),
    )
    print(f"[env] ENVIRONMENT RECEIPT frozen: {receipt_path}", flush=True)
    print(f"[env] receipt sha256: "
          f"{receipt_mod.receipt_sha256(receipt_path)}", flush=True)
    return receipt


def main() -> None:
    ap = argparse.ArgumentParser(
        description="RSI-006-Q3 Stage 1: environment qualification "
                    "(repeatable until green)")
    ap.add_argument("--qualify-env", action="store_true")
    ap.add_argument("--work-dir", default=None)
    ap.add_argument("--pool-dir", default=None)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--install-deps", dest="install_deps",
                    action="store_true", default=True)
    ap.add_argument("--no-install-deps", dest="install_deps",
                    action="store_false")
    ap.add_argument("--receipt", default=None)
    args = ap.parse_args()

    if not args.qualify_env:
        ap.print_help()
        sys.exit(2)
    work_dir = Path(args.work_dir or "rsi-006-q3-env")
    work_dir.mkdir(parents=True, exist_ok=True)
    pool_dir = Path(args.pool_dir) if args.pool_dir else work_dir / "pool"
    receipt_path = Path(args.receipt) if args.receipt \
        else work_dir / "environment-receipt.json"
    try:
        qualify_environment(pool_config.POOL, work_dir, pool_dir,
                            args.python, args.install_deps, receipt_path)
    except EnvironmentNotReady as e:
        print(f"[env] NOT READY: {e}", flush=True)
        print("[env] launch evidence preserved under "
              f"{work_dir / 'env-evidence'}; repair and repeat Stage 1.",
              flush=True)
        sys.exit(1)
    print("[env] Stage 1 GREEN: receipt frozen; environment immutable for "
          "the scientific run.", flush=True)


if __name__ == "__main__":
    main()
