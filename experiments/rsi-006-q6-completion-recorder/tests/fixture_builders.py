"""Fixture builders for Q6 mechanism tests (NOT scientific).

These mimic the frozen Q3 builder protocol (keyword-only, returning
(exact_bytes, launch_dict)) with deterministic fixture payloads. They
are resolved by dotted name inside the recorder subprocess, so this
module must be importable there (tests put its directory on PYTHONPATH
via env_overrides).
"""

import json


def fixture_completion(*, repo_name, mutant, baseline, argv, python,
                       run_dir, env, env_overrides, junit_path,
                       evidence, **extra):
    """Deterministic fixture completion: canonical bytes + launch."""
    record = {
        "fixture": "completion",
        "repo": repo_name,
        "mutant_id": mutant.get("mutant_id"),
        "exit_status": evidence.get("exit_status"),
        "timeout": bool(evidence.get("timeout")),
        "child_pid": evidence.get("child_pid"),
        "exec_nonce": evidence.get("exec_nonce"),
    }
    outcome_bytes = json.dumps(
        record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    launch = {
        "fixture": "launch",
        "argv": list(argv),
        "child_pid": evidence.get("child_pid"),
        "exit_status": evidence.get("exit_status"),
        "timeout": bool(evidence.get("timeout")),
    }
    return outcome_bytes, launch


def fixture_spawn_failure(*, repo_name, mutant, argv, python, run_dir,
                          env, env_overrides, start_ts, end_ts, error,
                          **extra):
    """Deterministic fixture spawn failure."""
    record = {
        "fixture": "spawn-failure",
        "repo": repo_name,
        "mutant_id": mutant.get("mutant_id"),
        "error": str(error),
    }
    outcome_bytes = json.dumps(
        record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    launch = {
        "fixture": "launch-spawn-failed",
        "argv": list(argv),
        "child_pid": None,
    }
    return outcome_bytes, launch
