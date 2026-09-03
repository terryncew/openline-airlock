from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

from . import ci, entry
from .gitops import root
from .util import canonical_json_bytes, sha256_bytes


SCHEMA = "airlock.nightshift.ci-route.v1"


def _option_value(argv: list[str], name: str) -> tuple[str | None, list[str]]:
    """Extract one option while preserving every other frozen Nightshift argument."""
    value: str | None = None
    out: list[str] = []
    index = 0
    prefix = name + "="
    while index < len(argv):
        token = argv[index]
        if token == name:
            if value is not None:
                raise ValueError(f"{name} may be supplied only once")
            if index + 1 >= len(argv):
                raise ValueError(f"{name} requires a value")
            value = argv[index + 1]
            index += 2
            continue
        if token.startswith(prefix):
            if value is not None:
                raise ValueError(f"{name} may be supplied only once")
            value = token[len(prefix):]
            if not value:
                raise ValueError(f"{name} requires a value")
            index += 1
            continue
        out.append(token)
        index += 1
    return value, out


def _repo_argument(argv: list[str]) -> str:
    value = "."
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--repo":
            if index + 1 >= len(argv):
                raise ValueError("--repo requires a value")
            value = argv[index + 1]
            index += 2
            continue
        if token.startswith("--repo="):
            value = token.split("=", 1)[1]
        index += 1
    return value


def consume_receipt(repo: Path, receipt_path: Path) -> dict[str, Any]:
    """Verify a Recorder receipt and reduce it to a no-side-effect Nightshift route."""
    repo = repo.resolve()
    receipt_path = receipt_path.resolve()
    key_path = repo / ".airlock" / "verification.key"
    if not key_path.exists():
        raise ValueError("local Airlock verification key is missing")
    if not receipt_path.exists():
        raise ValueError(f"CI receipt does not exist: {receipt_path}")
    try:
        receipt = json.loads(receipt_path.read_text())
    except Exception as exc:
        raise ValueError("CI receipt is not valid JSON") from exc

    key = key_path.read_bytes()
    verified = ci.verify_ci_receipt(receipt, key)
    if not verified.get("valid"):
        raise ValueError("CI receipt failed Airlock integrity verification")

    payload = receipt.get("payload") or {}
    disposition = payload.get("disposition")
    if disposition not in ci.DISPOSITIONS:
        raise ValueError("CI receipt has an unsupported disposition")
    authorization = payload.get("authorization") or {}
    for forbidden in ("merge", "deployment", "baseline_change", "workflow_repair"):
        if authorization.get(forbidden) is True:
            raise ValueError(f"CI receipt unexpectedly grants {forbidden} authority")

    route_map = {
        "CODE_REPAIR_ALLOWED": ("STOP", "CODE_REPAIR_PROCESS"),
        "RETRY_RECOMMENDED": ("STOP", "BOUNDED_RETRY_PROCESS"),
        "REPORT_ONLY": ("STOP", "REPORT_ONLY"),
        "NO_ACTION": ("PROCEED", "ORDINARY_NIGHTSHIFT"),
    }
    action, next_process = route_map[disposition]
    run = payload.get("run") or {}
    return {
        "schema": SCHEMA,
        "disposition": disposition,
        "nightshift_action": action,
        "next_process": next_process,
        "worker_may_start": action == "PROCEED",
        "receipt_path": str(receipt_path),
        "receipt_sha256": sha256_bytes(canonical_json_bytes(receipt)),
        "canonical_payload_sha256": payload.get("canonical_payload_sha256"),
        "source_bundle_sha256": payload.get("source_bundle_sha256"),
        "run": {
            "repository": run.get("repository"),
            "run_id": run.get("run_id"),
            "run_attempt": run.get("run_attempt"),
            "head_sha": run.get("provider_run_head_sha"),
        },
        "authority": {
            "code_repair": bool(authorization.get("code_repair")),
            "retry": bool(authorization.get("retry")),
            "merge": False,
            "deployment": False,
            "baseline_change": False,
            "workflow_repair": False,
        },
        "boundary": (
            "Recorder classifies; Nightshift consumes the sealed route. "
            "This build performs no CI retry and no CI-directed code repair."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    raw = list(argv or [])
    try:
        ci_run, delegated = _option_value(raw, "--ci")
        if ci_run is None:
            return entry.main(["nightshift", *raw])
        if "--verify" in delegated or any(row.startswith("--verify=") for row in delegated):
            raise ValueError("--ci cannot be combined with --verify")

        repo = root(Path(_repo_argument(delegated)).resolve())
        recorded = ci.record_run(ci_run, cwd=repo)
        route = consume_receipt(repo, Path(recorded["receipt_path"]))
    except ci.CIRecorderError as exc:
        print(f"ERROR: {ci._safe_error_text(exc)}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        print(f"ERROR: {ci._safe_error_text(exc)}", file=sys.stderr)
        return 3

    if route["nightshift_action"] == "PROCEED":
        return entry.main(["nightshift", *delegated])

    print("Airlock nightshift — CI route")
    print(f"Disposition: {route['disposition']}")
    print(f"Next process: {route['next_process']}")
    print("Hermes started: NO")
    print(f"CI receipt: {route['receipt_path']}")
    print("No retry was started. No CI-directed code repair was started.")
    return 0
