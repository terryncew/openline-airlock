from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from airlock.sieve import sufficiency_check
from airlock.util import compact_result, matches_any, sha256_bytes, write_json

from .github_api import GitHubReadClient, parse_submit_comment, validate_submitter_and_fork
from .policy import load_submit_config, protected_touches

RESULT_MARKER_RE = re.compile(r"<!--\s*airlock-result:(\d+)\s*-->")


def _run(argv: list[str], cwd: Path, *, timeout: int | None = None, text: bool = True, env: dict | None = None):
    return subprocess.run(
        argv,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
        timeout=timeout,
        check=False,
        env=env,
    )


def _must(argv: list[str], cwd: Path, *, timeout: int = 120) -> str:
    cp = _run(argv, cwd, timeout=timeout)
    if cp.returncode != 0:
        raise RuntimeError(f"{' '.join(argv)} failed: {cp.stderr[-1200:]}")
    return cp.stdout


def _canonical_bytes(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _api(token: str, method: str, path: str, payload: dict | None = None):
    url = "https://api.github.com" + path
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "openline-airlock-actions/0.1")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[-1000:]
        raise RuntimeError(f"GitHub API {exc.code} for {path}: {body}") from exc


def _paged_comments(token: str, repo: str, path: str, *, max_pages: int = 20) -> list[dict]:
    out: list[dict] = []
    joiner = "&" if "?" in path else "?"
    last_full = False
    for page in range(1, max_pages + 1):
        rows = _api(token, "GET", f"{path}{joiner}per_page=100&page={page}")
        if not isinstance(rows, list):
            raise RuntimeError("GitHub comments endpoint returned a non-list response")
        out.extend(rows)
        last_full = len(rows) == 100
        if not last_full:
            return out
    if last_full:
        raise RuntimeError("comment history is too large to establish submission limits safely")
    return out


def _daily_count(token: str, repo: str, submitter: str, *, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    since = urllib.parse.quote((now - timedelta(days=1)).isoformat().replace("+00:00", "Z"))
    rows = _paged_comments(token, repo, f"/repos/{repo}/issues/comments?since={since}&sort=created&direction=desc")
    count = 0
    for row in rows:
        login = ((row.get("user") or {}).get("login") or "")
        if login.casefold() == submitter.casefold() and parse_submit_comment(row.get("body") or ""):
            count += 1
    return count


def _prior_open_submission(token: str, repo: str, issue: int, submitter: str, current_comment_id: int) -> int | None:
    rows = _paged_comments(token, repo, f"/repos/{repo}/issues/{issue}/comments")
    resolved = set()
    submissions: list[int] = []
    for row in rows:
        body = row.get("body") or ""
        login = ((row.get("user") or {}).get("login") or "")
        if login.casefold() == "github-actions[bot]":
            for match in RESULT_MARKER_RE.finditer(body):
                resolved.add(int(match.group(1)))
        if login.casefold() == submitter.casefold() and parse_submit_comment(body):
            cid = int(row.get("id") or 0)
            if cid and cid != current_comment_id:
                submissions.append(cid)
    for cid in sorted(submissions):
        if cid not in resolved:
            return cid
    return None


def _parse_name_status(raw: bytes) -> list[str]:
    parts = raw.split(b"\0")
    if parts and parts[-1] == b"":
        parts.pop()
    paths: list[str] = []
    i = 0
    while i < len(parts):
        status = parts[i].decode("ascii", errors="strict")
        i += 1
        count = 2 if status and status[0] in {"R", "C"} else 1
        if not status or i + count > len(parts):
            raise RuntimeError("malformed NUL-delimited git diff")
        for _ in range(count):
            paths.append(parts[i].decode("utf-8", errors="strict"))
            i += 1
    return paths


def _changed_paths(repo: Path, base: str, candidate: str) -> list[str]:
    cp = _run(
        ["git", "-c", "core.hooksPath=/dev/null", "diff", "--name-status", "-z", "--find-renames", "--find-copies", base, candidate],
        repo,
        timeout=120,
        text=False,
    )
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.decode(errors="replace")[-1000:])
    return _parse_name_status(cp.stdout)


def _tracked(repo: Path, commit: str) -> list[str]:
    cp = _run(["git", "ls-tree", "-r", "--name-only", "-z", commit], repo, timeout=120, text=False)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.decode(errors="replace")[-1000:])
    return [p.decode("utf-8") for p in cp.stdout.split(b"\0") if p]


def _base_airlock_config(repo: Path, base: str) -> dict:
    text = _must(["git", "show", f"{base}:.airlock/config.json"], repo)
    obj = json.loads(text)
    if obj.get("schema") != "airlock.config.v1":
        raise RuntimeError("base .airlock/config.json is missing or unsupported")
    return obj


def _outcome(*, decision: str, reason: str, admission: dict, execution_attempted: bool, **extra) -> dict:
    obj = {
        "schema": "airlock.github.outcome.v1",
        "submission_comment_id": admission["submission_comment_id"],
        "repo": admission["repo"],
        "issue_number": admission["issue_number"],
        "issue_title": admission.get("issue_title"),
        "submitter": admission["submitter"],
        "source_repo": admission["source_repo"],
        "source_sha": admission["source_sha"],
        "base_sha": admission["base_sha"],
        "decision": decision,
        "reason": reason,
        "execution_attempted": bool(execution_attempted),
        "changed_paths": admission.get("changed_paths", []),
        "protected_touches": admission.get("protected_touches", []),
        "airlock_config_sha256": admission.get("airlock_config_sha256"),
        "patch_sha256": admission.get("patch_sha256"),
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
        "workflow_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
    }
    obj.update(extra)
    return obj


def admit(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    event_path = Path(os.environ.get("GITHUB_EVENT_PATH", ""))
    if not event_path.exists():
        raise RuntimeError("GITHUB_EVENT_PATH is required")
    event = json.loads(event_path.read_text())
    config = load_submit_config(Path(".airlock/submit.json"))
    repo = ((event.get("repository") or {}).get("full_name") or "")
    issue = event.get("issue") or {}
    comment = event.get("comment") or {}
    sender = ((event.get("sender") or {}).get("login") or "").strip()
    comment_id = int(comment.get("id") or 0)
    parsed = parse_submit_comment(comment.get("body") or "")
    if not parsed:
        raise RuntimeError("issue comment is not an Airlock submission")
    if issue.get("pull_request"):
        raise RuntimeError("Airlock submissions must be issue comments, not PR comments")
    if repo.casefold() != str(config["repo"]).casefold():
        raise RuntimeError("repository does not match .airlock/submit.json")
    if not sender or not comment_id:
        raise RuntimeError("GitHub event is missing authenticated sender/comment id")
    source_repo, source_sha = parsed
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("read-only GITHUB_TOKEN is required for admission")

    try:
        daily = _daily_count(token, repo, sender)
        prior = _prior_open_submission(token, repo, int(issue["number"]), sender, comment_id)
    except RuntimeError as exc:
        admission = {
            "schema": "airlock.github.admission.v1", "status": "BLOCKED", "reason": "SUBMISSION_HISTORY_UNRESOLVED",
            "submission_comment_id": comment_id, "repo": repo, "issue_number": int(issue["number"]),
            "issue_title": str(issue.get("title") or f"Issue #{issue['number']}"), "submitter": sender,
            "source_repo": source_repo, "source_sha": source_sha, "base_sha": "", "changed_paths": [],
            "protected_touches": [], "airlock_config_sha256": None, "patch_sha256": None, "detail": str(exc),
        }
        write_json(out_dir / "admission.json", admission)
        write_json(out_dir / "outcome.json", _outcome(decision="BLOCKED", reason="SUBMISSION_HISTORY_UNRESOLVED", admission=admission, execution_attempted=False, detail=str(exc)))
        return admission

    if daily > int(config["max_daily_submissions_per_user"]):
        admission = {
            "schema": "airlock.github.admission.v1", "status": "BLOCKED", "reason": "DAILY_SUBMISSION_LIMIT",
            "submission_comment_id": comment_id, "repo": repo, "issue_number": int(issue["number"]),
            "issue_title": str(issue.get("title") or f"Issue #{issue['number']}"), "submitter": sender,
            "source_repo": source_repo, "source_sha": source_sha, "base_sha": "", "changed_paths": [],
            "protected_touches": [], "airlock_config_sha256": None, "patch_sha256": None,
        }
        write_json(out_dir / "admission.json", admission)
        write_json(out_dir / "outcome.json", _outcome(decision="BLOCKED", reason="DAILY_SUBMISSION_LIMIT", admission=admission, execution_attempted=False))
        return admission

    if prior:
        admission = {
            "schema": "airlock.github.admission.v1", "status": "BLOCKED", "reason": "OPEN_CANDIDATE_EXISTS",
            "submission_comment_id": comment_id, "repo": repo, "issue_number": int(issue["number"]),
            "issue_title": str(issue.get("title") or f"Issue #{issue['number']}"), "submitter": sender,
            "source_repo": source_repo, "source_sha": source_sha, "base_sha": "", "changed_paths": [],
            "protected_touches": [], "airlock_config_sha256": None, "patch_sha256": None, "prior_comment_id": prior,
        }
        write_json(out_dir / "admission.json", admission)
        write_json(out_dir / "outcome.json", _outcome(decision="BLOCKED", reason="OPEN_CANDIDATE_EXISTS", admission=admission, execution_attempted=False, prior_comment_id=prior))
        return admission

    client = GitHubReadClient(token)
    try:
        identity = validate_submitter_and_fork(client, config, sender, source_repo)
        base_sha = client.branch_head(repo, config["base_branch"])
    except RuntimeError as exc:
        admission = {
            "schema": "airlock.github.admission.v1", "status": "BLOCKED", "reason": "SOURCE_OR_IDENTITY_REJECTED",
            "submission_comment_id": comment_id, "repo": repo, "issue_number": int(issue["number"]),
            "issue_title": str(issue.get("title") or f"Issue #{issue['number']}"), "submitter": sender,
            "source_repo": source_repo, "source_sha": source_sha, "base_sha": "", "changed_paths": [],
            "protected_touches": [], "airlock_config_sha256": None, "patch_sha256": None, "detail": str(exc),
        }
        write_json(out_dir / "admission.json", admission)
        write_json(out_dir / "outcome.json", _outcome(decision="BLOCKED", reason="SOURCE_OR_IDENTITY_REJECTED", admission=admission, execution_attempted=False, detail=str(exc)))
        return admission

    cwd = Path.cwd()
    try:
        _must(["git", "fetch", "--no-tags", "origin", base_sha], cwd, timeout=300)
        _must(["git", "fetch", "--no-tags", f"https://github.com/{source_repo}.git", source_sha], cwd, timeout=300)
    except RuntimeError as exc:
        admission = {
            "schema": "airlock.github.admission.v1", "status": "BLOCKED", "reason": "SOURCE_FETCH_FAILED",
            "submission_comment_id": comment_id, "repo": repo, "issue_number": int(issue["number"]),
            "issue_title": str(issue.get("title") or f"Issue #{issue['number']}"), "submitter": sender,
            "source_repo": source_repo, "source_sha": source_sha, "base_sha": base_sha, "changed_paths": [],
            "protected_touches": [], "airlock_config_sha256": None, "patch_sha256": None, "detail": str(exc),
        }
        write_json(out_dir / "admission.json", admission)
        write_json(out_dir / "outcome.json", _outcome(decision="BLOCKED", reason="SOURCE_FETCH_FAILED", admission=admission, execution_attempted=False, detail=str(exc)))
        return admission
    if _run(["git", "merge-base", "--is-ancestor", base_sha, source_sha], cwd).returncode != 0:
        admission = {
            "schema": "airlock.github.admission.v1", "status": "BLOCKED", "reason": "BASE_NOT_ANCESTOR",
            "submission_comment_id": comment_id, "repo": repo, "issue_number": int(issue["number"]),
            "issue_title": str(issue.get("title") or f"Issue #{issue['number']}"), "submitter": sender,
            "source_repo": source_repo, "source_sha": source_sha, "base_sha": base_sha, "changed_paths": [],
            "protected_touches": [], "airlock_config_sha256": None, "patch_sha256": None,
        }
        write_json(out_dir / "admission.json", admission)
        write_json(out_dir / "outcome.json", _outcome(decision="BLOCKED", reason="BASE_NOT_ANCESTOR", admission=admission, execution_attempted=False))
        return admission

    airlock_config = _base_airlock_config(cwd, base_sha)
    config_sha = sha256_bytes(_canonical_bytes(airlock_config))
    protected = list(airlock_config.get("protected_paths", []))
    changed = _changed_paths(cwd, base_sha, source_sha)
    touched = protected_touches(changed, protected)
    admission = {
        "schema": "airlock.github.admission.v1",
        "status": "ADMITTED",
        "reason": "STATIC_PREFLIGHT_PASSED",
        "submission_comment_id": comment_id,
        "repo": repo,
        "issue_number": int(issue["number"]),
        "issue_title": str(issue.get("title") or f"Issue #{issue['number']}"),
        "submitter": sender,
        "source_repo": source_repo,
        "source_sha": source_sha,
        "base_sha": base_sha,
        "identity": identity,
        "changed_paths": sorted(set(changed)),
        "protected_paths": protected,
        "protected_touches": touched,
        "airlock_config_sha256": config_sha,
        "patch_sha256": None,
    }
    if touched:
        admission["status"] = "BLOCKED"
        admission["reason"] = "PROTECTED_FILES_CHANGED"
    elif len(set(changed)) > int(config["max_patch_files"]):
        admission["status"] = "BLOCKED"
        admission["reason"] = "PATCH_FILE_LIMIT"
    else:
        patch = out_dir / "candidate.patch"
        cp = _run(["git", "diff", "--binary", "--full-index", base_sha, source_sha], cwd, timeout=120, text=False)
        if cp.returncode != 0:
            raise RuntimeError(cp.stderr.decode(errors="replace")[-1000:])
        patch.write_bytes(cp.stdout)
        if patch.stat().st_size == 0:
            admission["status"] = "BLOCKED"
            admission["reason"] = "NO_PATCH"
            patch.unlink(missing_ok=True)
        elif patch.stat().st_size > int(config["max_patch_bytes"]):
            admission["status"] = "BLOCKED"
            admission["reason"] = "PATCH_SIZE_LIMIT"
            patch.unlink(missing_ok=True)
        else:
            admission["patch_sha256"] = _sha_file(patch)

    write_json(out_dir / "admission.json", admission)
    if admission["status"] == "BLOCKED":
        write_json(out_dir / "outcome.json", _outcome(decision="BLOCKED", reason=admission["reason"], admission=admission, execution_attempted=False))
    return admission


def _docker_run(workspace: Path, image: str, argv: list[str], config: dict) -> dict:
    if not shutil.which("docker"):
        raise RuntimeError("GitHub Actions Airlock evaluation requires Docker")
    cmd = [
        "docker", "run", "--rm", "--pull", "never", "--network", "none",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only",
        "--pids-limit", str(config["pids_limit"]), "--memory", str(config["memory"]), "--cpus", str(config["cpus"]),
        "--user", f"{os.getuid() if hasattr(os, 'getuid') else 65532}:{os.getgid() if hasattr(os, 'getgid') else 65532}",
        "--workdir", "/workspace", "--tmpfs", "/tmp:rw,nosuid,nodev,size=512m",
        "-e", "HOME=/tmp/airlock-home", "-e", "CI=1", "-e", "PYTHONPATH=/workspace/src:/workspace",
        "-v", f"{workspace}:/workspace:rw", "--entrypoint", "", image, *[str(x) for x in argv],
    ]
    started = time.monotonic()
    safe_env = {"PATH": os.environ.get("PATH", "")}
    try:
        cp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=int(config["evaluation_timeout_seconds"]), check=False, env=safe_env)
        raw = {"argv": argv, "exit_code": cp.returncode, "stdout": cp.stdout, "stderr": cp.stderr, "duration_seconds": round(time.monotonic()-started, 6), "timed_out": False}
    except subprocess.TimeoutExpired as exc:
        raw = {"argv": argv, "exit_code": 124, "stdout": exc.stdout or "", "stderr": exc.stderr or "", "duration_seconds": round(time.monotonic()-started, 6), "timed_out": True}
    return compact_result(raw)


def _run_group(workspace: Path, image: str, commands: list[list[str]], config: dict, kind: str) -> dict:
    rows = []
    for argv in commands:
        before = _must(["git", "status", "--porcelain", "--untracked-files=no"], workspace)
        record = _docker_run(workspace, image, argv, config)
        record["kind"] = kind
        after = _must(["git", "status", "--porcelain", "--untracked-files=no"], workspace)
        record["tracked_side_effect"] = bool(before.strip() or after.strip())
        rows.append(record)
        if record["tracked_side_effect"]:
            return {"rule": kind, "status": "FAIL", "reason": "EVALUATOR_SIDE_EFFECT", "commands": rows}
        if record["exit_code"] != 0 or record["timed_out"]:
            return {"rule": kind, "status": "FAIL", "commands": rows}
    return {"rule": kind, "status": "PASS", "commands": rows}


def evaluate(in_dir: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    admission = json.loads((in_dir / "admission.json").read_text())
    if admission["status"] != "ADMITTED":
        outcome = json.loads((in_dir / "outcome.json").read_text())
        write_json(out_dir / "outcome.json", outcome)
        return outcome

    config = load_submit_config(Path(".airlock/submit.json"))
    patch_src = in_dir / "candidate.patch"
    if _sha_file(patch_src) != admission["patch_sha256"]:
        raise RuntimeError("candidate patch hash changed after admission")
    _must(["git", "checkout", "--detach", admission["base_sha"]], Path.cwd())
    airlock_config = _base_airlock_config(Path.cwd(), admission["base_sha"])
    if sha256_bytes(_canonical_bytes(airlock_config)) != admission["airlock_config_sha256"]:
        raise RuntimeError("Airlock config changed after admission")

    image = f"airlock-evaluator:{os.environ.get('GITHUB_RUN_ID', 'local')}"
    build_temp = Path(tempfile.mkdtemp(prefix="airlock-image-"))
    build_ctx = build_temp / "context"
    build_ctx.mkdir()
    try:
        archive = _run(["git", "archive", "--format=tar", admission["base_sha"]], Path.cwd(), timeout=120, text=False)
        if archive.returncode != 0:
            raise RuntimeError(archive.stderr.decode(errors="replace")[-1200:])
        with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as tf:
            tf.extractall(build_ctx)
        build = _run(["docker", "build", "--pull", "-f", str(build_ctx / ".airlock/Dockerfile"), "-t", image, str(build_ctx)], Path.cwd(), timeout=1200)
        if build.returncode != 0:
            outcome = _outcome(decision="ERROR", reason="EVALUATOR_IMAGE_BUILD_FAILED", admission=admission, execution_attempted=False, build_stderr_tail=build.stderr[-1200:])
            write_json(out_dir / "outcome.json", outcome)
            return outcome
    finally:
        shutil.rmtree(build_temp, ignore_errors=True)

    temp = Path(tempfile.mkdtemp(prefix="airlock-actions-"))
    workspace = temp / "workspace"
    checks: list[dict] = []
    execution_attempted = False
    try:
        _must(["git", "worktree", "add", "--detach", str(workspace), admission["base_sha"]], Path.cwd())
        patch = out_dir / "candidate.patch"
        shutil.copyfile(patch_src, patch)
        apply = _run(["git", "apply", "--index", "--whitespace=nowarn", str(patch)], workspace, timeout=120)
        if apply.returncode != 0:
            outcome = _outcome(decision="BLOCKED", reason="PATCH_APPLY_FAILED", admission=admission, execution_attempted=False, checks=[])
            write_json(out_dir / "outcome.json", outcome)
            return outcome
        expected_tree = _must(["git", "write-tree"], workspace).strip()
        verification = airlock_config.get("verification", {})
        for kind, commands in (
            ("target", verification.get("target_commands", [])),
            ("static", verification.get("static_commands", [])),
            ("regression", verification.get("test_commands", [])),
        ):
            if commands:
                execution_attempted = True
            group = _run_group(workspace, image, commands, config, kind)
            checks.append(group)
            if group["status"] != "PASS":
                reason = group.get("reason") or ("TARGET_FAILED" if kind == "target" else "LINT_OR_TYPECHECK" if kind == "static" else "TESTS_FAILED")
                outcome = _outcome(decision="BLOCKED", reason=reason, admission=admission, execution_attempted=execution_attempted, checks=checks, expected_tree=expected_tree, container_image=image)
                write_json(out_dir / "outcome.json", outcome)
                return outcome

        test_patterns = [p for p in admission.get("protected_paths", []) if p.startswith(("tests/", "test/", "spec/", "__tests__/"))]
        test_files = [p for p in _tracked(Path.cwd(), admission["base_sha"]) if matches_any(p, test_patterns)]
        sufficient = sufficiency_check(Path.cwd(), admission["base_sha"], admission["changed_paths"], test_files, verification.get("target_commands", []))
        checks.append(sufficient)
        decision = "SURVIVED" if sufficient["status"] == "PASS" else "NEEDS_EVIDENCE"
        reason = "ALL_CONFIGURED_CHECKS_PASSED" if decision == "SURVIVED" else sufficient.get("basis", "INSUFFICIENT_EVIDENCE")
        outcome = _outcome(
            decision=decision, reason=reason, admission=admission, execution_attempted=execution_attempted,
            checks=checks, expected_tree=expected_tree, container_image=image, patch_sha256=_sha_file(patch),
        )
        write_json(out_dir / "outcome.json", outcome)
        return outcome
    finally:
        if workspace.exists():
            _run(["git", "worktree", "remove", "--force", str(workspace)], Path.cwd(), timeout=30)
        shutil.rmtree(temp, ignore_errors=True)


def _safe_title(title: str) -> str:
    title = " ".join(str(title).split())
    return (title[:110] or "Airlock contribution")


def _comment_body(outcome: dict, *, pr_url: str | None = None) -> str:
    marker = f"<!-- airlock-result:{outcome['submission_comment_id']} -->"
    decision = outcome["decision"]
    if pr_url:
        intro = f"Airlock: **SURVIVED** — {pr_url}"
    elif decision == "REOPEN":
        intro = "Airlock: **REOPEN** — the base branch moved after evaluation. Submit a fresh commit against current main."
    elif decision == "NEEDS_EVIDENCE":
        intro = f"Airlock: **NEEDS_EVIDENCE** — `{outcome['reason']}`. No PR was opened."
    elif decision == "BLOCKED":
        intro = f"Airlock: **BLOCKED** — `{outcome['reason']}`. No PR was opened."
    else:
        intro = f"Airlock: **{decision}** — `{outcome['reason']}`. No PR was opened."
    digest = hashlib.sha256(_canonical_bytes(outcome)).hexdigest()
    return f"{marker}\n{intro}\n\nVerification record SHA-256: `{digest}`"


def _post_comment(token: str, repo: str, issue: int, body: str) -> None:
    _api(token, "POST", f"/repos/{repo}/issues/{issue}/comments", {"body": body})


def _result_marker_exists(token: str, repo: str, issue: int, comment_id: int) -> bool:
    rows = _paged_comments(token, repo, f"/repos/{repo}/issues/{issue}/comments")
    marker = f"<!-- airlock-result:{comment_id} -->"
    for row in rows:
        login = ((row.get("user") or {}).get("login") or "").casefold()
        if login == "github-actions[bot]" and marker in (row.get("body") or ""):
            return True
    return False


def _existing_pr_for_branch(token: str, repo: str, branch: str) -> str | None:
    owner = repo.split("/", 1)[0]
    head = urllib.parse.quote(f"{owner}:{branch}", safe="")
    rows = _api(token, "GET", f"/repos/{repo}/pulls?state=all&head={head}&per_page=10")
    if isinstance(rows, list) and rows:
        return rows[0].get("html_url")
    return None


def publish(in_dir: Path) -> dict:
    outcome_path = in_dir / "outcome.json"
    outcome = json.loads(outcome_path.read_text())
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("trusted publish job requires GITHUB_TOKEN")
    repo_name = outcome["repo"]
    issue = int(outcome["issue_number"])
    config = load_submit_config(Path(".airlock/submit.json"))

    if _result_marker_exists(token, repo_name, issue, int(outcome["submission_comment_id"])):
        return {"decision": "ALREADY_PUBLISHED", "pr_opened": False}

    if outcome["decision"] != "SURVIVED":
        _post_comment(token, repo_name, issue, _comment_body(outcome))
        return {"decision": outcome["decision"], "pr_opened": False}

    branch = f"airlock/issue-{issue}/comment-{outcome['submission_comment_id']}"
    existing_pr = _existing_pr_for_branch(token, repo_name, branch)
    if existing_pr:
        _post_comment(token, repo_name, issue, _comment_body(outcome, pr_url=existing_pr))
        return {"decision": "PR_OPENED", "pr_opened": True, "pr_url": existing_pr, "replayed": True}

    current = GitHubReadClient(token).branch_head(repo_name, config["base_branch"])
    if current != outcome["base_sha"]:
        reopened = {**outcome, "decision": "REOPEN", "reason": "BASE_MOVED", "current_base_sha": current, "requires_fresh_evaluation": True}
        write_json(in_dir / "reopen.json", reopened)
        _post_comment(token, repo_name, issue, _comment_body(reopened))
        return {"decision": "REOPEN", "pr_opened": False}

    patch = in_dir / "candidate.patch"
    if not patch.exists() or _sha_file(patch) != outcome["patch_sha256"]:
        raise RuntimeError("trusted publisher patch binding failed")
    base_config = json.loads(_must(["git", "show", f"{outcome['base_sha']}:.airlock/config.json"], Path.cwd()))
    if sha256_bytes(_canonical_bytes(base_config)) != outcome.get("airlock_config_sha256"):
        raise RuntimeError("trusted publisher config binding failed")
    touched = protected_touches(outcome.get("changed_paths", []), base_config.get("protected_paths", []))
    if touched:
        raise RuntimeError("trusted publisher recheck found protected paths")

    event_path = Path(os.environ.get("GITHUB_EVENT_PATH", ""))
    if event_path.exists():
        event = json.loads(event_path.read_text())
        if int(((event.get("comment") or {}).get("id") or 0)) != int(outcome["submission_comment_id"]):
            raise RuntimeError("trusted publisher event/comment binding failed")
        if ((event.get("repository") or {}).get("full_name") or "").casefold() != repo_name.casefold():
            raise RuntimeError("trusted publisher event/repository binding failed")

    _must(["git", "checkout", "--detach", outcome["base_sha"]], Path.cwd())
    apply = _run(["git", "apply", "--index", "--whitespace=nowarn", str(patch)], Path.cwd(), timeout=120)
    if apply.returncode != 0:
        raise RuntimeError("trusted publisher could not apply evaluated patch")
    applied = [p for p in _must(["git", "diff", "--cached", "--name-only"], Path.cwd()).splitlines() if p]
    if sorted(applied) != sorted(outcome.get("changed_paths", [])):
        raise RuntimeError("trusted publisher file list differs from evaluated file list")
    tree = _must(["git", "write-tree"], Path.cwd()).strip()
    if tree != outcome.get("expected_tree"):
        raise RuntimeError("trusted publisher tree differs from evaluated tree")

    _must(["git", "config", "core.hooksPath", "/dev/null"], Path.cwd())
    _must(["git", "config", "commit.gpgsign", "false"], Path.cwd())
    _must(["git", "config", "user.name", "OpenLine Airlock"], Path.cwd())
    _must(["git", "config", "user.email", "airlock@users.noreply.github.com"], Path.cwd())
    _must(["git", "checkout", "-b", branch], Path.cwd())
    _must(["git", "commit", "-m", f"Airlock contribution for issue #{issue}"], Path.cwd())
    _must(["git", "push", "-u", "origin", branch], Path.cwd(), timeout=300)

    receipt = {
        "schema": "airlock.github.verification.v1",
        "decision": "READY_FOR_HUMAN_REVIEW",
        "repo": repo_name,
        "issue_number": issue,
        "submitter": outcome["submitter"],
        "base_sha": outcome["base_sha"],
        "source_sha": outcome["source_sha"],
        "patch_sha256": outcome["patch_sha256"],
        "airlock_config_sha256": outcome["airlock_config_sha256"],
        "changed_paths": outcome["changed_paths"],
        "checks": outcome.get("checks", []),
        "workflow_run_id": outcome.get("workflow_run_id"),
    }
    receipt_sha = hashlib.sha256(_canonical_bytes(receipt)).hexdigest()
    body = (
        f"Airlock survivor for #{issue}.\n\n"
        f"Submitted by `@{outcome['submitter']}`. The patch passed the repository-owned checks recorded below. "
        "This does not claim the patch is perfect; it records what earned maintainer review.\n\n"
        f"**Verification record SHA-256:** `{receipt_sha}`\n\n"
        "<details><summary>Airlock verification record</summary>\n\n"
        "```json\n" + json.dumps(receipt, indent=2, sort_keys=True) + "\n```\n\n</details>"
    )
    pr = _api(token, "POST", f"/repos/{repo_name}/pulls", {
        "title": _safe_title(f"Airlock: {outcome.get('issue_title') or f'issue #{issue}'}"),
        "head": branch,
        "base": config["base_branch"],
        "body": body,
    })
    pr_url = pr.get("html_url")
    if not pr_url:
        raise RuntimeError("GitHub did not return a PR URL")
    _post_comment(token, repo_name, issue, _comment_body(outcome, pr_url=pr_url))
    return {"decision": "PR_OPENED", "pr_opened": True, "pr_url": pr_url, "receipt_sha256": receipt_sha}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m airlock_submit.actions")
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("admit")
    a.add_argument("--out", type=Path, required=True)
    e = sub.add_parser("evaluate")
    e.add_argument("--in", dest="in_dir", type=Path, required=True)
    e.add_argument("--out", type=Path, required=True)
    pub = sub.add_parser("publish")
    pub.add_argument("--in", dest="in_dir", type=Path, required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "admit":
            result = admit(args.out)
        elif args.command == "evaluate":
            result = evaluate(args.in_dir, args.out)
        else:
            result = publish(args.in_dir)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        # Admission/evaluation failures become explicit, publishable ERROR outcomes instead of
        # disappearing into runner logs. The trusted publish step still never executes candidate code.
        try:
            if args.command == "evaluate":
                args.out.mkdir(parents=True, exist_ok=True)
                admission = json.loads((args.in_dir / "admission.json").read_text())
                error = _outcome(decision="ERROR", reason="EVALUATION_ERROR", admission=admission, execution_attempted=False, detail=str(exc))
                write_json(args.out / "outcome.json", error)
                print(json.dumps(error, indent=2, sort_keys=True))
                return 0
            if args.command == "admit":
                args.out.mkdir(parents=True, exist_ok=True)
                event_path = Path(os.environ.get("GITHUB_EVENT_PATH", ""))
                event = json.loads(event_path.read_text()) if event_path.exists() else {}
                issue = event.get("issue") or {}
                comment = event.get("comment") or {}
                sender = ((event.get("sender") or {}).get("login") or "unknown")
                parsed = parse_submit_comment(comment.get("body") or "") or ("unknown/unknown", "0" * 40)
                admission = {
                    "schema": "airlock.github.admission.v1", "status": "BLOCKED", "reason": "ADMISSION_ERROR",
                    "submission_comment_id": int(comment.get("id") or 0),
                    "repo": ((event.get("repository") or {}).get("full_name") or "unknown/unknown"),
                    "issue_number": int(issue.get("number") or 0), "issue_title": str(issue.get("title") or "Airlock submission"),
                    "submitter": sender, "source_repo": parsed[0], "source_sha": parsed[1], "base_sha": "",
                    "changed_paths": [], "protected_touches": [], "airlock_config_sha256": None, "patch_sha256": None,
                }
                write_json(args.out / "admission.json", admission)
                error = _outcome(decision="ERROR", reason="ADMISSION_ERROR", admission=admission, execution_attempted=False, detail=str(exc))
                write_json(args.out / "outcome.json", error)
                print(json.dumps(error, indent=2, sort_keys=True))
                return 0
        except Exception:
            pass
        print(json.dumps({"decision": "ERROR", "error": str(exc)}, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
