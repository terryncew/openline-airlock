from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

from .gitops import changed_paths, tracked_files
from .util import canonical_json_bytes, matches_any, sha256_bytes, sha256_file


def ensure_key(path: Path) -> bytes:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(secrets.token_bytes(32))
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return path.read_bytes()


def sign(payload: dict, key: bytes) -> dict:
    signature = hmac.new(key, canonical_json_bytes(payload), hashlib.sha256).hexdigest()
    return {"alg": "HMAC-SHA256", "payload": payload, "signature": signature}


def verify_signature(record: dict, key: bytes) -> bool:
    if record.get("alg") != "HMAC-SHA256":
        return False
    payload = record.get("payload")
    signature = record.get("signature")
    if not isinstance(payload, dict) or not isinstance(signature, str):
        return False
    expected = hmac.new(key, canonical_json_bytes(payload), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_offline(repo: Path, verification_path: Path, key_path: Path) -> dict:
    record = json.loads(verification_path.read_text())
    key = key_path.read_bytes()
    checks = []

    checks.append({"check": "signature", "ok": verify_signature(record, key)})
    payload = record.get("payload", {})

    base = payload.get("base_commit")
    candidate = payload.get("candidate_commit")
    recorded_paths = payload.get("changed_paths", [])
    if base and candidate:
        try:
            actual_paths = changed_paths(repo, base, candidate)
            checks.append({"check": "git_diff_boundary", "ok": actual_paths == recorded_paths, "actual": actual_paths})
        except Exception as exc:
            checks.append({"check": "git_diff_boundary", "ok": False, "error": str(exc)})
    else:
        checks.append({"check": "git_diff_boundary", "ok": False, "error": "missing commit ids"})

    protected = payload.get("protected_patterns", [])
    protected_ok = not any(matches_any(path, protected) for path in recorded_paths)
    checks.append({"check": "protected_paths", "ok": protected_ok})

    baseline = payload.get("baseline", {})
    file_rows = baseline.get("protected_fingerprint", {}).get("files", [])
    baseline_ok = True
    for row in file_rows:
        result = __import__("subprocess").run(
            ["git", "show", f"{base}:{row['path']}"], cwd=str(repo), stdout=__import__("subprocess").PIPE, stderr=__import__("subprocess").PIPE
        )
        if result.returncode != 0 or sha256_bytes(result.stdout) != row["sha256"]:
            baseline_ok = False
            break
    checks.append({"check": "baseline_protected_fingerprint", "ok": baseline_ok})

    command_records = payload.get("evidence", {}).get("commands", [])
    command_integrity = all(
        isinstance(row.get("argv"), list)
        and isinstance(row.get("exit_code"), int)
        and isinstance(row.get("stdout_sha256"), str)
        and isinstance(row.get("stderr_sha256"), str)
        for row in command_records
    )
    checks.append({"check": "recorded_command_artifacts", "ok": command_integrity})

    ready = payload.get("decision") == "READY_FOR_REVIEW"
    all_exit_green = all(row.get("exit_code") == 0 and not row.get("timed_out", False) for row in command_records)
    checks.append({"check": "recorded_checks_green", "ok": (not ready) or all_exit_green})

    ok = all(row["ok"] for row in checks)
    return {"valid": ok, "checks": checks, "record_sha256": sha256_file(verification_path)}
