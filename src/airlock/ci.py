from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.resources
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .verification import ensure_key, sign, verify_signature
from .util import canonical_json_bytes, sha256_bytes

SCHEMA_VERSION = "airlock.ci.receipt.v1"
SOURCE_SCHEMA_VERSION = "airlock.ci.source.v1"
PROVIDER = "github-actions"
UNKNOWN = "UNKNOWN"
CAUSES = {"CODE_REGRESSION", "WORKFLOW_CONFIG", "ENVIRONMENT", "EXTERNAL_SERVICE", "UNRESOLVED"}
DISPOSITIONS = {"CODE_REPAIR_ALLOWED", "RETRY_RECOMMENDED", "REPORT_ONLY", "NO_ACTION"}
PATCH_STATES = {"YES", "NO", "UNKNOWN"}
REPRO_STATES = {"REPRODUCED", "NOT_REPRODUCED", "NOT_ATTEMPTED", "UNKNOWN"}
EVIDENCE_GRADES = {"DIRECT", "CORROBORATED", "INSUFFICIENT"}
STABILITIES = {"REPRODUCIBLE", "TRANSIENT", "UNKNOWN"}

RUN_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)/actions/runs/(?P<run>[0-9]+)(?:/attempts/(?P<attempt>[0-9]+))?/?(?:\?.*)?$"
)
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class CIRecorderError(RuntimeError):
    exit_code = 2


class UnsupportedInput(CIRecorderError):
    exit_code = 2


class RetrievalIncomplete(CIRecorderError):
    exit_code = 3


class ProviderFailure(CIRecorderError):
    exit_code = 4


@dataclass(frozen=True)
class RunTarget:
    repo: str
    run_id: int
    attempt: int | None
    local_repo: Path | None


def _resource_bytes(name: str) -> bytes:
    return importlib.resources.files("airlock").joinpath(name).read_bytes()


def load_rule_set() -> tuple[dict[str, Any], str]:
    raw = _resource_bytes("ci_rules.v1.json")
    obj = json.loads(raw)
    if obj.get("rule_set_version") != "airlock.ci.rules.v1":
        raise RuntimeError("unexpected CI rule set version")
    return obj, sha256_bytes(raw)


def _git_repo_root(cwd: Path) -> Path | None:
    cp = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=str(cwd), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if cp.returncode != 0:
        return None
    root = Path(cp.stdout.strip())
    return root if root.is_dir() else None


def _normalize_github_remote(value: str) -> str | None:
    token = value.strip()
    patterns = (
        r"^https://github\.com/(?P<repo>[^/]+/[^/]+?)(?:\.git)?$",
        r"^git@github\.com:(?P<repo>[^/]+/[^/]+?)(?:\.git)?$",
        r"^ssh://git@github\.com/(?P<repo>[^/]+/[^/]+?)(?:\.git)?$",
    )
    for pattern in patterns:
        match = re.match(pattern, token)
        if match:
            return match.group("repo").removesuffix(".git")
    return None


def _local_remote_repo(local_repo: Path | None) -> str | None:
    if local_repo is None:
        return None
    cp = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"], cwd=str(local_repo), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if cp.returncode != 0:
        return None
    return _normalize_github_remote(cp.stdout)


def resolve_target(run: str, repo_arg: str | None, cwd: Path | None = None) -> RunTarget:
    cwd = (cwd or Path.cwd()).resolve()
    local_repo = _git_repo_root(cwd)
    local_identity = _local_remote_repo(local_repo)
    url_match = RUN_URL_RE.match(run.strip())
    if url_match:
        identity = f"{url_match.group('owner')}/{url_match.group('repo')}"
        if repo_arg and repo_arg.casefold() != identity.casefold():
            raise UnsupportedInput(f"run URL repository {identity} conflicts with --repo {repo_arg}")
        if local_identity and local_identity.casefold() != identity.casefold():
            raise UnsupportedInput(f"run URL repository {identity} conflicts with local origin {local_identity}")
        return RunTarget(identity, int(url_match.group("run")), int(url_match.group("attempt")) if url_match.group("attempt") else None, local_repo)

    if not run.isdigit():
        raise UnsupportedInput("RUN must be a GitHub Actions run URL or numeric run ID")
    identity = repo_arg or local_identity
    if not identity or not REPO_RE.match(identity):
        raise UnsupportedInput("numeric run IDs require --repo OWNER/REPO or a GitHub local origin")
    if repo_arg and local_identity and repo_arg.casefold() != local_identity.casefold():
        raise UnsupportedInput(f"--repo {repo_arg} conflicts with local origin {local_identity}")
    return RunTarget(identity, int(run), None, local_repo)


def _safe_error_text(exc: Exception) -> str:
    text = str(exc)
    text = re.sub(r"(?i)(authorization|token|bearer)\s*[:=]?\s*[^\s,;]+", r"\1=[REDACTED]", text)
    return text[:500]


class GitHubActionsReadClient:
    """Minimal GitHub Actions reader. Every provider request is GET-only."""

    def __init__(self, token: str | None = None, api_base: str = "https://api.github.com", opener: Any | None = None):
        self.token = token
        self.api_base = api_base.rstrip("/")
        self.opener = opener or urllib.request.urlopen
        self.request_methods: list[str] = []

    def _request(self, path: str, *, accept: str = "application/vnd.github+json") -> bytes:
        req = urllib.request.Request(self.api_base + path, method="GET")
        req.add_header("Accept", accept)
        req.add_header("User-Agent", "openline-airlock-ci/0.3")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        self.request_methods.append(req.get_method())
        try:
            with self.opener(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise ProviderFailure(f"GitHub authorization failed ({exc.code})") from exc
            if exc.code >= 500:
                raise ProviderFailure(f"GitHub provider failure ({exc.code})") from exc
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderFailure(f"GitHub network failure: {_safe_error_text(exc)}") from exc

    def _json(self, path: str) -> dict[str, Any]:
        try:
            raw = self._request(path)
        except urllib.error.HTTPError as exc:
            raise ProviderFailure(f"GitHub API {exc.code} for requested run evidence") from exc
        try:
            obj = json.loads(raw)
        except Exception as exc:
            raise RetrievalIncomplete("GitHub returned malformed JSON for authoritative evidence") from exc
        if not isinstance(obj, dict):
            raise RetrievalIncomplete("GitHub returned an unexpected evidence shape")
        return obj

    def _optional_json(self, path: str) -> dict[str, Any]:
        try:
            return {"available": True, "value": self._json(path)}
        except ProviderFailure:
            raise
        except urllib.error.HTTPError as exc:
            if exc.code in {404, 410}:
                return {"available": False, "reason": f"GITHUB_{exc.code}"}
            raise ProviderFailure(f"GitHub API {exc.code} while retrieving optional evidence") from exc

    def _optional_bytes(self, path: str, *, accept: str = "application/vnd.github.raw+json") -> dict[str, Any]:
        try:
            raw = self._request(path, accept=accept)
            return {"available": True, "bytes": raw}
        except ProviderFailure:
            raise
        except urllib.error.HTTPError as exc:
            if exc.code in {404, 410}:
                return {"available": False, "reason": f"GITHUB_{exc.code}"}
            raise ProviderFailure(f"GitHub API {exc.code} while retrieving optional evidence") from exc

    def run(self, repo: str, run_id: int) -> dict[str, Any]:
        obj = self._json(f"/repos/{repo}/actions/runs/{run_id}")
        if int(obj.get("id") or 0) != run_id:
            raise RetrievalIncomplete("GitHub run identity did not match the requested run")
        if obj.get("status") != "completed":
            raise UnsupportedInput(f"workflow run {run_id} is not completed")
        return obj

    def attempt(self, repo: str, run_id: int, attempt: int) -> dict[str, Any]:
        return self._json(f"/repos/{repo}/actions/runs/{run_id}/attempts/{attempt}")

    def jobs(self, repo: str, run_id: int, attempt: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page = 1
        while True:
            obj = self._json(f"/repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100&page={page}")
            part = obj.get("jobs")
            if not isinstance(part, list):
                raise RetrievalIncomplete("GitHub jobs response omitted the jobs list")
            rows.extend(row for row in part if isinstance(row, dict))
            if len(part) < 100:
                break
            page += 1
            if page > 100:
                raise RetrievalIncomplete("GitHub job pagination exceeded the Recorder safety bound")
        return rows

    def job_log(self, repo: str, job_id: int) -> dict[str, Any]:
        return self._optional_bytes(f"/repos/{repo}/actions/jobs/{job_id}/logs", accept="text/plain")

    def annotations(self, repo: str, check_run_url: str | None) -> dict[str, Any]:
        if not check_run_url:
            return {"available": False, "reason": "NO_CHECK_RUN_ID"}
        match = re.search(r"/check-runs/([0-9]+)$", check_run_url)
        if not match:
            return {"available": False, "reason": "NO_CHECK_RUN_ID"}
        check_id = int(match.group(1))
        rows: list[dict[str, Any]] = []
        page = 1
        while True:
            try:
                raw = self._request(f"/repos/{repo}/check-runs/{check_id}/annotations?per_page=100&page={page}")
            except urllib.error.HTTPError as exc:
                if exc.code in {404, 410}:
                    return {"available": False, "reason": f"GITHUB_{exc.code}"}
                raise ProviderFailure(f"GitHub API {exc.code} while retrieving annotations") from exc
            try:
                part = json.loads(raw)
            except Exception as exc:
                raise RetrievalIncomplete("GitHub returned malformed annotation evidence") from exc
            if not isinstance(part, list):
                raise RetrievalIncomplete("GitHub annotations response had an unexpected shape")
            rows.extend(row for row in part if isinstance(row, dict))
            if len(part) < 100:
                break
            page += 1
        return {"available": True, "value": rows}

    def workflow_file(self, repo: str, path: str | None, ref: str) -> dict[str, Any]:
        if not path:
            return {"available": False, "reason": "WORKFLOW_PATH_UNKNOWN"}
        clean = path.removeprefix("/")
        quoted = urllib.parse.quote(clean, safe="/")
        try:
            raw = self._request(f"/repos/{repo}/contents/{quoted}?ref={urllib.parse.quote(ref, safe='')}")
        except urllib.error.HTTPError as exc:
            if exc.code in {404, 410}:
                return {"available": False, "reason": f"GITHUB_{exc.code}"}
            raise ProviderFailure(f"GitHub API {exc.code} while retrieving workflow file") from exc
        try:
            obj = json.loads(raw)
            content = base64.b64decode(obj["content"], validate=False)
        except Exception as exc:
            raise RetrievalIncomplete("GitHub workflow-file evidence could not be decoded") from exc
        return {"available": True, "bytes": content}


def _provider_timestamp(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _evidence_object(kind: str, provider_id: str, raw: Any) -> dict[str, Any]:
    if isinstance(raw, bytes):
        digest = sha256_bytes(raw)
    else:
        digest = sha256_bytes(canonical_json_bytes(raw))
    return {"kind": kind, "provider_id": provider_id, "sha256": digest}


def _decode_log(log: dict[str, Any]) -> str | None:
    if not log.get("available"):
        return None
    raw = log.get("bytes")
    if not isinstance(raw, bytes):
        return None
    return raw.decode("utf-8", errors="replace")


def _workflow_dependencies(text: str | None) -> dict[str, set[str]]:
    """Conservative static parser for simple jobs.<id>.needs declarations.

    Dynamic expressions, reusable workflows, and ambiguous YAML are intentionally ignored.
    """
    if not text:
        return {}
    lines = text.splitlines()
    in_jobs = False
    jobs_indent: int | None = None
    current: str | None = None
    current_indent: int | None = None
    edges: dict[str, set[str]] = {}
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if stripped == "jobs:":
            in_jobs = True
            jobs_indent = indent
            current = None
            continue
        if not in_jobs:
            continue
        if jobs_indent is not None and indent <= jobs_indent and stripped != "jobs:":
            break
        if re.match(r"^[A-Za-z0-9_.-]+:$", stripped) and jobs_indent is not None and indent == jobs_indent + 2:
            current = stripped[:-1]
            current_indent = indent
            edges.setdefault(current, set())
            continue
        if current and current_indent is not None and indent > current_indent and stripped.startswith("needs:"):
            value = stripped.split(":", 1)[1].strip()
            if "${{" in value or not value:
                continue
            if value.startswith("[") and value.endswith("]"):
                items = [x.strip().strip("'\"") for x in value[1:-1].split(",") if x.strip()]
            else:
                items = [value.strip("'\"")]
            if all(re.match(r"^[A-Za-z0-9_.-]+$", item) for item in items):
                edges[current].update(items)
    return edges


def build_source_bundle(client: GitHubActionsReadClient, repo: str, run_id: int, requested_attempt: int | None = None) -> dict[str, Any]:
    run = client.run(repo, run_id)
    latest_attempt = int(run.get("run_attempt") or 0)
    if latest_attempt < 1:
        raise RetrievalIncomplete("GitHub run omitted a valid run_attempt")
    attempt = requested_attempt or latest_attempt
    if attempt < 1 or attempt > latest_attempt:
        raise UnsupportedInput(f"run attempt {attempt} does not exist for workflow run {run_id}")
    selected_run = run if attempt == latest_attempt else client.attempt(repo, run_id, attempt)
    if selected_run.get("status") != "completed":
        raise UnsupportedInput(f"workflow run {run_id} attempt {attempt} is not completed")

    head_sha = str(selected_run.get("head_sha") or run.get("head_sha") or "")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", head_sha):
        raise RetrievalIncomplete("GitHub run omitted a full provider head SHA")
    head_sha = head_sha.lower()
    workflow_path = selected_run.get("path") or run.get("path")
    workflow = client.workflow_file(repo, str(workflow_path) if workflow_path else None, head_sha)
    workflow_text = _decode_log(workflow)
    workflow_hash = sha256_bytes(workflow["bytes"]) if workflow.get("available") and isinstance(workflow.get("bytes"), bytes) else UNKNOWN

    jobs = client.jobs(repo, run_id, attempt)
    job_rows: list[dict[str, Any]] = []
    evidence_refs: list[dict[str, Any]] = [_evidence_object("run", f"run:{run_id}:attempt:{attempt}", selected_run)]
    if attempt != latest_attempt:
        evidence_refs.append(_evidence_object("run_latest_metadata", f"run:{run_id}:latest", run))
    if workflow.get("available"):
        evidence_refs.append(_evidence_object("workflow_file", str(workflow_path), workflow["bytes"]))
    else:
        evidence_refs.append(_evidence_object("workflow_file_unavailable", str(workflow_path or UNKNOWN), workflow))

    for job in sorted(jobs, key=lambda row: int(row.get("id") or 0)):
        job_id = int(job.get("id") or 0)
        if job_id <= 0:
            raise RetrievalIncomplete("GitHub job omitted a stable provider ID")
        log = client.job_log(repo, job_id)
        annotations = client.annotations(repo, job.get("check_run_url"))
        steps = []
        for step in sorted((job.get("steps") or []), key=lambda row: int(row.get("number") or 0)):
            if not isinstance(step, dict):
                continue
            steps.append({
                "number": int(step.get("number") or 0),
                "name": str(step.get("name") or UNKNOWN),
                "status": str(step.get("status") or UNKNOWN),
                "conclusion": str(step.get("conclusion") or UNKNOWN),
                "started_at": _provider_timestamp(step.get("started_at")),
                "completed_at": _provider_timestamp(step.get("completed_at")),
            })
        log_text = _decode_log(log)
        row = {
            "id": job_id,
            "name": str(job.get("name") or UNKNOWN),
            "status": str(job.get("status") or UNKNOWN),
            "conclusion": str(job.get("conclusion") or UNKNOWN),
            "runner_labels": sorted(str(x) for x in (job.get("labels") or [])),
            "started_at": _provider_timestamp(job.get("started_at")),
            "completed_at": _provider_timestamp(job.get("completed_at")),
            "steps": steps,
            "matrix": UNKNOWN,
            "log": {"available": bool(log.get("available")), "text": log_text if log_text is not None else None, "unavailable_reason": log.get("reason") if not log.get("available") else None},
            "annotations": {"available": bool(annotations.get("available")), "value": annotations.get("value") if annotations.get("available") else None, "unavailable_reason": annotations.get("reason") if not annotations.get("available") else None},
        }
        job_rows.append(row)
        evidence_refs.append(_evidence_object("job", f"job:{job_id}", job))
        evidence_refs.append(_evidence_object("job_log" if log.get("available") else "job_log_unavailable", f"job:{job_id}:log", log["bytes"] if log.get("available") else log))
        evidence_refs.append(_evidence_object("annotations" if annotations.get("available") else "annotations_unavailable", f"job:{job_id}:annotations", annotations.get("value") if annotations.get("available") else annotations))

    pull_requests = selected_run.get("pull_requests") or run.get("pull_requests") or []
    pr = pull_requests[0] if isinstance(pull_requests, list) and len(pull_requests) == 1 and isinstance(pull_requests[0], dict) else None
    base = (pr or {}).get("base") or {}
    pr_head = (pr or {}).get("head") or {}
    execution = {
        "provider_run_head_sha": head_sha,
        "provider_run_head_ref": str(selected_run.get("head_branch") or run.get("head_branch") or UNKNOWN),
        "triggering_sha": str(pr_head.get("sha") or UNKNOWN),
        "triggering_ref": str(pr_head.get("ref") or UNKNOWN),
        "execution_sha": head_sha,
        "execution_ref": (f"refs/heads/{selected_run.get('head_branch') or run.get('head_branch')}" if str(selected_run.get("event") or run.get("event") or "") == "push" and (selected_run.get("head_branch") or run.get("head_branch")) else UNKNOWN),
    }

    later_attempts: list[dict[str, Any]] = []
    for later in range(attempt + 1, latest_attempt + 1):
        try:
            later_run = client.attempt(repo, run_id, later)
            later_jobs = client.jobs(repo, run_id, later)
        except CIRecorderError:
            raise
        evidence_refs.append(_evidence_object("comparison_run", f"run:{run_id}:attempt:{later}", later_run))
        for comparison_job in later_jobs:
            if isinstance(comparison_job, dict) and int(comparison_job.get("id") or 0) > 0:
                evidence_refs.append(_evidence_object("comparison_job", f"job:{int(comparison_job['id'])}", comparison_job))
        later_attempts.append({
            "attempt": later,
            "status": str(later_run.get("status") or UNKNOWN),
            "conclusion": str(later_run.get("conclusion") or UNKNOWN),
            "head_sha": str(later_run.get("head_sha") or head_sha).lower(),
            "event": str(later_run.get("event") or run.get("event") or UNKNOWN),
            "head_branch": str(later_run.get("head_branch") or run.get("head_branch") or UNKNOWN),
            "workflow_file_sha256": workflow_hash,
            "jobs": [
                {
                    "id": int(j.get("id") or 0),
                    "name": str(j.get("name") or UNKNOWN),
                    "conclusion": str(j.get("conclusion") or UNKNOWN),
                    "runner_labels": sorted(str(x) for x in (j.get("labels") or [])),
                }
                for j in sorted(later_jobs, key=lambda x: int(x.get("id") or 0))
            ],
        })

    bundle = {
        "schema_version": SOURCE_SCHEMA_VERSION,
        "provider": PROVIDER,
        "repository": repo,
        "run_id": run_id,
        "run_attempt": attempt,
        "workflow": {
            "id": selected_run.get("workflow_id") or run.get("workflow_id") or UNKNOWN,
            "name": str(selected_run.get("name") or run.get("name") or UNKNOWN),
            "path": str(workflow_path or UNKNOWN),
            "file_sha256": workflow_hash,
            "file_available": bool(workflow.get("available")),
            "file_unavailable_reason": workflow.get("reason") if not workflow.get("available") else None,
            "static_needs": {key: sorted(value) for key, value in sorted(_workflow_dependencies(workflow_text).items())},
        },
        "event": str(selected_run.get("event") or run.get("event") or UNKNOWN),
        "execution": execution,
        "base_ref": str(base.get("ref") or UNKNOWN),
        "base_sha": str(base.get("sha") or UNKNOWN),
        "status": str(selected_run.get("status") or UNKNOWN),
        "conclusion": str(selected_run.get("conclusion") or UNKNOWN),
        "created_at": _provider_timestamp(selected_run.get("created_at") or run.get("created_at")),
        "run_started_at": _provider_timestamp(selected_run.get("run_started_at") or run.get("run_started_at")),
        "updated_at": _provider_timestamp(selected_run.get("updated_at") or run.get("updated_at")),
        "jobs": job_rows,
        "later_attempts": later_attempts,
        "evidence_objects": sorted(evidence_refs, key=lambda row: (row["kind"], row["provider_id"])),
    }
    return bundle


def _first_blocking_step(job: dict[str, Any]) -> dict[str, Any] | None:
    steps = [row for row in job.get("steps", []) if row.get("conclusion") in {"failure", "timed_out", "cancelled"}]
    main = [row for row in steps if not str(row.get("name", "")).casefold().startswith("post ") and row.get("conclusion") != "cancelled"]
    candidates = main or [row for row in steps if row.get("conclusion") != "cancelled"]
    if not candidates:
        return None
    return sorted(candidates, key=lambda row: int(row.get("number") or 0))[0]


def _code_rule_stage_ok(rule: dict[str, Any], step_name: str) -> bool:
    if rule.get("class") != "CODE_REGRESSION":
        return True
    name = step_name.casefold()
    reason = rule.get("reason")
    if reason == "TEST_FAILURE":
        return any(token in name for token in ("test", "pytest", "unittest", "jest", "vitest", "rspec"))
    if reason == "LINT_OR_TYPE_FAILURE":
        return any(token in name for token in ("lint", "ruff", "mypy", "type", "eslint", "flake8", "pyright"))
    if reason == "COMPILE_OR_BUILD_FAILURE":
        return any(token in name for token in ("build", "compile", "cargo", "gradle", "maven", "make"))
    return False


def _match_rule(text: str, rule_set: dict[str, Any], *, step_name: str = "") -> tuple[dict[str, Any] | None, list[str]]:
    matches: list[tuple[dict[str, Any], str]] = []
    for rule in rule_set.get("rules", []):
        if not _code_rule_stage_ok(rule, step_name):
            continue
        for pattern in rule.get("patterns", []):
            if re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL):
                matches.append((rule, pattern))
                break
    classes = sorted({row[0]["class"] for row in matches})
    if len(classes) != 1:
        return None, classes
    # Rule file order is authoritative within one class.
    return matches[0][0], classes


def _direct_non_code_exoneration(rule: dict[str, Any] | None, text: str) -> bool:
    """Earn patch_implicated:NO only from direct evidence outside candidate execution.

    A non-code cause class alone is insufficient.  In particular, a generic
    "no space left" emitted while candidate code is running does not exonerate
    the patch.  PR #60's Git-object copy signature is direct because the failed
    operation is repository/runner plumbing rather than candidate-code execution.
    """
    if not rule or rule.get("class") != "ENVIRONMENT":
        return False
    reason = rule.get("reason")
    if reason == "RUNNER_CAPACITY":
        return bool(re.search(r"(?:hosted runner|runner (?:was abandoned|has received a shutdown signal)|lost communication with the server)", text, re.IGNORECASE))
    if reason == "DISK_OR_RESOURCE_EXHAUSTION":
        return bool(
            re.search(r"(?:/home/runner|RUNNER_TEMP|hosted runner|runner image)", text, re.IGNORECASE)
            and re.search(r"(?:disk quota exceeded|no space left on device|cannot allocate memory|out of memory|oom killed)", text, re.IGNORECASE)
        )
    if reason == "RUNNER_FILESYSTEM":
        return bool(
            re.search(r"(?:\.git/objects|git object copy failed|failed to copy[^\n]*\.git/objects|unable to (?:copy|create)[^\n]*\.git/objects)", text, re.IGNORECASE)
            or (
                re.search(r"(?:/home/runner|RUNNER_TEMP|hosted runner|runner image)", text, re.IGNORECASE)
                and re.search(r"(?:no space left on device|input/output error)", text, re.IGNORECASE)
            )
        )
    return False


def _equivalent_pass(bundle: dict[str, Any], job: dict[str, Any]) -> bool:
    for later in bundle.get("later_attempts", []):
        if later.get("status") != "completed":
            continue
        if later.get("head_sha") != bundle["execution"]["provider_run_head_sha"]:
            continue
        if later.get("event") != bundle.get("event") or later.get("head_branch") != bundle["execution"]["provider_run_head_ref"]:
            continue
        if later.get("workflow_file_sha256") != bundle["workflow"]["file_sha256"]:
            continue
        for other in later.get("jobs", []):
            if other.get("name") == job.get("name") and other.get("runner_labels") == job.get("runner_labels") and other.get("conclusion") == "success":
                return True
    return False


def _job_key_candidates(name: str) -> set[str]:
    # Only exact simple job IDs are safe to bind to static `needs` edges.
    return {name} if re.fullmatch(r"[A-Za-z0-9_.-]+", name) else set()


def _role_map(bundle: dict[str, Any], blocking_jobs: dict[int, dict[str, Any]]) -> dict[int, str]:
    needs = bundle.get("workflow", {}).get("static_needs", {})
    by_key: dict[str, int] = {}
    for job_id, job in blocking_jobs.items():
        for key in _job_key_candidates(str(job.get("name") or "")):
            by_key[key] = job_id
    roles = {job_id: "PRIMARY" for job_id in blocking_jobs}
    for job_id, job in blocking_jobs.items():
        keys = _job_key_candidates(str(job.get("name") or ""))
        if len(keys) != 1:
            continue
        key = next(iter(keys))
        predecessors = needs.get(key, [])
        for pred in predecessors:
            pred_id = by_key.get(pred)
            if pred_id is None:
                continue
            upstream = blocking_jobs[pred_id]
            upstream_done = upstream.get("completed_at")
            downstream_start = job.get("started_at")
            if upstream_done and downstream_start and upstream_done <= downstream_start:
                roles[job_id] = "DOWNSTREAM"
                break
    return roles


def analyze_bundle(bundle: dict[str, Any], *, key: bytes) -> dict[str, Any]:
    rule_set, rule_sha = load_rule_set()
    if bundle.get("schema_version") != SOURCE_SCHEMA_VERSION or bundle.get("provider") != PROVIDER:
        raise ValueError("unsupported CI source bundle")

    source_sha = sha256_bytes(canonical_json_bytes(bundle))
    jobs = sorted(bundle.get("jobs", []), key=lambda row: int(row.get("id") or 0))
    blocking_jobs: dict[int, dict[str, Any]] = {}
    for job in jobs:
        if job.get("conclusion") in {"failure", "timed_out", "cancelled"}:
            blocking_jobs[int(job["id"])] = job
    roles = _role_map(bundle, blocking_jobs)

    findings: list[dict[str, Any]] = []
    evidence_refs: list[dict[str, Any]] = []
    for job_id, job in sorted(blocking_jobs.items()):
        step = _first_blocking_step(job)
        log_text = ((job.get("log") or {}).get("text") or "")
        annotation_text = "\n".join(
            str((row or {}).get("message") or "")
            for row in ((job.get("annotations") or {}).get("value") or [])
            if isinstance(row, dict)
        )
        signal_text = log_text + ("\n" + annotation_text if annotation_text else "")
        rule, classes = _match_rule(signal_text, rule_set, step_name=str((step or {}).get("name") or ""))
        evidence_available = bool((job.get("log") or {}).get("available")) or bool((job.get("annotations") or {}).get("available"))
        if job.get("conclusion") == "cancelled" or step is None or not evidence_available or rule is None:
            cause = "UNRESOLVED"
            reason = "INSUFFICIENT_EVIDENCE"
            rule_id = "CI-UNRESOLVED-001"
            grade = "INSUFFICIENT"
            patch = "UNKNOWN"
            summary = "available evidence does not deterministically identify one cause"
            if len(classes) > 1:
                summary = "evidence matches more than one causal class"
        else:
            cause = str(rule["class"])
            reason = str(rule["reason"])
            rule_id = str(rule["id"])
            grade = "DIRECT"
            patch = "NO" if _direct_non_code_exoneration(rule, signal_text) else "UNKNOWN"
            summaries = {
                "TEST_FAILURE": "a concrete test failure was recorded after execution reached the failing step",
                "LINT_OR_TYPE_FAILURE": "a concrete lint or type-check failure was recorded",
                "COMPILE_OR_BUILD_FAILURE": "a concrete compile or build failure was recorded",
                "WORKFLOW_SYNTAX": "GitHub recorded an invalid workflow definition",
                "EXPRESSION_OR_ACTION_CONFIG": "workflow/action configuration failed before ordinary code remediation is authorized",
                "PERMISSION_OR_SECRET_CONFIG": "workflow permission or secret configuration blocked execution",
                "RUNNER_FILESYSTEM": "runner filesystem evidence blocked the execution path",
                "RUNNER_CAPACITY": "runner availability/capacity evidence blocked the execution path",
                "DISK_OR_RESOURCE_EXHAUSTION": "runner resource exhaustion blocked the execution path",
                "RATE_LIMIT": "an upstream service returned rate-limit evidence",
                "REMOTE_5XX": "an upstream service returned a server-side failure",
                "DNS_TLS_OR_NETWORK": "network, DNS, or TLS evidence blocked the execution path",
            }
            summary = summaries.get(reason, "a deterministic Recorder rule matched the blocking evidence")

        transient = _equivalent_pass(bundle, job)
        stability = "TRANSIENT" if transient else "UNKNOWN"
        if transient and grade == "DIRECT":
            grade = "CORROBORATED"
        finding_ref = f"job:{job_id}:step:{(step or {}).get('number', UNKNOWN)}"
        evidence_refs.append({
            "ref": finding_ref,
            "job_id": job_id,
            "step_number": (step or {}).get("number", UNKNOWN),
            "rule_id": rule_id,
            "evidence_object_sha256": next((x["sha256"] for x in bundle.get("evidence_objects", []) if x.get("provider_id") == f"job:{job_id}:log"), UNKNOWN),
        })
        findings.append({
            "job_id": job_id,
            "job": str(job.get("name") or UNKNOWN),
            "matrix": job.get("matrix", UNKNOWN),
            "role": roles.get(job_id, "PRIMARY"),
            "step_number": (step or {}).get("number", UNKNOWN),
            "step": (step or {}).get("name", UNKNOWN),
            "cause_class": cause,
            "reason_code": reason,
            "rule_id": rule_id,
            "patch_implicated": patch,
            "local_reproduction": "NOT_ATTEMPTED",
            "evidence_grade": grade,
            "stability": stability,
            "evidence_summary": summary,
            "evidence_ref": finding_ref,
        })

    if not findings and bundle.get("conclusion") in {"failure", "timed_out", "cancelled"}:
        evidence_refs.append({
            "ref": f"run:{bundle['run_id']}:attempt:{bundle['run_attempt']}",
            "job_id": 0,
            "step_number": UNKNOWN,
            "rule_id": "CI-UNRESOLVED-001",
            "evidence_object_sha256": next((x["sha256"] for x in bundle.get("evidence_objects", []) if x.get("kind") == "run"), UNKNOWN),
        })
        findings.append({
            "job_id": 0, "job": UNKNOWN, "matrix": UNKNOWN, "role": "PRIMARY",
            "step_number": UNKNOWN, "step": UNKNOWN, "cause_class": "UNRESOLVED",
            "reason_code": "INSUFFICIENT_EVIDENCE", "rule_id": "CI-UNRESOLVED-001",
            "patch_implicated": UNKNOWN, "local_reproduction": "NOT_ATTEMPTED",
            "evidence_grade": "INSUFFICIENT", "stability": UNKNOWN,
            "evidence_summary": "the run failed without an authoritative blocking job finding",
            "evidence_ref": f"run:{bundle['run_id']}:attempt:{bundle['run_attempt']}",
        })

    primary = [row for row in findings if row["role"] == "PRIMARY"]
    primary_classes = {row["cause_class"] for row in primary}
    incomplete = any(row["evidence_grade"] == "INSUFFICIENT" for row in primary)
    if not primary:
        disposition = "NO_ACTION"
    elif incomplete or "UNRESOLVED" in primary_classes or len(primary_classes) > 1:
        disposition = "REPORT_ONLY"
    elif primary_classes == {"CODE_REGRESSION"}:
        disposition = "CODE_REPAIR_ALLOWED"
    elif primary_classes.issubset({"ENVIRONMENT", "EXTERNAL_SERVICE"}) and all(row["stability"] == "TRANSIENT" for row in primary):
        disposition = "RETRY_RECOMMENDED"
    else:
        disposition = "REPORT_ONLY"

    authorization = {
        "result": disposition,
        "code_repair": disposition == "CODE_REPAIR_ALLOWED",
        "retry": disposition == "RETRY_RECOMMENDED",
        "merge": False,
        "deployment": False,
        "baseline_change": False,
        "workflow_repair": False,
        "scope": "possible next process only; ordinary Airlock file, budget, isolation, and evaluation boundaries still apply",
    }
    run_row = {
        "repository": bundle["repository"],
        "run_id": int(bundle["run_id"]),
        "run_attempt": int(bundle["run_attempt"]),
        "workflow_id": bundle["workflow"]["id"],
        "workflow_name": bundle["workflow"]["name"],
        "workflow_path": bundle["workflow"]["path"],
        "workflow_file_sha256": bundle["workflow"]["file_sha256"],
        "event": bundle["event"],
        "provider_run_head_sha": bundle["execution"]["provider_run_head_sha"],
        "provider_run_head_ref": bundle["execution"]["provider_run_head_ref"],
        "triggering_sha": bundle["execution"].get("triggering_sha", UNKNOWN),
        "triggering_ref": bundle["execution"].get("triggering_ref", UNKNOWN),
        "execution_sha": bundle["execution"].get("execution_sha", UNKNOWN),
        "execution_ref": bundle["execution"].get("execution_ref", UNKNOWN),
        "base_ref": bundle.get("base_ref", UNKNOWN),
        "base_sha": bundle.get("base_sha", UNKNOWN),
        "status": bundle["status"],
        "conclusion": bundle["conclusion"],
    }
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "provider": PROVIDER,
        "source_bundle_sha256": source_sha,
        "rule_set_version": rule_set["rule_set_version"],
        "rule_set_sha256": rule_sha,
        "run": run_row,
        "findings": findings,
        "disposition": disposition,
        "authorization": authorization,
        "evidence_references": sorted(evidence_refs, key=lambda row: (row["job_id"], str(row["step_number"]))),
    }
    payload["canonical_payload_sha256"] = sha256_bytes(canonical_json_bytes(payload))
    return sign(payload, key)


def verify_ci_receipt(receipt: dict[str, Any], key: bytes) -> dict[str, Any]:
    signature_ok = verify_signature(receipt, key)
    payload = receipt.get("payload") if isinstance(receipt, dict) else None
    hash_ok = False
    semantic_ok = False
    if isinstance(payload, dict):
        claimed = payload.get("canonical_payload_sha256")
        core = dict(payload)
        core.pop("canonical_payload_sha256", None)
        hash_ok = isinstance(claimed, str) and claimed == sha256_bytes(canonical_json_bytes(core))
        semantic_ok = (
            payload.get("schema_version") == SCHEMA_VERSION
            and payload.get("provider") == PROVIDER
            and payload.get("disposition") in DISPOSITIONS
            and all(row.get("cause_class") in CAUSES for row in payload.get("findings", []))
        )
    return {"valid": signature_ok and hash_ok and semantic_ok, "signature": signature_ok, "payload_hash": hash_ok, "semantics": semantic_ok}


def render_text(receipt: dict[str, Any]) -> str:
    payload = receipt["payload"]
    run = payload["run"]
    lines = [
        "CI FAILURE RECEIPT",
        "Execution",
        f"  repository: {run['repository']}",
        f"  run: {run['run_id']} / attempt {run['run_attempt']}",
        f"  provider head: {run['provider_run_head_sha']}",
        f"  execution ref: {run['execution_ref']}",
        f"  workflow: {run['workflow_name']}",
        f"  event: {run['event']}",
    ]
    findings = payload["findings"]
    if findings:
        for index, finding in enumerate(findings, 1):
            lines.extend([
                "",
                "Blocking finding" + (f" {index}" if len(findings) > 1 else ""),
                f"  job: {finding['job']}",
                f"  step: {finding['step']}",
                f"  role: {finding['role']}",
                f"  class: {finding['cause_class']}",
                f"  reason: {finding['reason_code']}",
                f"  rule: {finding['rule_id']}",
                f"  stability: {finding['stability']}",
                f"  evidence: {finding['evidence_summary']}",
                f"  patch implicated: {finding['patch_implicated']}",
                f"  local reproduction: {finding['local_reproduction']}",
            ])
    else:
        lines.extend(["", "Blocking finding", "  none"])
    lines.extend([
        "",
        f"Code repair authority: {'YES' if payload['authorization']['code_repair'] else 'NO'}",
        f"Disposition: {payload['disposition']}",
        "Merge authority: NO",
        "Deployment authority: NO",
        "",
        f"Receipt: sha256:{sha256_bytes(canonical_json_bytes(receipt))}",
    ])
    return "\n".join(lines)


def _token_from_environment(local_repo: Path | None) -> str | None:
    # Config may name a token environment variable; the secret itself never belongs in config.
    token_env: str | None = None
    if local_repo:
        config_path = local_repo / ".airlock" / "config.json"
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text())
                github = config.get("github") if isinstance(config, dict) else None
                if isinstance(github, dict) and isinstance(github.get("read_token_env"), str):
                    token_env = github["read_token_env"]
            except Exception:
                token_env = None
    if token_env and os.environ.get(token_env):
        return os.environ[token_env]
    return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or None


def _default_output_path(target: RunTarget, attempt: int) -> Path:
    filename = f"{target.repo.replace('/', '-')}-{target.run_id}-attempt-{attempt}.json"
    if target.local_repo:
        return target.local_repo / ".airlock" / "ci" / filename
    return Path.cwd() / filename


def _key_path(target: RunTarget) -> Path:
    if target.local_repo:
        return target.local_repo / ".airlock" / "verification.key"
    return Path.home() / ".config" / "openline-airlock" / "verification.key"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="airlock ci",
        description="Reconstruct one completed GitHub Actions attempt and decide what its failure evidence authorizes.",
    )
    parser.add_argument("run", metavar="RUN", help="GitHub Actions run URL or numeric run ID")
    parser.add_argument("--repo", help="OWNER/REPO; required for numeric IDs when local origin cannot identify the repository")
    parser.add_argument("--out", help="Path for the canonical signed JSON receipt")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def record_run(
    run: str,
    *,
    repo_arg: str | None = None,
    cwd: Path | None = None,
    out: str | Path | None = None,
    client: GitHubActionsReadClient | None = None,
) -> dict[str, Any]:
    """Seal one completed GitHub Actions attempt and return the verified receipt.

    This is the programmatic boundary used by Nightshift.  It performs the same
    read-only retrieval and sealing work as ``airlock ci`` without routing through
    terminal text or granting any new authority.
    """
    target = resolve_target(run, repo_arg, cwd=cwd)
    reader = client or GitHubActionsReadClient(token=_token_from_environment(target.local_repo))
    bundle = build_source_bundle(reader, target.repo, target.run_id, target.attempt)
    key_path = _key_path(target)
    key = ensure_key(key_path)
    receipt = analyze_bundle(bundle, key=key)
    if not verify_ci_receipt(receipt, key)["valid"]:
        raise RetrievalIncomplete("Recorder could not verify its sealed receipt")
    attempt = int(receipt["payload"]["run"]["run_attempt"])
    output_path = Path(out).expanduser().resolve() if out is not None else _default_output_path(target, attempt)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = canonical_json_bytes(receipt) + b"\n"
    output_path.write_bytes(encoded)
    return {
        "target": target,
        "receipt": receipt,
        "receipt_path": output_path,
        "receipt_sha256": sha256_bytes(encoded.rstrip(b"\n")),
        "source_bundle": bundle,
        "key_path": key_path,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        recorded = record_run(args.run, repo_arg=args.repo, out=args.out)
        receipt = recorded["receipt"]
        encoded = canonical_json_bytes(receipt) + b"\n"
        if args.format == "json":
            sys.stdout.buffer.write(encoded)
        else:
            print(render_text(receipt))
            print(f"Canonical JSON: {recorded['receipt_path']}")
        return 0
    except CIRecorderError as exc:
        print(f"ERROR: {_safe_error_text(exc)}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        print(f"ERROR: {_safe_error_text(exc)}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
