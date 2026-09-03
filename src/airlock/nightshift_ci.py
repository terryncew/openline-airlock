from __future__ import annotations

import json
import math
from pathlib import Path
import sys
from typing import Any

from . import ci, ci_doctor, ci_retry, entry
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


def _flag(argv: list[str], name: str) -> tuple[bool, list[str]]:
    seen = False
    out: list[str] = []
    for token in argv:
        if token == name:
            if seen:
                raise ValueError(f"{name} may be supplied only once")
            seen = True
            continue
        out.append(token)
    return seen, out


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


def _doctor_budget(argv: list[str]) -> float:
    raw, _ = _option_value(argv, "--budget")
    if raw is None:
        raise ValueError("--repair-ci requires --budget for one bounded Doctor attempt")
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError("--budget must be a positive finite amount") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError("--budget must be a positive finite amount")
    return value


def _doctor_model(argv: list[str]) -> str:
    """Bind the one Doctor attempt to the one Nightshift worker identity the operator selected."""
    long_agents, _ = _option_value(argv, "--agents")
    short_agents, _ = _option_value(argv, "-n")
    if long_agents is not None and short_agents is not None:
        raise ValueError("--agents/-n may be supplied only once")
    raw_agents = long_agents if long_agents is not None else short_agents
    if raw_agents is None:
        agents = 1
    else:
        try:
            agents = int(raw_agents)
        except ValueError as exc:
            raise ValueError("--agents must be an integer") from exc
    if agents != 1:
        raise ValueError("--repair-ci runs exactly one Doctor attempt; --agents must be 1")

    raw_profiles, _ = _option_value(argv, "--profiles")
    profiles = [row.strip() for row in (raw_profiles or "").split(",") if row.strip()]
    if len(profiles) > 1:
        raise ValueError("--repair-ci accepts at most one Hermes profile")
    return "hermes" if not profiles else f"hermes@{profiles[0]}"


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
            "A retry occurs only with explicit --retry-ci and a sealed RETRY_RECOMMENDED receipt. "
            "A Doctor attempt occurs only with explicit --repair-ci, a positive budget, and a sealed CODE_REPAIR_ALLOWED receipt."
        ),
    }


def _print_doctor_result(route: dict[str, Any], result: dict[str, Any]) -> None:
    print("Airlock nightshift — CI Doctor")
    print(f"Disposition: {route['disposition']}")
    print(f"Doctor decision: {result['decision']}")
    print(f"Doctor worker started: {'YES' if result.get('worker_started') else 'NO'}")
    print("Ordinary Nightshift started: NO")
    if result.get("ready_branch"):
        print(f"Ready for review: {result['ready_branch']}")
    else:
        print("Ready for review: 0")
    print(f"CI receipt: {route['receipt_path']}")
    print(f"Doctor receipt: {result['receipt_path']}")
    print("GitHub write authority: NO")
    print("Merge authority: NO")


def main(argv: list[str] | None = None) -> int:
    raw = list(argv or [])
    try:
        retry_requested, raw = _flag(raw, "--retry-ci")
        repair_requested, raw = _flag(raw, "--repair-ci")
        if retry_requested and repair_requested:
            raise ValueError("--retry-ci and --repair-ci are mutually exclusive")

        ci_run, delegated = _option_value(raw, "--ci")
        if ci_run is None:
            if retry_requested:
                raise ValueError("--retry-ci requires --ci")
            if repair_requested:
                raise ValueError("--repair-ci requires --ci")
            return entry.main(["nightshift", *raw])
        if "--verify" in delegated or any(row.startswith("--verify=") for row in delegated):
            raise ValueError("--ci cannot be combined with --verify")

        doctor_budget = None
        doctor_model = None
        if repair_requested:
            # Validate the spend and one-worker boundary before any provider read.
            doctor_budget = _doctor_budget(delegated)
            doctor_model = _doctor_model(delegated)

        repo = root(Path(_repo_argument(delegated)).resolve())
        recorded = ci.record_run(ci_run, cwd=repo)
        route = consume_receipt(repo, Path(recorded["receipt_path"]))

        if retry_requested:
            if route["disposition"] != "RETRY_RECOMMENDED":
                print("Airlock nightshift — bounded CI retry")
                print(f"Disposition: {route['disposition']}")
                print("Retry submitted: NO")
                print("Hermes started: NO")
                print(f"CI receipt: {route['receipt_path']}")
                print("The sealed receipt did not authorize a bounded retry.")
                return 0
            retried = ci_retry.bounded_retry(repo, recorded)
            print("Airlock nightshift — bounded CI retry")
            print("Disposition: RETRY_RECOMMENDED")
            print("Retry submitted: YES")
            print(f"Retry attempt: {retried['retry_attempt']}")
            print(f"Retry disposition: {retried['retry_disposition']}")
            print("Hermes started: NO")
            print(f"Original receipt: {retried['original_receipt_path']}")
            print(f"Retry receipt: {retried['retry_receipt_path']}")
            print(f"Retry record: {retried['retry_record_path']}")
            print("Retry budget remaining: 0")
            return 0

        if repair_requested:
            if route["disposition"] != "CODE_REPAIR_ALLOWED":
                print("Airlock nightshift — CI Doctor")
                print(f"Disposition: {route['disposition']}")
                print("Doctor submitted: NO")
                print("Doctor worker started: NO")
                print("Ordinary Nightshift started: NO")
                print(f"CI receipt: {route['receipt_path']}")
                print("The sealed receipt did not authorize a code-repair attempt.")
                return 0
            assert doctor_budget is not None and doctor_model is not None
            repaired = ci_doctor.run_doctor(
                repo,
                Path(route["receipt_path"]),
                model=doctor_model,
                budget=doctor_budget,
            )
            _print_doctor_result(route, repaired)
            return 0
    except ci.CIRecorderError as exc:
        print(f"ERROR: {ci._safe_error_text(exc)}", file=sys.stderr)
        return exc.exit_code
    except ci_retry.CIRetryError as exc:
        print(f"ERROR: {ci._safe_error_text(exc)}", file=sys.stderr)
        return exc.exit_code
    except ci_doctor.CIDoctorError as exc:
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
