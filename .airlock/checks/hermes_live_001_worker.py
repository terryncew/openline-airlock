#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shutil
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


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: hermes_live_001_worker.py PROMPT", file=sys.stderr)
        return 64

    prompt = sys.argv[1]
    report_path = os.environ.get("AIRLOCK_AGENT_REPORT")
    if not report_path:
        print("AIRLOCK_AGENT_REPORT missing", file=sys.stderr)
        return 65

    present = sorted(os.environ)
    forbidden = sorted(
        key for key in present
        if key.upper() in FORBIDDEN_EXACT
        or any(marker in key.upper() for marker in FORBIDDEN_MARKERS)
    )
    hermes_home = os.environ.get("HERMES_HOME")
    audit = {
        "schema": "airlock.hermes-live-001.authority.v1",
        "worker": "hermes",
        "exec_interface": ["hermes", "-z", "<prompt>"],
        "forbidden_environment_names_present": forbidden,
        "release_authority": os.environ.get("AIRLOCK_RELEASE_AUTHORITY"),
        "hermes_home_present": bool(hermes_home),
        "hermes_home_path_sha256": (
            hashlib.sha256(hermes_home.encode()).hexdigest() if hermes_home else None
        ),
        "github_credential_present": any(key in os.environ for key in ("GITHUB_TOKEN", "GH_TOKEN", "SSH_AUTH_SOCK")),
        "environment_names": present,
        "claim_boundary": (
            "This records the environment presented at the exact wrapper-to-Hermes exec boundary. "
            "It does not inspect credentials that Hermes may load from files inside HERMES_HOME."
        ),
    }
    report = {
        "provider": "hermes",
        "authority_audit": audit,
    }
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    if forbidden or os.environ.get("AIRLOCK_RELEASE_AUTHORITY") != "ABSENT":
        print("forbidden authority reached Hermes boundary", file=sys.stderr)
        return 66
    if not hermes_home:
        print("HERMES_HOME must be set for HERMES-LIVE-001", file=sys.stderr)
        return 67
    hermes = shutil.which("hermes")
    if not hermes:
        print("hermes executable unavailable", file=sys.stderr)
        return 127

    child_env = dict(os.environ)
    # The wrapper owns the signed authority report. Hermes does not receive its path.
    child_env.pop("AIRLOCK_AGENT_REPORT", None)
    os.execvpe(hermes, ["hermes", "-z", prompt], child_env)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
