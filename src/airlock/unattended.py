from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

POLICY_SCHEMA = "airlock.unattended.policy.v1"
CANDIDATE_SCHEMA = "airlock.unattended.candidate.v1"
RESULT_SCHEMA = "airlock.unattended.v1"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _run(argv: list[str], cwd: Path, *, timeout: int | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    started = time.monotonic()
    try:
        cp = subprocess.run(
            argv,
            cwd=str(cwd),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return {
            "argv": argv,
            "exit_code": cp.returncode,
            "stdout": cp.stdout,
            "stderr": cp.stderr,
            "timed_out": False,
            "duration_seconds": round(time.monotonic() - started, 6),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "argv": argv,
            "exit_code": 124,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "timed_out": True,
            "duration_seconds": round(time.monotonic() - started, 6),
        }


def _git(repo: Path, *args: str, timeout: int | None = None, check: bool = True) -> str:
    result = _run(["git", *args], repo, timeout=timeout)
    if check and result["exit_code"] != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {str(result['stderr']).strip()}")
    return str(result["stdout"])


def _compact(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "argv": result["argv"],
        "exit_code": int(result["exit_code"]),
        "timed_out": bool(result.get("timed_out")),
        "duration_seconds": result.get("duration_seconds"),
        "stdout_sha256": sha256_bytes(str(result.get("stdout", "")).encode()),
        "stderr_sha256": sha256_bytes(str(result.get("stderr", "")).encode()),
        "stdout_tail": str(result.get("stdout", ""))[-1200:],
        "stderr_tail": str(result.get("stderr", ""))[-1200:],
    }


def load_policy(repo: Path) -> dict[str, Any]:
    path = repo / ".airlock" / "unattended.json"
    if not path.exists():
        raise RuntimeError(".airlock/unattended.json is missing")
    value = load_json(path)
    if not isinstance(value, dict) or value.get("schema") != POLICY_SCHEMA:
        raise RuntimeError("unsupported unattended policy")
    if int(value.get("candidate_count", 0)) < 1:
        raise RuntimeError("candidate_count must be >= 1")
    if not str(value.get("label", "")).strip():
        raise RuntimeError("unattended label is empty")
    evaluation = value.get("evaluation")
    if not isinstance(evaluation, dict) or not str(evaluation.get("image", "")).strip():
        raise RuntimeError("unattended evaluation image is missing")
    return value


def prompt_from_event(event_path: Path, candidate_id: str) -> str:
    event = load_json(event_path)
    issue = event.get("issue") or {}
    number = issue.get("number")
    title = issue.get("title")
    body = issue.get("body") or ""
    url = issue.get("html_url")
    if not isinstance(number, int) or not isinstance(title, str) or not isinstance(url, str):
        raise RuntimeError("GitHub issue event is missing issue metadata")
    return (
        f"You are Airlock candidate {candidate_id}, one independent attempt to fix GitHub issue #{number}.\n\n"
        f"Title: {title}\n\n{body}\n\nSource: {url}\n\n"
        "Work only in this checkout. Make the smallest complete code change that solves the issue. "
        "You may inspect and run the repository's existing checks. Do not push, open a pull request, "
        "or change the repository's policy/evaluator surfaces to make your patch pass. Airlock will "
        "independently decide whether the final tree earns review."
    )


def write_prompt(event_path: Path, candidate_id: str, out: Path) -> dict[str, Any]:
    text = prompt_from_event(event_path, candidate_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return {"prompt_sha256": sha256_bytes(text.encode()), "path": str(out)}


def capture_candidate(
    repo: Path,
    *,
    base: str,
    candidate_id: str,
    issue_number: int,
    issue_url: str,
    prompt_path: Path,
    expected_prompt_sha256: str | None,
    expected_git_config_sha256: str | None,
    final_message_path: Path | None,
    agent_outcome: str,
    out_dir: Path,
) -> dict[str, Any]:
    repo = repo.resolve()
    git_config = repo / ".git" / "config"
    if expected_git_config_sha256 is not None:
        if not git_config.exists() or sha256_file(git_config) != expected_git_config_sha256:
            raise RuntimeError("candidate changed local Git configuration; refusing artifact capture")
    _git(repo, "cat-file", "-e", f"{base}^{{commit}}")
    prompt_sha = expected_prompt_sha256 or sha256_file(prompt_path)
    final_sha = None
    if final_message_path and final_message_path.exists():
        final_sha = sha256_file(final_message_path)

    # Workflow scratch is generator context, never candidate content. Remove it before staging.
    scratch = repo / ".airlock-unattended"
    if scratch.exists():
        shutil.rmtree(scratch)
    _git(repo, "reset", "--mixed", base, check=False)
    _git(repo, "add", "-A")
    patch_result = _run(["git", "diff", "--cached", "--binary", "--full-index", base, "--"], repo)
    if patch_result["exit_code"] != 0:
        raise RuntimeError(str(patch_result["stderr"]).strip() or "could not capture candidate patch")
    patch = str(patch_result["stdout"]).encode()
    changed = [
        row.strip()
        for row in _git(repo, "diff", "--cached", "--name-only", base, "--").splitlines()
        if row.strip()
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    patch_path = out_dir / "candidate.patch"
    patch_path.write_bytes(patch)
    body = {
        "schema": CANDIDATE_SCHEMA,
        "candidate_id": candidate_id,
        "issue_number": int(issue_number),
        "issue_url": issue_url,
        "base_commit": base,
        "prompt_sha256": prompt_sha,
        "agent_outcome": agent_outcome,
        "patch_sha256": sha256_bytes(patch),
        "patch_bytes": len(patch),
        "changed_paths": changed,
        "final_message_sha256": final_sha,
    }
    manifest = {"candidate_manifest_sha256": sha256_bytes(canonical_bytes(body)), **body}
    write_json(out_dir / "candidate.json", manifest)
    return manifest


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) or path == pattern.rstrip("/") for pattern in patterns)


def _test_files(repo: Path, base: str, protected: list[str]) -> list[str]:
    test_patterns = [p for p in protected if p.startswith(("tests/", "test/", "spec/", "__tests__/"))]
    if not test_patterns:
        return []
    files = _git(repo, "ls-tree", "-r", "--name-only", base).splitlines()
    return [path for path in files if _matches_any(path, test_patterns)]


def _infer_modules(changed_paths: list[str]) -> set[str]:
    names: set[str] = set()
    for raw in changed_paths:
        p = Path(raw)
        if p.suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go"}:
            if p.stem not in {"__init__", "index", "mod"}:
                names.add(p.stem.lower())
            for part in p.parts[:-1]:
                if part not in {"src", "lib", "app", "pkg"}:
                    names.add(part.lower())
    return names


def _sufficiency(repo: Path, base: str, changed_paths: list[str], test_files: list[str], target: list[list[str]]) -> dict[str, Any]:
    if target:
        return {"rule": "evidence_sufficiency", "status": "PASS", "basis": "explicit_target_command", "matched_tests": []}
    modules = _infer_modules(changed_paths)
    if not modules:
        return {"rule": "evidence_sufficiency", "status": "INSUFFICIENT", "basis": "no_changed_source_module_detected", "matched_tests": []}
    matched: list[str] = []
    for path in test_files:
        text = _git(repo, "show", f"{base}:{path}", check=False).lower()
        if any(re.search(rf"\b{re.escape(name)}\b", text) for name in modules):
            matched.append(path)
    if not matched:
        return {
            "rule": "evidence_sufficiency",
            "status": "INSUFFICIENT",
            "basis": "no_baseline_test_references_changed_module",
            "changed_modules": sorted(modules),
            "matched_tests": [],
        }
    return {
        "rule": "evidence_sufficiency",
        "status": "PASS",
        "basis": "baseline_test_reference_heuristic",
        "changed_modules": sorted(modules),
        "matched_tests": matched,
    }


def _tree_delta_sha(worktree: Path, base: str) -> str:
    result = _run(["git", "diff", "--binary", "--full-index", base, "--"], worktree)
    if result["exit_code"] != 0:
        raise RuntimeError(str(result["stderr"]).strip() or "could not fingerprint candidate tree")
    return sha256_bytes(str(result["stdout"]).encode())


def _docker_command(worktree: Path, image: str, argv: list[str], timeout: int, policy: dict[str, Any]) -> dict[str, Any]:
    evaluation = policy["evaluation"]
    command = [
        "docker", "run", "--rm",
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--memory", str(evaluation.get("memory", "2g")),
        "--cpus", str(evaluation.get("cpus", "2")),
        "--pids-limit", str(int(evaluation.get("pids_limit", 512))),
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m",
        "-e", "HOME=/tmp/airlock-home",
        "-e", "PYTHONPATH=/workspace/src:/workspace",
        "-e", "GIT_TERMINAL_PROMPT=0",
        "-e", "GIT_OPTIONAL_LOCKS=0",
        "-v", f"{worktree}:/workspace:rw",
        "-v", f"{worktree / '.git'}:/workspace/.git:ro",
        "-w", "/workspace",
        image,
        *argv,
    ]
    return _run(command, worktree, timeout=timeout, env={"PATH": os.environ.get("PATH", "")})


def _run_check_group(
    worktree: Path,
    base: str,
    image: str,
    commands: list[list[str]],
    *,
    timeout: int,
    kind: str,
    policy: dict[str, Any],
    command_runner: Callable[[Path, str, list[str], int, dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for argv in commands:
        before = _tree_delta_sha(worktree, base)
        result = command_runner(worktree, image, list(argv), timeout, policy)
        compact = _compact(result)
        after = _tree_delta_sha(worktree, base)
        compact["kind"] = kind
        compact["side_effect"] = before != after
        rows.append(compact)
        if compact["exit_code"] != 0 or compact["timed_out"] or compact["side_effect"]:
            return {"rule": kind, "status": "FAIL", "commands": rows}
    return {"rule": kind, "status": "PASS", "commands": rows}


def _verify_candidate_manifest(candidate_dir: Path) -> tuple[dict[str, Any], Path]:
    manifest_path = candidate_dir / "candidate.json"
    patch_path = candidate_dir / "candidate.patch"
    if not manifest_path.exists() or not patch_path.exists():
        raise RuntimeError(f"candidate artifact incomplete: {candidate_dir}")
    manifest = load_json(manifest_path)
    if manifest.get("schema") != CANDIDATE_SCHEMA:
        raise RuntimeError(f"unsupported candidate artifact: {candidate_dir}")
    body = dict(manifest)
    claimed_manifest = body.pop("candidate_manifest_sha256", "")
    if claimed_manifest != sha256_bytes(canonical_bytes(body)):
        raise RuntimeError(f"candidate manifest hash mismatch: {candidate_dir}")
    if manifest.get("patch_sha256") != sha256_file(patch_path):
        raise RuntimeError(f"candidate patch hash mismatch: {candidate_dir}")
    return manifest, patch_path


def evaluate_candidates(
    repo: Path,
    *,
    base: str,
    issue_number: int,
    candidates_root: Path,
    out_dir: Path,
    workflow_run_id: str,
    workflow_run_attempt: str = "1",
    command_runner: Callable[[Path, str, list[str], int, dict[str, Any]], dict[str, Any]] = _docker_command,
) -> dict[str, Any]:
    repo = repo.resolve()
    if _git(repo, "rev-parse", "HEAD").strip() != base:
        raise RuntimeError("evaluation checkout does not match frozen base")
    policy = load_policy(repo)
    config_path = repo / ".airlock" / "config.json"
    config = load_json(config_path)
    if config.get("schema") != "airlock.config.v1":
        raise RuntimeError("unsupported Airlock config")

    candidate_dirs = sorted({p.parent for p in candidates_root.rglob("candidate.json")})
    if len(candidate_dirs) != int(policy["candidate_count"]):
        raise RuntimeError(
            f"expected {policy['candidate_count']} candidate artifacts, found {len(candidate_dirs)}"
        )

    protected = [str(p) for p in config.get("protected_paths", [])]
    verification = config.get("verification", {})
    target = [list(row) for row in verification.get("target_commands", [])]
    static = [list(row) for row in verification.get("static_commands", [])]
    regression = [list(row) for row in verification.get("test_commands", [])]
    timeout = int(verification.get("timeout_seconds", 1200))
    image = str(policy["evaluation"]["image"])
    test_files = _test_files(repo, base, protected)

    rows: list[dict[str, Any]] = []
    survivors: list[tuple[dict[str, Any], Path]] = []
    temp_root = Path(tempfile.mkdtemp(prefix="airlock-unattended-eval-"))
    try:
        for candidate_dir in candidate_dirs:
            manifest, patch_path = _verify_candidate_manifest(candidate_dir)
            row: dict[str, Any] = {
                "candidate_id": manifest["candidate_id"],
                "patch_sha256": manifest["patch_sha256"],
                "agent_outcome": manifest.get("agent_outcome"),
                "checks": [],
            }
            if manifest.get("base_commit") != base or int(manifest.get("issue_number", -1)) != int(issue_number):
                row.update({"disposition": "BLOCKED", "reason": "BINDING_MISMATCH"})
                rows.append(row)
                continue
            if manifest.get("agent_outcome") != "success":
                row.update({"disposition": "ERROR", "reason": "GENERATOR_FAILED", "changed_paths": list(manifest.get("changed_paths", []))})
                rows.append(row)
                continue
            if int(manifest.get("patch_bytes", 0)) == 0:
                row.update({"disposition": "BLOCKED", "reason": "NO_PATCH", "changed_paths": []})
                rows.append(row)
                continue

            wt = temp_root / str(manifest["candidate_id"])
            clone = _run(["git", "clone", "--no-hardlinks", "--quiet", str(repo), str(wt)], repo, timeout=120)
            if clone["exit_code"] != 0:
                raise RuntimeError(str(clone["stderr"]).strip() or "could not create isolated evaluator clone")
            _git(wt, "checkout", "--detach", base)
            try:
                apply_result = _run(["git", "apply", "--index", "--binary", str(patch_path)], wt)
                if apply_result["exit_code"] != 0:
                    row.update({"disposition": "BLOCKED", "reason": "PATCH_APPLY_FAILED"})
                    rows.append(row)
                    continue
                actual_paths = [
                    p.strip() for p in _git(wt, "diff", "--cached", "--name-only", base, "--").splitlines() if p.strip()
                ]
                row["changed_paths"] = actual_paths
                if actual_paths != list(manifest.get("changed_paths", [])):
                    row.update({"disposition": "BLOCKED", "reason": "PATCH_PATH_BINDING_MISMATCH"})
                    rows.append(row)
                    continue
                touched = [p for p in actual_paths if _matches_any(p, protected)]
                protected_check = {"rule": "protected_files", "status": "FAIL" if touched else "PASS", "touched": touched}
                row["checks"].append(protected_check)
                if touched:
                    row.update({"disposition": "BLOCKED", "reason": "PROTECTED_FILES_CHANGED"})
                    rows.append(row)
                    continue

                for kind, commands, failure_reason in (
                    ("target", target, "TARGET_FAILED"),
                    ("static", static, "LINT_OR_TYPECHECK"),
                    ("regression", regression, "TESTS_FAILED"),
                ):
                    check = _run_check_group(
                        wt, base, image, commands,
                        timeout=timeout,
                        kind=kind,
                        policy=policy,
                        command_runner=command_runner,
                    )
                    row["checks"].append(check)
                    if check["status"] != "PASS":
                        row.update({"disposition": "BLOCKED", "reason": failure_reason})
                        break
                if row.get("disposition") == "BLOCKED":
                    rows.append(row)
                    continue

                suff = _sufficiency(repo, base, actual_paths, test_files, target)
                row["checks"].append(suff)
                if suff["status"] != "PASS":
                    row.update({"disposition": "NEEDS_EVIDENCE", "reason": suff["basis"]})
                    rows.append(row)
                    continue
                row.update({"disposition": "SURVIVED", "reason": "ALL_CONFIGURED_CHECKS_PASSED"})
                rows.append(row)
                survivors.append((row, patch_path))
            finally:
                shutil.rmtree(wt, ignore_errors=True)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    generator_failures = sum(row.get("reason") == "GENERATOR_FAILED" for row in rows)

    # Four independent agents may arrive at the exact same patch. That is one
    # implementation, not four competing implementations. Collapse byte-identical
    # survivor patches by their bound SHA-256, while preserving every candidate row
    # in the receipt. Distinct surviving patches still require a human choice.
    unique_by_patch: dict[str, tuple[dict[str, Any], Path]] = {}
    equivalent_ids: dict[str, list[str]] = {}
    for survivor, patch_path in survivors:
        patch_sha = str(survivor["patch_sha256"])
        unique_by_patch.setdefault(patch_sha, (survivor, patch_path))
        equivalent_ids.setdefault(patch_sha, []).append(str(survivor["candidate_id"]))
    unique_survivors = [unique_by_patch[key] for key in sorted(unique_by_patch)]

    if len(unique_survivors) == 1:
        decision = "READY_FOR_REVIEW"
    elif len(unique_survivors) > 1:
        decision = "MULTIPLE_SURVIVORS"
    elif rows and generator_failures == len(rows):
        decision = "ENVIRONMENT_FAILURE"
    else:
        decision = "NO_PATCH_READY"

    body: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "issue_number": int(issue_number),
        "base_commit": base,
        "config_sha256": sha256_file(config_path),
        "policy_sha256": sha256_file(repo / ".airlock" / "unattended.json"),
        "workflow_run_id": str(workflow_run_id),
        "workflow_run_attempt": str(workflow_run_attempt),
        "candidate_count": len(rows),
        "survivor_count": len(survivors),
        "unique_survivor_count": len(unique_survivors),
        "generator_failures": generator_failures,
        "decision": decision,
        "candidates": rows,
        "security_boundary": {
            "generator_has_github_write_token": False,
            "evaluation_has_provider_secret": False,
            "evaluation_network": "none",
            "publication_executes_candidate_code": False,
        },
    }
    if len(unique_survivors) == 1:
        survivor, patch_path = unique_survivors[0]
        patch_sha = str(survivor["patch_sha256"])
        body["survivor"] = {
            "candidate_id": survivor["candidate_id"],
            "equivalent_candidate_ids": sorted(equivalent_ids[patch_sha]),
            "patch_sha256": patch_sha,
            "changed_paths": survivor["changed_paths"],
        }
    result = {"receipt_sha256": sha256_bytes(canonical_bytes(body)), **body}
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "result.json", result)
    (out_dir / "result.sha256").write_text(sha256_file(out_dir / "result.json") + "\n", encoding="utf-8")
    if len(unique_survivors) == 1:
        shutil.copy2(unique_survivors[0][1], out_dir / "survivor.patch")
    return result


def verify_result(result_path: Path, patch_path: Path | None = None) -> dict[str, Any]:
    value = load_json(result_path)
    if value.get("schema") != RESULT_SCHEMA:
        return {"valid": False, "reason": "SCHEMA"}
    body = dict(value)
    claimed = body.pop("receipt_sha256", "")
    if claimed != sha256_bytes(canonical_bytes(body)):
        return {"valid": False, "reason": "RECEIPT_HASH"}
    if value.get("decision") == "READY_FOR_REVIEW":
        if patch_path is None or not patch_path.exists():
            return {"valid": False, "reason": "SURVIVOR_PATCH_MISSING"}
        if sha256_file(patch_path) != value.get("survivor", {}).get("patch_sha256"):
            return {"valid": False, "reason": "SURVIVOR_PATCH_HASH"}
    return {"valid": True, "receipt_sha256": claimed}


def _safe_branch(issue_number: int, run_id: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", run_id).strip("-")[:32] or "run"
    return f"airlock/unattended/issue-{issue_number}-{clean}"


def _remote_branch_state(
    repo: Path,
    *,
    branch: str,
    base: str,
    expected_patch_sha256: str,
    expected_paths: list[str],
) -> dict[str, Any]:
    probe = _run(["git", "ls-remote", "--heads", "origin", f"refs/heads/{branch}"], repo, timeout=120)
    if probe["exit_code"] != 0:
        raise RuntimeError(str(probe["stderr"]).strip() or "could not inspect survivor branch")
    if not str(probe["stdout"]).strip():
        return {"exists": False}

    fetch = _run([
        "git", "fetch", "origin",
        f"refs/heads/{branch}:refs/remotes/origin/{branch}",
    ], repo, timeout=120)
    if fetch["exit_code"] != 0:
        raise RuntimeError(str(fetch["stderr"]).strip() or "could not fetch existing survivor branch")
    remote_ref = f"origin/{branch}"
    remote_sha = _git(repo, "rev-parse", remote_ref).strip()
    parent = _git(repo, "rev-parse", f"{remote_sha}^").strip()
    if parent != base:
        raise RuntimeError("existing survivor branch is not based on the evaluated commit")
    diff = _run(["git", "diff", "--binary", "--full-index", base, remote_sha, "--"], repo)
    if diff["exit_code"] != 0:
        raise RuntimeError(str(diff["stderr"]).strip() or "could not verify existing survivor branch")
    if sha256_bytes(str(diff["stdout"]).encode()) != expected_patch_sha256:
        raise RuntimeError("existing survivor branch patch does not match the admitted receipt")
    paths = [
        row.strip()
        for row in _git(repo, "diff", "--name-only", base, remote_sha, "--").splitlines()
        if row.strip()
    ]
    if paths != expected_paths:
        raise RuntimeError("existing survivor branch changed-path binding mismatch")
    return {"exists": True, "sha": remote_sha}


def _existing_pull_request(repo: Path, *, branch: str, base_branch: str) -> dict[str, Any] | None:
    if not shutil.which("gh"):
        raise RuntimeError("GitHub CLI is required in the trusted publication job")
    found = _run([
        "gh", "pr", "list",
        "--state", "all",
        "--base", base_branch,
        "--head", branch,
        "--limit", "1",
        "--json", "number,url,state,headRefOid",
    ], repo, timeout=120)
    if found["exit_code"] != 0:
        raise RuntimeError(str(found["stderr"]).strip() or "publisher could not inspect existing pull requests")
    try:
        rows = json.loads(str(found["stdout"]) or "[]")
    except Exception as exc:
        raise RuntimeError("publisher could not parse existing pull request state") from exc
    if not rows:
        return None
    row = rows[0]
    if not isinstance(row, dict):
        raise RuntimeError("publisher received invalid pull request state")
    return row


def publication_plan(repo: Path, result: dict[str, Any], *, current_base: str) -> dict[str, Any]:
    if current_base != result.get("base_commit"):
        return {"status": "REOPEN", "reason": "BASE_MOVED"}
    decision = result.get("decision")
    if decision == "READY_FOR_REVIEW":
        return {"status": "PUBLISH"}
    if decision == "MULTIPLE_SURVIVORS":
        return {"status": "NEEDS_CHOICE"}
    if decision == "ENVIRONMENT_FAILURE":
        return {"status": "FIX_ENV"}
    return {"status": "NO_REVIEW"}


def publish_result(
    repo: Path,
    *,
    result_path: Path,
    patch_path: Path | None,
    issue_number: int,
    base_branch: str,
) -> dict[str, Any]:
    repo = repo.resolve()
    verification = verify_result(result_path, patch_path)
    if not verification["valid"]:
        raise RuntimeError(f"unattended result failed verification: {verification['reason']}")
    result = load_json(result_path)
    fetch = _run(["git", "fetch", "origin", base_branch], repo, timeout=120)
    if fetch["exit_code"] != 0:
        raise RuntimeError(str(fetch["stderr"]).strip() or "could not fetch base branch")
    current = _git(repo, "rev-parse", f"origin/{base_branch}").strip()
    plan = publication_plan(repo, result, current_base=current)
    if plan["status"] == "REOPEN":
        if shutil.which("gh"):
            _run([
                "gh", "issue", "comment", str(issue_number),
                "--body", "Airlock result: **REOPEN** — the base branch moved after evaluation. Remove and re-add the `airlock` label to retry from the new base.",
            ], repo, timeout=60)
        return plan
    if plan["status"] == "NEEDS_CHOICE":
        if shutil.which("gh"):
            _run([
                "gh", "issue", "comment", str(issue_number),
                "--body", (
                    f"Airlock found {result.get('unique_survivor_count', result.get('survivor_count'))} distinct independently passing patches and refused to invent a winner. "
                    f"See Actions run `{result.get('workflow_run_id')}` for the retained candidate evidence."
                ),
            ], repo, timeout=60)
        return plan
    if plan["status"] == "FIX_ENV":
        if shutil.which("gh"):
            _run([
                "gh", "issue", "comment", str(issue_number),
                "--body", (
                    "Airlock could not complete generation in this run, so no candidate was admitted. "
                    f"See Actions run `{result.get('workflow_run_id')}` and fix the generator environment before retrying."
                ),
            ], repo, timeout=60)
        return plan
    if plan["status"] != "PUBLISH":
        return plan
    if patch_path is None:
        raise RuntimeError("survivor patch missing")

    base = str(result["base_commit"])
    expected_paths = list(result.get("survivor", {}).get("changed_paths", []))
    patch_sha = str(result.get("survivor", {}).get("patch_sha256", ""))

    # Re-apply and re-check the admitted patch even on a publisher retry. Publication
    # owns GitHub writes, but it still does not get to reinterpret evaluator evidence.
    _git(repo, "checkout", "--detach", base)
    apply_result = _run(["git", "apply", "--index", "--binary", str(patch_path)], repo)
    if apply_result["exit_code"] != 0:
        raise RuntimeError(str(apply_result["stderr"]).strip() or "publisher could not apply survivor patch")
    actual_paths = [p.strip() for p in _git(repo, "diff", "--cached", "--name-only", base, "--").splitlines() if p.strip()]
    if actual_paths != expected_paths:
        raise RuntimeError("publisher changed-path binding mismatch")
    config = load_json(repo / ".airlock" / "config.json")
    protected = [str(p) for p in config.get("protected_paths", [])]
    touched = [p for p in actual_paths if _matches_any(p, protected)]
    if touched:
        raise RuntimeError(f"publisher recheck found protected paths: {touched}")

    run_id = f"{result.get('workflow_run_id') or 'run'}-{result.get('workflow_run_attempt') or '1'}"
    branch = _safe_branch(issue_number, run_id)
    remote = _remote_branch_state(
        repo,
        branch=branch,
        base=base,
        expected_patch_sha256=patch_sha,
        expected_paths=expected_paths,
    )
    reused_branch = bool(remote.get("exists"))
    if not reused_branch:
        _git(repo, "switch", "-c", branch)
        _git(repo, "config", "user.name", "github-actions[bot]")
        _git(repo, "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
        _git(repo, "commit", "-m", f"airlock: survivor for issue #{issue_number}")
        push = _run(["git", "push", "-u", "origin", branch], repo, timeout=120)
        if push["exit_code"] != 0:
            raise RuntimeError(str(push["stderr"]).strip() or "publisher could not push survivor branch")

    checks: list[str] = []
    survivor_id = result["survivor"]["candidate_id"]
    survivor_row = next(row for row in result["candidates"] if row["candidate_id"] == survivor_id)
    for check in survivor_row.get("checks", []):
        for command in check.get("commands", []):
            checks.append(f"- `{shlex.join(command['argv'])}` → exit {command['exit_code']}")
    body = "\n".join([
        f"Airlock independently admitted one survivor for issue #{issue_number}.",
        "",
        f"Fixes #{issue_number}",
        "",
        "### Airlock receipt",
        f"- Base: `{base}`",
        f"- Candidate: `{survivor_id}`",
        f"- Patch SHA-256: `{patch_sha}`",
        f"- Config SHA-256: `{result['config_sha256']}`",
        f"- Receipt SHA-256: `{result['receipt_sha256']}`",
        f"- Workflow run: `{result['workflow_run_id']}` (attempt `{result.get('workflow_run_attempt', '1')}`)",
        "",
        "### Recorded checks",
        *(checks or ["- No configured executable checks were recorded."]),
        "",
        "Generation had no GitHub write credential. Candidate evaluation ran without the provider secret and with network disabled. The publication job did not execute candidate code.",
    ])

    existing_pr = _existing_pull_request(repo, branch=branch, base_branch=base_branch)
    if existing_pr is not None:
        state = str(existing_pr.get("state", "")).upper()
        url = str(existing_pr.get("url", "")).strip()
        if state != "OPEN":
            return {
                "status": "PUBLISHED_CLOSED",
                "branch": branch,
                "url": url,
                "reused_branch": True,
                "reused_pr": True,
            }
        return {
            "status": "PUBLISHED",
            "branch": branch,
            "url": url,
            "reused_branch": True,
            "reused_pr": True,
        }

    pr = _run([
        "gh", "pr", "create",
        "--base", base_branch,
        "--head", branch,
        "--title", f"Airlock: survivor for issue #{issue_number}",
        "--body", body,
    ], repo, timeout=120)
    if pr["exit_code"] != 0:
        raise RuntimeError(str(pr["stderr"]).strip() or "publisher could not open pull request")
    return {
        "status": "PUBLISHED",
        "branch": branch,
        "url": str(pr["stdout"]).strip(),
        "reused_branch": reused_branch,
        "reused_pr": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m airlock.unattended")
    sub = parser.add_subparsers(dest="command", required=True)

    prompt = sub.add_parser("prompt")
    prompt.add_argument("--event", required=True)
    prompt.add_argument("--candidate", required=True)
    prompt.add_argument("--out", required=True)

    capture = sub.add_parser("capture")
    capture.add_argument("--repo", default=".")
    capture.add_argument("--base", required=True)
    capture.add_argument("--candidate", required=True)
    capture.add_argument("--issue", type=int, required=True)
    capture.add_argument("--issue-url", required=True)
    capture.add_argument("--prompt", required=True)
    capture.add_argument("--prompt-sha")
    capture.add_argument("--git-config-sha")
    capture.add_argument("--final-message")
    capture.add_argument("--agent-outcome", default="unknown")
    capture.add_argument("--out", required=True)

    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--repo", default=".")
    evaluate.add_argument("--base", required=True)
    evaluate.add_argument("--issue", type=int, required=True)
    evaluate.add_argument("--candidates", required=True)
    evaluate.add_argument("--workflow-run-id", required=True)
    evaluate.add_argument("--workflow-run-attempt", default="1")
    evaluate.add_argument("--out", required=True)

    publish = sub.add_parser("publish")
    publish.add_argument("--repo", default=".")
    publish.add_argument("--result", required=True)
    publish.add_argument("--patch")
    publish.add_argument("--issue", type=int, required=True)
    publish.add_argument("--base-branch", default="main")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "prompt":
        info = write_prompt(Path(args.event), args.candidate, Path(args.out))
        print(json.dumps(info, sort_keys=True))
        return 0
    if args.command == "capture":
        final = Path(args.final_message) if args.final_message else None
        manifest = capture_candidate(
            Path(args.repo),
            base=args.base,
            candidate_id=args.candidate,
            issue_number=args.issue,
            issue_url=args.issue_url,
            prompt_path=Path(args.prompt),
            expected_prompt_sha256=args.prompt_sha,
            expected_git_config_sha256=args.git_config_sha,
            final_message_path=final,
            agent_outcome=args.agent_outcome,
            out_dir=Path(args.out),
        )
        print(json.dumps({"candidate_id": manifest["candidate_id"], "patch_sha256": manifest["patch_sha256"]}, sort_keys=True))
        return 0
    if args.command == "evaluate":
        result = evaluate_candidates(
            Path(args.repo),
            base=args.base,
            issue_number=args.issue,
            candidates_root=Path(args.candidates),
            out_dir=Path(args.out),
            workflow_run_id=args.workflow_run_id,
            workflow_run_attempt=args.workflow_run_attempt,
        )
        print(json.dumps({"decision": result["decision"], "survivors": result["survivor_count"], "receipt_sha256": result["receipt_sha256"]}, sort_keys=True))
        return 0
    if args.command == "publish":
        patch = Path(args.patch) if args.patch else None
        result = publish_result(
            Path(args.repo),
            result_path=Path(args.result),
            patch_path=patch,
            issue_number=args.issue,
            base_branch=args.base_branch,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    raise RuntimeError("unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
