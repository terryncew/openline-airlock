from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from . import ci
from .util import canonical_json_bytes, sha256_bytes
from .verification import sign, verify_signature

SCHEMA = "airlock.ci.bounded-retry.v1"
MAX_RETRIES = 1


class CIRetryError(RuntimeError):
    exit_code = 2


class RetryNotAuthorized(CIRetryError):
    exit_code = 2


class RetryAlreadyConsumed(CIRetryError):
    exit_code = 2


class RetryIncomplete(CIRetryError):
    exit_code = 3


class RetryProviderFailure(CIRetryError):
    exit_code = 4


class GitHubActionsRetryClient:
    """One-purpose GitHub writer for rerunning failed jobs exactly once."""

    def __init__(
        self,
        token: str | None,
        api_base: str = "https://api.github.com",
        opener: Any | None = None,
    ) -> None:
        self.token = token
        self.api_base = api_base.rstrip("/")
        self.opener = opener or urllib.request.urlopen
        self.request_methods: list[str] = []

    def _request(self, path: str, *, method: str) -> bytes:
        if not self.token:
            raise RetryProviderFailure("GitHub token is required for bounded CI retry")
        data = b"" if method == "POST" else None
        req = urllib.request.Request(self.api_base + path, data=data, method=method)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "openline-airlock-ci-retry/0.3")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("Authorization", f"Bearer {self.token}")
        self.request_methods.append(req.get_method())
        try:
            with self.opener(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise RetryProviderFailure(f"GitHub authorization failed ({exc.code})") from exc
            if exc.code >= 500:
                raise RetryProviderFailure(f"GitHub provider failure ({exc.code})") from exc
            raise RetryProviderFailure(f"GitHub rejected bounded retry ({exc.code})") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RetryProviderFailure(f"GitHub network failure: {ci._safe_error_text(exc)}") from exc

    def run_metadata(self, repo: str, run_id: int) -> dict[str, Any]:
        raw = self._request(f"/repos/{repo}/actions/runs/{run_id}", method="GET")
        try:
            value = json.loads(raw)
        except Exception as exc:
            raise RetryIncomplete("GitHub returned malformed workflow-run metadata") from exc
        if not isinstance(value, dict) or int(value.get("id") or 0) != int(run_id):
            raise RetryIncomplete("GitHub retry metadata did not match the requested run")
        return value

    def rerun_failed_jobs(self, repo: str, run_id: int) -> None:
        self._request(f"/repos/{repo}/actions/runs/{run_id}/rerun-failed-jobs", method="POST")


def _guard_path(repo: Path, provider_repo: str, run_id: int, attempt: int) -> Path:
    safe_repo = provider_repo.replace("/", "-")
    return repo / ".airlock" / "ci" / "retries" / f"{safe_repo}-{run_id}-attempt-{attempt}.json"


def _write_signed(path: Path, payload: dict[str, Any], key: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(sign(payload, key)) + b"\n")


def _reserve_once(path: Path, payload: dict[str, Any], key: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = canonical_json_bytes(sign(payload, key)) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise RetryAlreadyConsumed("bounded retry budget for this run attempt is already consumed or reserved") from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
    except Exception:
        # A partial reservation is safer than silently allowing a duplicate retry.
        raise


def verify_retry_record(path: Path, key: bytes) -> dict[str, Any]:
    try:
        record = json.loads(path.read_text())
    except Exception:
        return {"valid": False, "reason": "JSON"}
    payload = record.get("payload") if isinstance(record, dict) else None
    semantic = (
        isinstance(payload, dict)
        and payload.get("schema") == SCHEMA
        and int((payload.get("retry_budget") or {}).get("maximum") or 0) == MAX_RETRIES
        and int((payload.get("retry_budget") or {}).get("consumed") or 0) in {0, 1}
    )
    return {"valid": bool(semantic and verify_signature(record, key)), "signature": verify_signature(record, key), "semantics": semantic}


def bounded_retry(
    repo: Path,
    recorded: dict[str, Any],
    *,
    retry_client: GitHubActionsRetryClient | None = None,
    recorder: Callable[..., dict[str, Any]] = ci.record_run,
    read_client_factory: Callable[[str | None], ci.GitHubActionsReadClient] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    poll_interval_seconds: float = 2.0,
    poll_limit: int = 300,
) -> dict[str, Any]:
    """Consume one RETRY_RECOMMENDED receipt and issue at most one provider rerun.

    The durable reservation is created before the POST. If submission becomes
    ambiguous, the reservation remains and another automatic retry is forbidden.
    """
    repo = repo.resolve()
    receipt = recorded.get("receipt")
    receipt_path = Path(recorded.get("receipt_path") or "").resolve()
    key_path = repo / ".airlock" / "verification.key"
    if not isinstance(receipt, dict) or not receipt_path.exists() or not key_path.exists():
        raise RetryIncomplete("bounded retry requires the sealed local Recorder receipt and verification key")
    key = key_path.read_bytes()
    if not ci.verify_ci_receipt(receipt, key).get("valid"):
        raise RetryIncomplete("Recorder receipt failed integrity verification before retry")

    payload = receipt.get("payload") or {}
    authorization = payload.get("authorization") or {}
    if payload.get("disposition") != "RETRY_RECOMMENDED" or authorization.get("retry") is not True:
        raise RetryNotAuthorized("CI receipt does not authorize bounded retry")
    if authorization.get("code_repair") is True:
        raise RetryNotAuthorized("retry receipt unexpectedly grants code-repair authority")
    for forbidden in ("merge", "deployment", "baseline_change", "workflow_repair"):
        if authorization.get(forbidden) is True:
            raise RetryNotAuthorized(f"retry receipt unexpectedly grants {forbidden} authority")

    run = payload.get("run") or {}
    provider_repo = str(run.get("repository") or "")
    run_id = int(run.get("run_id") or 0)
    original_attempt = int(run.get("run_attempt") or 0)
    if not provider_repo or run_id <= 0 or original_attempt <= 0:
        raise RetryIncomplete("Recorder receipt omitted exact run identity")

    target = recorded.get("target")
    if target is not None:
        if str(getattr(target, "repo", "")) != provider_repo or int(getattr(target, "run_id", 0)) != run_id:
            raise RetryIncomplete("Recorder target and sealed run identity disagree")

    token = ci._token_from_environment(repo)
    if retry_client is None and not token:
        raise RetryProviderFailure("GitHub token is required for bounded CI retry")
    client = retry_client or GitHubActionsRetryClient(token)

    guard = _guard_path(repo, provider_repo, run_id, original_attempt)
    original_receipt_sha = sha256_bytes(canonical_json_bytes(receipt))
    reservation = {
        "schema": SCHEMA,
        "status": "RESERVED",
        "provider": ci.PROVIDER,
        "repository": provider_repo,
        "run_id": run_id,
        "source_attempt": original_attempt,
        "retry_attempt": None,
        "retry_budget": {"maximum": MAX_RETRIES, "consumed": 0, "remaining": 0},
        "original_receipt_path": str(receipt_path),
        "original_receipt_sha256": original_receipt_sha,
        "retry_receipt_path": None,
        "retry_receipt_sha256": None,
        "retry_disposition": None,
        "worker_started": False,
        "authority": {"merge": False, "deployment": False, "baseline_change": False, "workflow_repair": False, "code_repair": False},
    }
    _reserve_once(guard, reservation, key)

    try:
        current = client.run_metadata(provider_repo, run_id)
    except RetryProviderFailure:
        # No provider mutation was attempted, so a deterministic preflight failure
        # must not burn the one retry budget forever.
        guard.unlink(missing_ok=True)
        raise
    current_attempt = int(current.get("run_attempt") or 0)
    if current_attempt != original_attempt or current.get("status") != "completed":
        reservation["status"] = "SOURCE_STALE"
        _write_signed(guard, reservation, key)
        raise RetryNotAuthorized("workflow run advanced after the Recorder receipt; bounded retry was not submitted")

    try:
        client.rerun_failed_jobs(provider_repo, run_id)
    except CIRetryError:
        reservation["status"] = "SUBMISSION_UNKNOWN"
        reservation["retry_budget"]["consumed"] = 1
        _write_signed(guard, reservation, key)
        raise

    reservation["status"] = "SUBMITTED"
    reservation["retry_budget"]["consumed"] = 1
    _write_signed(guard, reservation, key)

    expected_attempt = original_attempt + 1
    completed: dict[str, Any] | None = None
    for _ in range(max(1, poll_limit)):
        metadata = client.run_metadata(provider_repo, run_id)
        observed_attempt = int(metadata.get("run_attempt") or 0)
        if observed_attempt > expected_attempt:
            reservation["status"] = "ATTEMPT_CONFLICT"
            reservation["retry_attempt"] = observed_attempt
            _write_signed(guard, reservation, key)
            raise RetryIncomplete("workflow attempt advanced beyond the one bounded retry")
        if observed_attempt == expected_attempt and metadata.get("status") == "completed":
            completed = metadata
            break
        sleep(poll_interval_seconds)
    if completed is None:
        reservation["status"] = "SUBMITTED_UNSEALED"
        reservation["retry_attempt"] = expected_attempt
        _write_signed(guard, reservation, key)
        raise RetryIncomplete("bounded retry was submitted but the retry attempt did not complete within the polling bound")

    run_url = f"https://github.com/{provider_repo}/actions/runs/{run_id}/attempts/{expected_attempt}"
    if read_client_factory is None:
        read_client = ci.GitHubActionsReadClient(token=token)
    else:
        read_client = read_client_factory(token)
    retry_recorded = recorder(run_url, cwd=repo, client=read_client)
    retry_receipt = retry_recorded.get("receipt")
    retry_path = Path(retry_recorded.get("receipt_path") or "").resolve()
    if not isinstance(retry_receipt, dict) or not retry_path.exists() or not ci.verify_ci_receipt(retry_receipt, key).get("valid"):
        reservation["status"] = "RETRY_RECEIPT_INVALID"
        reservation["retry_attempt"] = expected_attempt
        _write_signed(guard, reservation, key)
        raise RetryIncomplete("retry attempt completed but its Recorder receipt could not be verified")

    retry_payload = retry_receipt.get("payload") or {}
    retry_run = retry_payload.get("run") or {}
    if int(retry_run.get("run_id") or 0) != run_id or int(retry_run.get("run_attempt") or 0) != expected_attempt:
        reservation["status"] = "RETRY_IDENTITY_MISMATCH"
        reservation["retry_attempt"] = expected_attempt
        _write_signed(guard, reservation, key)
        raise RetryIncomplete("retry receipt did not bind the exact rerun attempt")

    reservation.update({
        "status": "SEALED",
        "retry_attempt": expected_attempt,
        "retry_receipt_path": str(retry_path),
        "retry_receipt_sha256": sha256_bytes(canonical_json_bytes(retry_receipt)),
        "retry_disposition": retry_payload.get("disposition"),
    })
    _write_signed(guard, reservation, key)
    if not verify_retry_record(guard, key).get("valid"):
        raise RetryIncomplete("bounded retry record failed local integrity verification")

    return {
        "schema": SCHEMA,
        "status": "SEALED",
        "repository": provider_repo,
        "run_id": run_id,
        "source_attempt": original_attempt,
        "retry_attempt": expected_attempt,
        "retry_disposition": retry_payload.get("disposition"),
        "original_receipt_path": receipt_path,
        "retry_receipt_path": retry_path,
        "retry_record_path": guard,
        "retry_record_sha256": sha256_bytes(canonical_json_bytes(json.loads(guard.read_text()))),
        "retry_budget": {"maximum": MAX_RETRIES, "consumed": 1, "remaining": 0},
        "worker_started": False,
    }
