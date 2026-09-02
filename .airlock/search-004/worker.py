#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

FORBIDDEN_EXACT = {
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "SSH_AUTH_SOCK",
    "AIRLOCK_VERIFICATION_KEY",
    "OPENLINE_RELEASE_KEY",
}
FORBIDDEN_MARKERS = ("RELEASE_KEY", "DEPLOY_KEY", "SIGNING_KEY")


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _safe_int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: worker.py PROMPT", file=sys.stderr)
        return 64

    report_path_raw = os.environ.get("AIRLOCK_AGENT_REPORT")
    usage_path_raw = os.environ.get("SEARCH004_USAGE_FILE")
    hermes_home_raw = os.environ.get("HERMES_HOME")
    if not report_path_raw or not usage_path_raw or not hermes_home_raw:
        print("SEARCH-004 worker boundary missing required path", file=sys.stderr)
        return 65

    report_path = Path(report_path_raw).resolve()
    usage_path = Path(usage_path_raw).resolve()
    hermes_home = Path(hermes_home_raw).resolve()
    cwd = Path.cwd().resolve()
    if _inside(usage_path, cwd) or _inside(usage_path, hermes_home):
        print("usage file must live outside candidate repo and Hermes profile", file=sys.stderr)
        return 66

    present = sorted(os.environ)
    forbidden = sorted(
        key for key in present
        if key.upper() in FORBIDDEN_EXACT
        or any(marker in key.upper() for marker in FORBIDDEN_MARKERS)
    )
    audit = {
        "schema": "airlock.search-004.worker-boundary.v1",
        "worker": "hermes",
        "exec_interface": ["hermes", "-z", "<prompt>", "--usage-file", "<controller-path>"],
        "forbidden_environment_names_present": forbidden,
        "release_authority": os.environ.get("AIRLOCK_RELEASE_AUTHORITY"),
        "hermes_home_present": True,
        "hermes_home_path_sha256": hashlib.sha256(str(hermes_home).encode()).hexdigest(),
        "github_credential_present": any(key in os.environ for key in ("GITHUB_TOKEN", "GH_TOKEN", "SSH_AUTH_SOCK")),
        "usage_path_outside_candidate_repo": not _inside(usage_path, cwd),
        "usage_path_outside_hermes_home": not _inside(usage_path, hermes_home),
    }
    report = {"provider": "hermes", "authority_audit": audit}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    if forbidden or os.environ.get("AIRLOCK_RELEASE_AUTHORITY") != "ABSENT":
        return 67
    hermes = shutil.which("hermes")
    if not hermes:
        return 127

    usage_path.parent.mkdir(parents=True, exist_ok=True)
    usage_path.unlink(missing_ok=True)
    child_env = dict(os.environ)
    child_env.pop("AIRLOCK_AGENT_REPORT", None)
    child_env.pop("SEARCH004_USAGE_FILE", None)
    cp = subprocess.run(
        [hermes, "-z", sys.argv[1], "--usage-file", str(usage_path)],
        env=child_env,
        check=False,
    )

    usage_summary = {"present": usage_path.is_file()}
    if usage_path.is_file():
        raw = usage_path.read_bytes()
        usage_summary["sha256"] = hashlib.sha256(raw).hexdigest()
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {}
            usage_summary["parse_error"] = True
        for key in (
            "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
            "reasoning_tokens", "total_tokens", "api_calls",
        ):
            usage_summary[key] = _safe_int(parsed.get(key))
        for key in ("model", "provider", "service_tier", "completed", "failed"):
            usage_summary[key] = parsed.get(key)

    report["usage_receipt"] = usage_summary
    report["worker_exit_code"] = cp.returncode
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return int(cp.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
