#!/usr/bin/env python3
"""RSI-005: lineage-aware inheritance — HARNESS QUALIFICATION STAGE ONLY.

This runner contains NO scientific primary. Its only job is to prove that
the repaired successor harness can create its complete runtime state,
establish the internal phase-token path, cross a real fresh-process
dispatch boundary, and arrive at the named PRE_NIGHTSHIFT_BOUNDARY —
without executing a candidate, contacting Nightshift, writing REOPEN
evidence, or beginning the scientific primary.

Why RSI-005 exists
------------------
RSI-004's single authorized primary attempt crashed before any phase
dispatch. The frozen root cause (proofs/rsi-004/) is:

    build_fixture() recorded state_dir=<tmp>/state but never created that
    directory. orchestrate() then tried to write <tmp>/state/.phase_token
    and crashed with FileNotFoundError before any phase dispatch or
    Nightshift contact.

The earned repair in this successor harness: build_fixture() creates
state_dir before returning the state object, and the phase-token write
fails closed (raises) if the directory is ever absent again.

The question for THIS stage is not the lineage question. It is:

    Can the repaired successor harness create its complete runtime state,
    establish the internal phase-token path, cross a real fresh-process
    dispatch boundary, and arrive at the exact pre-Nightshift boundary
    without executing a candidate, contacting Nightshift, writing REOPEN
    evidence, or beginning the scientific primary?

Qualification terminology
-------------------------
This stage uses qualification_status, never scientific verdict terminology:

    QUALIFIED_RSI_005_PRE_NIGHTSHIFT_HARNESS
    NOT_QUALIFIED_RSI_005_PRE_NIGHTSHIFT_HARNESS

Execution gates
---------------
* Default invocation (no flags): runs the ordinary self-check only.
* --qualify-harness: runs the harness qualification described above. Safe
  for local execution and CI: it never calls run_nightshift, never executes
  a candidate shim, never writes the primary-contact marker, and never
  produces a scientific result.
* --internal-probe: internal-only child entry point, token-gated exactly
  like future phase dispatch. Refuses to run without the orchestrator's
  unpredictable phase token.

There is deliberately no scientific-primary execution flag in this stage. The
scientific RSI-005 preregistration is not frozen here and no lineage
experiment is claimed, authorized, or executed.

Predecessor bindings (frozen, from the RSI-004 freeze on main f2f2ece):
* RSI-004 reviewed runner SHA-256:
  1195b9f0d54a6bdc93b982ac56778e9ee69f21f51a73333eb3c718a0ec951de2
* RSI-004 frozen preregistration SHA-256:
  8e9ceb9bc928c710920893a79fa99661f93d2456bc3acf1586a8175eb51ca8fd
* Verified Memory: 36e3d0e0dab6a121abc1c14accbaa7310b5c2186
* Verified Memory evidence.py SHA-256:
  ba02bc78c999120b31ea68fcb4f4fd2d12967c705e380204d0ee093b1d874ec9

RSI-004, RSI-003, and Verified Memory are sealed: this file must not modify
them, and its self-check verifies their frozen bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from airlock.nightshift import run_nightshift

try:
    import openline_verified_memory as _ovm_pkg
    from openline_verified_memory import derive_airlock_memory_with_lineage  # noqa: F401
except ImportError as exc:  # fail closed: the repaired projector is part of the lineage question
    raise SystemExit(
        "RSI-005 requires openline-verified-memory pinned to "
        "36e3d0e0dab6a121abc1c14accbaa7310b5c2186 "
        "(derive_airlock_memory_with_lineage)"
    ) from exc


AIRLOCK_BASE_MAIN = "f2f2ecebf8672054154df6c99fb7c0a593334841"
PREDECESSOR_RUNNER_SHA256 = (
    "1195b9f0d54a6bdc93b982ac56778e9ee69f21f51a73333eb3c718a0ec951de2"
)
PREDECESSOR_PREREG_SHA256 = (
    "8e9ceb9bc928c710920893a79fa99661f93d2456bc3acf1586a8175eb51ca8fd"
)
VERIFIED_MEMORY_COMMIT = "36e3d0e0dab6a121abc1c14accbaa7310b5c2186"
EVIDENCE_PY_SHA256 = "ba02bc78c999120b31ea68fcb4f4fd2d12967c705e380204d0ee093b1d874ec9"

QUALIFIED = "QUALIFIED_RSI_005_PRE_NIGHTSHIFT_HARNESS"
NOT_QUALIFIED = "NOT_QUALIFIED_RSI_005_PRE_NIGHTSHIFT_HARNESS"
PRE_NIGHTSHIFT_BOUNDARY = "PRE_NIGHTSHIFT_BOUNDARY"

PRIMARY_CONTACT_MARKER = Path(__file__).with_name(".rsi-005-primary-contact")
PHASE_TOKEN_ENV = "AIRLOCK_RSI_005_PHASE_TOKEN"
PARENT_PID_ENV = "AIRLOCK_RSI_005_PARENT_PID"

# Contact accounting. The ONLY writer of the primary-contact marker and the
# ONLY caller of run_nightshift is nightshift_entry() below. The
# harness-qualification stage never calls it, so both counters stay zero in
# every qualification run and the evidence binds that fact.
_CONTACTS = {"nightshift": 0, "candidate_executions": 0}

RU_BRANCH = "rsi-005/installed-rootU"
R1_BRANCH = "rsi-005/installed-gen1"
R2_BRANCH = "rsi-005/installed-gen2"
R3_BRANCH = "rsi-005/installed-gen3"
INSTALLED_BRANCHES = (RU_BRANCH, R1_BRANCH, R2_BRANCH, R3_BRANCH)

POLICY_V1 = (
    '"""Generator policy: ordinary code. The installed policy is the generator."""\n'
    "STEP = 1\n"
    "\n"
    "\n"
    "def propose(value: int) -> int:\n"
    "    return value + STEP\n"
)

# Inert provider placeholder for the harness-qualification fixture. It is
# created on disk so later phases have a provider path to resolve, but it
# refuses to execute: this stage must never execute a candidate.
HERMES_PLACEHOLDER = """#!/usr/bin/env python3
import sys
raise SystemExit(
    "rsi-005 harness-qualification fixture: the provider placeholder "
    "must never be executed in this stage"
)
"""


class QualificationFailure(RuntimeError):
    """A harness-qualification check failed; the stage must fail closed."""


class ProbeRefused(RuntimeError):
    """The internal child probe refused to cross the dispatch boundary."""


def sh(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    cp = subprocess.run(
        list(args),
        cwd=None if cwd is None else str(cwd),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and cp.returncode != 0:
        raise RuntimeError(
            f"command failed ({cp.returncode}): {' '.join(args)}\n{cp.stderr.strip()}"
        )
    return cp.stdout.strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def self_check() -> list[str]:
    """Ordinary self-check: pins, predecessor bytes, base ancestry. No execution."""
    problems: list[str] = []

    try:
        import openline_verified_memory as ovm

        if not hasattr(ovm, "derive_airlock_memory_with_lineage"):
            problems.append("verified memory lacks derive_airlock_memory_with_lineage")
        evidence = Path(ovm.__file__).with_name("evidence.py")
        if not evidence.is_file() or sha256_file(evidence) != EVIDENCE_PY_SHA256:
            problems.append("verified memory evidence.py bytes do not match the pin")
    except ImportError:
        problems.append("openline_verified_memory is not importable")

    rsi004_dir = Path(__file__).resolve().parent.parent / "rsi-004-lineage-aware-inheritance"
    runner = rsi004_dir / "run_rsi_004.py"
    prereg = rsi004_dir / "RSI_004_PREREGISTRATION.json"
    if not runner.is_file() or sha256_file(runner) != PREDECESSOR_RUNNER_SHA256:
        problems.append("RSI-004 predecessor runner bytes do not match the frozen binding")
    if not prereg.is_file() or sha256_file(prereg) != PREDECESSOR_PREREG_SHA256:
        problems.append("RSI-004 frozen preregistration bytes do not match the frozen binding")

    try:
        sh("git", "merge-base", "--is-ancestor", AIRLOCK_BASE_MAIN, "HEAD", cwd=_repo_root())
    except RuntimeError:
        problems.append(f"airlock base {AIRLOCK_BASE_MAIN} is not an ancestor of HEAD")

    return problems


def nightshift_entry(*args: Any, **kwargs: Any) -> Any:
    """Centralized primary Nightshift-entry choke point.

    The ONLY place the primary-contact marker may be written, immediately
    before the first Nightshift path, and the ONLY caller of run_nightshift
    in this module. All future scientific Nightshift paths must go through
    this function. The harness-qualification stage never calls it.
    """
    _CONTACTS["nightshift"] += 1
    PRIMARY_CONTACT_MARKER.write_text(
        "RSI-005 primary Nightshift contact began\n", encoding="utf-8"
    )
    return run_nightshift(*args, **kwargs)


def require_primary_contact_marker() -> None:
    """Defense in depth for future scientific phases: Nightshift entry is
    unreachable without the primary-contact marker."""
    if not PRIMARY_CONTACT_MARKER.exists():
        raise QualificationFailure(
            "Nightshift is unreachable without the primary-contact marker"
        )


def build_fixture(root: Path) -> dict[str, str]:
    """Build the real temporary fixture.

    THE EARNED REPAIR (RSI-004 root cause): state_dir is created before the
    state object is returned, so the phase-token write and every later phase
    always have a directory to write into.
    """
    repo = root / "repo"
    repo.mkdir(parents=True)
    sh("git", "init", "-q", str(repo))
    sh("git", "-C", str(repo), "config", "user.name", "RSI-005")
    sh("git", "-C", str(repo), "config", "user.email", "rsi-005@example.invalid")

    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / ".airlock" / "objectives").mkdir(parents=True)
    (repo / "src" / "value.py").write_text("VALUE = 0\n", encoding="utf-8")
    (repo / "src" / "policy.py").write_text(POLICY_V1, encoding="utf-8")
    (repo / "tests" / "check.py").write_text(
        "from src.value import VALUE\n"
        "raise SystemExit(0 if isinstance(VALUE, int) and VALUE >= 0 else 1)\n",
        encoding="utf-8",
    )
    (repo / ".airlock" / "objectives" / "measure.py").write_text(
        "import json\n"
        "from src.value import VALUE\n"
        "print(json.dumps({'value': VALUE}))\n",
        encoding="utf-8",
    )
    objective = {
        "schema": "airlock.objective.v1",
        "name": "RSI-005 fixture value",
        "goal": "Increase fixture value without changing the evaluator.",
        "measure": {
            "command": [sys.executable, ".airlock/objectives/measure.py"],
            "direction": "maximize",
            "unit": "points",
            "repeats": 1,
            "timeout_seconds": 30,
            "pass_env": [],
            "protected_evaluator_paths": [".airlock/objectives/measure.py"],
        },
        "bounds": {"max_generations": 1, "max_changed_files": 2, "max_changed_lines": 10},
        "selection": {
            "minimum_gain": "1",
            "complexity_penalty_per_changed_line": "0",
            "minimum_score_gap": "0",
        },
    }
    write_json(repo / ".airlock" / "objective.json", objective)
    config = {
        "schema": "airlock.config.v1",
        "parallelism": 1,
        "protected_paths": ["tests/**", ".github/**", ".airlock/**", "pyproject.toml"],
        "verification": {
            "static_commands": [[sys.executable, "-m", "py_compile", "src/value.py"]],
            "test_commands": [[sys.executable, "tests/check.py"]],
            "target_commands": [[sys.executable, "tests/check.py"]],
            "timeout_seconds": 30,
            "coverage_mode": "changed-module-reference",
        },
        "providers": {
            "hermes": {
                "command": ["hermes", "-z", "{prompt}"],
                "pass_env": ["HERMES_HOME", "OPENROUTER_API_KEY"],
                "timeout_seconds": 30,
            }
        },
        "init_baseline": {"green": True},
    }
    write_json(repo / ".airlock" / "config.json", config)
    (repo / ".gitignore").write_text(
        ".airlock/runs/\n"
        ".airlock/records/\n"
        ".airlock/improvements/\n"
        ".airlock/verification.key\n"
        ".airlock/index.json\n",
        encoding="utf-8",
    )
    sh("git", "add", ".", cwd=repo)
    sh("git", "commit", "-qm", "rsi-005 base", cwd=repo)
    base = sh("git", "rev-parse", "HEAD", cwd=repo)
    for branch in INSTALLED_BRANCHES:
        sh("git", "branch", branch, base, cwd=repo)

    bin_dir = root / "bin"
    bin_dir.mkdir()
    hermes = bin_dir / "hermes"
    hermes.write_text(HERMES_PLACEHOLDER, encoding="utf-8")
    hermes.chmod(hermes.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    hermes_home = root / "hermes-home"
    hermes_home.mkdir()

    # THE REPAIR: create state_dir before returning the state object. The
    # RSI-004 harness recorded this path without creating it and crashed on
    # the first write into it.
    state_dir = root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    state = {
        "repo": str(repo),
        "base_commit": base,
        "hermes_executable": str(hermes),
        "hermes_home": str(hermes_home),
        "state_dir": str(state_dir),
        "installed_branches": ",".join(INSTALLED_BRANCHES),
    }
    write_json(root / "state.json", state)
    return state


def write_phase_token(state_dir: Path) -> str:
    """Mint the unpredictable internal phase token into the runtime state.

    Fails closed with FileNotFoundError if state_dir was not created — the
    exact RSI-004 failure mode can no longer pass silently.
    """
    token = secrets.token_hex(32)
    (state_dir / ".phase_token").write_text(token, encoding="utf-8")
    return token


def _phase_env(state: dict[str, str]) -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = str(Path(state["hermes_executable"]).parent) + os.pathsep + env.get("PATH", "")
    env["HERMES_HOME"] = state["hermes_home"]
    env["OPENROUTER_API_KEY"] = "rsi-fixture-secret"
    return env


def _dir_writable(d: Path) -> bool:
    probe = d / ".writability-probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        return probe.read_text(encoding="utf-8") == "ok"
    except OSError:
        return False
    finally:
        try:
            probe.unlink()
        except OSError:
            pass


def internal_probe(state_path: Path) -> dict[str, Any]:
    """Internal-only child entry point, token-gated exactly like future
    phase dispatch. Reloads the state from disk, verifies the runtime
    evidence later phases need, records its PID, and reports back.

    Refuses to run without the orchestrator's unpredictable phase token.
    Never contacts Nightshift, never executes a candidate, never writes the
    primary-contact marker.
    """
    state = read_json(state_path)
    state_dir = Path(state["state_dir"])
    token_file = state_dir / ".phase_token"
    expected = token_file.read_text(encoding="utf-8").strip() if token_file.exists() else ""
    presented = os.environ.get(PHASE_TOKEN_ENV, "")
    if not expected or not presented or not secrets.compare_digest(presented, expected):
        raise ProbeRefused("internal probe refused: missing or invalid phase token")

    repo = Path(state["repo"])
    base = state["base_commit"]
    checks: dict[str, bool] = {}
    ref_bindings: dict[str, str | None] = {}

    checks["repo_exists"] = repo.is_dir()
    try:
        checks["fixture_base_exists"] = sh("git", "rev-parse", "--verify", base, cwd=repo) == base
    except RuntimeError:
        checks["fixture_base_exists"] = False

    refs_ok = True
    for branch in state.get("installed_branches", "").split(","):
        if not branch:
            continue
        try:
            sha = sh("git", "rev-parse", "--verify", branch, cwd=repo)
        except RuntimeError:
            sha = None
        ref_bindings[branch] = sha
        refs_ok = refs_ok and (sha == base)
    checks["installed_refs_initialized_at_base"] = refs_ok

    hermes = Path(state["hermes_executable"])
    checks["hermes_executable_exists"] = hermes.is_file() and os.access(hermes, os.X_OK)
    checks["state_dir_exists_writable"] = state_dir.is_dir() and _dir_writable(state_dir)
    checks["airlock_config_exists"] = (repo / ".airlock" / "config.json").is_file()
    checks["airlock_objective_exists"] = (repo / ".airlock" / "objective.json").is_file()
    checks["phase_token_round_trip"] = (
        token_file.read_text(encoding="utf-8").strip() == presented
    )

    child_pid = os.getpid()
    try:
        parent_pid = int(os.environ.get(PARENT_PID_ENV, "0"))
    except ValueError:
        parent_pid = 0
    checks["distinct_process"] = parent_pid != 0 and child_pid != parent_pid

    all_ok = all(checks.values())
    result = {
        "child_pid": child_pid,
        "parent_pid": parent_pid,
        "checks": checks,
        "ref_bindings": ref_bindings,
        "all_ok": all_ok,
    }
    write_json(state_dir / "probe_result.json", result)
    return result


def _dispatch_probe(
    script: Path, state_path: Path, env: dict[str, str], parent_pid: int
) -> subprocess.CompletedProcess:
    """Cross the fresh-process dispatch boundary through the same
    token/state authorization mechanism future phases use."""
    child_env = dict(env)
    child_env[PARENT_PID_ENV] = str(parent_pid)
    return subprocess.run(
        [sys.executable, str(script), "--internal-probe", "--state", str(state_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=child_env,
    )


def qualify_harness(output: Path | None) -> dict[str, Any]:
    """Run the harness qualification. NOT a scientific run.

    Exercises the real bootstrap and subprocess machinery: self-check, real
    temporary fixture, state_dir creation, real phase-token write, a fresh
    child process through the token-gated dispatch boundary, and arrival at
    PRE_NIGHTSHIFT_BOUNDARY — then cleans up. Never calls run_nightshift,
    never executes a candidate, never writes the primary-contact marker,
    never produces a scientific result.
    """
    script = Path(__file__).resolve()
    marker_before = PRIMARY_CONTACT_MARKER.exists()
    evidence: dict[str, Any] = {
        "schema": "airlock.rsi-005.qualification.v1",
        "stage": "harness-qualification (NOT a scientific run)",
        "airlock_base_sha": AIRLOCK_BASE_MAIN,
        "rsi004_predecessor_runner_sha256": PREDECESSOR_RUNNER_SHA256,
        "rsi004_frozen_prereg_sha256": PREDECESSOR_PREREG_SHA256,
        "verified_memory_commit": VERIFIED_MEMORY_COMMIT,
        "verified_memory_evidence_py_sha256": EVIDENCE_PY_SHA256,
        "rsi005_runner_sha256": sha256_file(script),
        "parent_pid": os.getpid(),
        "child_pid": None,
        "distinct_process": False,
        "state_dir_created": False,
        "phase_token_round_trip": False,
        "child_state_reload_ok": False,
        "fixture_base_sha": None,
        "installed_ref_bindings": {},
        "marker_exists_before": marker_before,
        "marker_exists_after": None,
        "nightshift_contacts": _CONTACTS["nightshift"],
        "candidate_executions": _CONTACTS["candidate_executions"],
        "phase_scientific_executions": 0,
        "reopen_mutations": 0,
        "boundary_reached": None,
        "qualification_status": NOT_QUALIFIED,
        "reasons": [],
    }

    root = Path(tempfile.mkdtemp(prefix="airlock-rsi-005-qual-"))
    try:
        problems = self_check()
        if problems:
            evidence["reasons"].extend(problems)
            raise QualificationFailure("self-check failed: " + "; ".join(problems))
        if marker_before:
            evidence["reasons"].append("primary-contact marker already exists before qualification")
            raise QualificationFailure("refusing to qualify with a pre-existing contact marker")

        state = build_fixture(root)
        state_dir = Path(state["state_dir"])
        # Regression for the exact RSI-004 failure: the directory must exist
        # before the token write, or we fail closed here.
        if not state_dir.is_dir():
            raise QualificationFailure("state_dir was not created by build_fixture")
        evidence["state_dir_created"] = True

        token = write_phase_token(state_dir)
        if (state_dir / ".phase_token").read_text(encoding="utf-8").strip() != token:
            raise QualificationFailure("phase token did not round-trip on disk")
        evidence["phase_token_round_trip"] = True

        state_path = root / "state.json"
        env = _phase_env(state)
        env[PHASE_TOKEN_ENV] = token
        parent_pid = os.getpid()
        cp = _dispatch_probe(script, state_path, env, parent_pid)
        if cp.returncode != 0:
            raise QualificationFailure(
                f"child probe failed ({cp.returncode}): {cp.stderr.strip().splitlines()[-1] if cp.stderr.strip() else 'no stderr'}"
            )
        probe = read_json(state_dir / "probe_result.json")
        evidence["child_pid"] = probe["child_pid"]
        evidence["distinct_process"] = bool(probe["checks"]["distinct_process"])
        evidence["child_state_reload_ok"] = bool(probe["all_ok"])
        evidence["fixture_base_sha"] = state["base_commit"]
        evidence["installed_ref_bindings"] = probe["ref_bindings"]

        failed_checks = [k for k, v in probe["checks"].items() if not v]
        if failed_checks:
            raise QualificationFailure("child probe checks failed: " + ", ".join(failed_checks))

        # The child returned through the token-gated boundary with every
        # runtime-evidence check green. We stop here: before any candidate
        # execution, before Nightshift, before REOPEN, before any marker.
        evidence["boundary_reached"] = PRE_NIGHTSHIFT_BOUNDARY
        evidence["marker_exists_after"] = PRIMARY_CONTACT_MARKER.exists()
        evidence["nightshift_contacts"] = _CONTACTS["nightshift"]
        evidence["candidate_executions"] = _CONTACTS["candidate_executions"]
        if evidence["marker_exists_after"]:
            raise QualificationFailure("primary-contact marker appeared during qualification")
        if evidence["nightshift_contacts"] != 0 or evidence["candidate_executions"] != 0:
            raise QualificationFailure("forbidden contact occurred during qualification")
        evidence["qualification_status"] = QUALIFIED
    except (QualificationFailure, FileNotFoundError, RuntimeError) as exc:
        if evidence["qualification_status"] != QUALIFIED:
            evidence["qualification_status"] = NOT_QUALIFIED
            if str(exc) not in evidence["reasons"]:
                evidence["reasons"].append(str(exc))
    finally:
        shutil.rmtree(root, ignore_errors=True)
        if evidence["marker_exists_after"] is None:
            evidence["marker_exists_after"] = PRIMARY_CONTACT_MARKER.exists()

    if output is not None:
        write_json(output, evidence)
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="RSI-005 harness qualification only (no scientific primary in this stage)"
    )
    parser.add_argument("--state", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--self-check", action="store_true", help="verify pins and bindings, then stop"
    )
    parser.add_argument(
        "--qualify-harness",
        action="store_true",
        help="run the pre-Nightshift harness qualification (non-scientific)",
    )
    parser.add_argument(
        "--internal-probe",
        action="store_true",
        help="internal-only child probe (token-gated; not for direct use)",
    )
    args = parser.parse_args(argv)

    if args.internal_probe:
        if args.state is None:
            parser.error("--state is required with --internal-probe")
        try:
            result = internal_probe(args.state)
        except ProbeRefused as exc:
            print(f"RSI-005 probe refused: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result, sort_keys=True))
        return 0

    if args.qualify_harness:
        evidence = qualify_harness(args.output)
        print(json.dumps(evidence, sort_keys=True))
        return 0 if evidence["qualification_status"] == QUALIFIED else 1

    problems = self_check()
    if problems:
        print("RSI-005 self-check FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(
        "RSI-005 self-check clean: pins verified, predecessor bindings unambiguous, "
        "base ancestry confirmed. Harness-qualification stage only "
        "(no scientific primary in this runner)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
