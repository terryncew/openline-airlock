from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from airlock.util import canonical_json_bytes, sha256_bytes, sha256_file, write_json

from .policy import load_submit_config, protected_touches
from .seal import load_verified
from .store import Store


def _run(argv: list[str], cwd: Path, *, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=timeout, check=False)


def _must(argv: list[str], cwd: Path, *, timeout: int = 120) -> str:
    cp = _run(argv, cwd, timeout=timeout)
    if cp.returncode != 0:
        raise RuntimeError(f"{' '.join(argv)} failed: {cp.stderr[-1000:]}")
    return cp.stdout


def _safe_title(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    return text[:180] or "Airlock contribution"


def _receipt_markdown(submission: dict, evaluation: dict, receipt_sha: str, receipt: dict | None = None) -> str:
    lines = [
        "### Airlock",
        "",
        f"This patch was submitted by @{submission['submitter']} and passed the repository checks listed below before entering the PR queue.",
        "",
        f"- Issue: #{submission['issue_number']}",
        f"- Base commit: `{evaluation['base_sha']}`",
        f"- Candidate commit: `{evaluation['source_sha']}`",
        f"- Patch SHA-256: `{evaluation['patch_sha256']}`",
        f"- Airlock config SHA-256: `{evaluation['airlock_config_sha256']}`",
        f"- Protected files changed: `{len(evaluation.get('protected_touches', []))}`",
        f"- Receipt SHA-256: `{receipt_sha}`",
        "",
        "Checks:",
    ]
    for check in evaluation.get("checks", []):
        rule = check.get("rule", "check")
        status = check.get("status", "UNKNOWN")
        commands = check.get("commands", [])
        if commands:
            for row in commands:
                argv = " ".join(str(x) for x in row.get("argv", []))
                lines.append(f"- `{argv}` — **{status}** (exit {row.get('exit_code')})")
        else:
            basis = check.get("basis")
            suffix = f" — {basis}" if basis else ""
            lines.append(f"- `{rule}` — **{status}**{suffix}")
    lines += [
        "",
        "Airlock records the exact checks that ran. This does not claim unknown behavior is correct.",
    ]
    if receipt is not None:
        lines += [
            "",
            "<details><summary>Airlock receipt</summary>",
            "",
            "```json",
            json.dumps(receipt, indent=2, sort_keys=True),
            "```",
            "",
            "</details>",
        ]
    return "\n".join(lines) + "\n"


def open_pr(*, submission_id: str, config_path: Path, db_path: Path, evaluation_key: str | None = None) -> dict:
    config = load_submit_config(config_path)
    key = evaluation_key or os.environ.get("AIRLOCK_EVALUATION_KEY", "")
    if not key:
        raise RuntimeError("AIRLOCK_EVALUATION_KEY is required")
    if not shutil.which("gh"):
        raise RuntimeError("trusted PR opener requires the GitHub CLI (`gh`)")

    store = Store(db_path)
    try:
        submission = store.get(submission_id)
        if submission["state"] != "SURVIVED":
            raise RuntimeError(f"submission is not eligible to open a PR: {submission['state']}")
        artifact_dir = Path(submission["artifact_dir"])
        bundle = load_verified(artifact_dir / "bundle.json", key)
        if bundle.get("submission_id") != submission_id:
            raise RuntimeError("bundle is bound to a different submission")
        patch_path = artifact_dir / bundle["patch"]["name"]
        evaluation_path = artifact_dir / bundle["evaluation"]["name"]
        if sha256_file(patch_path) != bundle["patch"]["sha256"]:
            raise RuntimeError("candidate patch hash mismatch")
        if sha256_file(evaluation_path) != bundle["evaluation"]["sha256"]:
            raise RuntimeError("evaluation record hash mismatch")
        evaluation = json.loads(evaluation_path.read_text())
        if evaluation.get("decision") != "SURVIVED":
            raise RuntimeError("evaluation does not authorize review")
        if evaluation.get("submission_id") != submission_id:
            raise RuntimeError("evaluation is bound to a different submission")
        if evaluation.get("base_sha") != submission["base_sha"] or evaluation.get("source_sha") != submission["source_sha"]:
            raise RuntimeError("evaluation commit binding mismatch")
        evaluation["patch_sha256"] = sha256_file(patch_path)
        touched = protected_touches(evaluation.get("changed_paths", []), evaluation.get("protected_paths", []))
        if touched:
            raise RuntimeError("protected-path check failed again in trusted opener")

        temp = Path(tempfile.mkdtemp(prefix=f"airlock-open-{submission_id}-"))
        repo = temp / "repo"
        try:
            repo.mkdir()
            _must(["git", "init", "-q"], repo)
            _must(["git", "config", "core.hooksPath", "/dev/null"], repo)
            remote = f"https://github.com/{submission['repo']}.git"
            _must(["git", "remote", "add", "origin", remote], repo)
            remote_head = _must(["git", "ls-remote", remote, f"refs/heads/{config['base_branch']}"], repo).split()[0]
            if remote_head != submission["base_sha"]:
                raise RuntimeError("base branch moved; candidate must be re-evaluated")
            _must(["git", "fetch", "--no-tags", "origin", submission["base_sha"]], repo, timeout=300)
            _must(["git", "checkout", "--detach", submission["base_sha"]], repo)
            apply = _run(["git", "apply", "--index", "--whitespace=nowarn", str(patch_path)], repo)
            if apply.returncode != 0:
                raise RuntimeError("trusted opener could not apply sealed patch: " + apply.stderr[-1000:])
            cached = _must(["git", "diff", "--cached", "--name-only", "-z"], repo)
            applied_paths = [p for p in cached.split("\0") if p]
            if sorted(applied_paths) != sorted(evaluation.get("changed_paths", [])):
                raise RuntimeError("applied file list differs from evaluated file list")
            if protected_touches(applied_paths, evaluation.get("protected_paths", [])):
                raise RuntimeError("sealed patch touches protected paths")
            tree = _must(["git", "write-tree"], repo).strip()
            if tree != bundle.get("expected_tree") or tree != evaluation.get("expected_tree"):
                raise RuntimeError("applied tree differs from evaluated tree")

            _must(["git", "config", "user.name", "OpenLine Airlock"], repo)
            _must(["git", "config", "user.email", "airlock@users.noreply.github.com"], repo)
            branch = f"airlock/issue-{submission['issue_number']}/{submission_id}"
            _must(["git", "checkout", "-b", branch], repo)
            _must(["git", "commit", "-m", f"Airlock contribution for issue #{submission['issue_number']}"], repo)
            _must(["git", "push", "-u", "origin", branch], repo, timeout=300)

            receipt = {
                "schema": "airlock.submit.receipt.v1",
                "submission_id": submission_id,
                "repo": submission["repo"],
                "issue_number": submission["issue_number"],
                "submitter": submission["submitter"],
                "base_sha": evaluation["base_sha"],
                "source_sha": evaluation["source_sha"],
                "patch_sha256": evaluation["patch_sha256"],
                "airlock_config_sha256": evaluation["airlock_config_sha256"],
                "container_image": evaluation["container_image"],
                "changed_paths": evaluation["changed_paths"],
                "protected_touches": [],
                "checks": evaluation["checks"],
                "decision": "READY_FOR_HUMAN_REVIEW",
            }
            receipt_sha = sha256_bytes(canonical_json_bytes(receipt))
            receipt_path = artifact_dir / "receipt.json"
            write_json(receipt_path, receipt)
            body_path = temp / "pr-body.md"
            body_path.write_text(_receipt_markdown(submission, {**evaluation, "patch_sha256": evaluation["patch_sha256"]}, receipt_sha, receipt))
            title = _safe_title(submission["issue_title"])
            cp = _run([
                "gh", "pr", "create", "--repo", submission["repo"], "--head", branch,
                "--base", config["base_branch"], "--title", title, "--body-file", str(body_path),
            ], repo, timeout=180)
            if cp.returncode != 0:
                raise RuntimeError("gh pr create failed: " + cp.stderr[-1000:])
            pr_url = cp.stdout.strip().splitlines()[-1]
            row = store.transition(submission_id, "PR_OPENED", detail={"pr_url": pr_url, "receipt_sha256": receipt_sha})
            return {"submission_id": submission_id, "state": row["state"], "pr_url": pr_url,
                    "receipt": str(receipt_path), "receipt_sha256": receipt_sha}
        finally:
            shutil.rmtree(temp, ignore_errors=True)
    finally:
        store.close()
