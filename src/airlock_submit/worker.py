from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from airlock.sieve import sufficiency_check
from airlock.util import compact_result, matches_any, sha256_bytes, sha256_file, write_json

from .policy import load_submit_config, protected_touches
from .seal import file_binding, seal
from .store import Store


def _run(argv: list[str], cwd: Path, *, timeout: int | None = None, text: bool = True):
    return subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=text, timeout=timeout, check=False)


def _git(repo: Path, *args: str, timeout: int = 120):
    cp = _run(["git", "-c", "core.hooksPath=/dev/null", *args], repo, timeout=timeout)
    if cp.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {cp.stderr[-1000:]}")
    return cp.stdout


def _parse_name_status(raw: bytes) -> list[str]:
    parts = raw.split(b"\0")
    if parts and parts[-1] == b"":
        parts.pop()
    paths: list[str] = []
    i = 0
    while i < len(parts):
        status = parts[i].decode("ascii", errors="strict")
        i += 1
        if not status:
            raise RuntimeError("empty git diff status")
        count = 2 if status[0] in {"R", "C"} else 1
        if i + count > len(parts):
            raise RuntimeError("malformed NUL-delimited git diff")
        for _ in range(count):
            paths.append(parts[i].decode("utf-8", errors="strict"))
            i += 1
    return paths


def _changed_paths(repo: Path, base: str, candidate: str) -> list[str]:
    cp = _run([
        "git", "-c", "core.hooksPath=/dev/null", "diff", "--name-status", "-z",
        "--find-renames", "--find-copies", base, candidate,
    ], repo, text=False, timeout=120)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.decode(errors="replace")[-1000:])
    return _parse_name_status(cp.stdout)


def _tracked(repo: Path, commit: str) -> list[str]:
    cp = _run(["git", "ls-tree", "-r", "--name-only", "-z", commit], repo, text=False, timeout=120)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.decode(errors="replace")[-1000:])
    return [p.decode("utf-8") for p in cp.stdout.split(b"\0") if p]


def _base_airlock_config(repo: Path, base: str) -> dict:
    text = _git(repo, "show", f"{base}:.airlock/config.json")
    obj = json.loads(text)
    if obj.get("schema") != "airlock.config.v1":
        raise RuntimeError("base .airlock/config.json is missing or unsupported")
    return obj


def _docker_result(workspace: Path, image: str, argv: list[str], config: dict, timeout: int) -> dict:
    if not shutil.which("docker"):
        raise RuntimeError("public Airlock evaluation requires Docker")
    uid = str(os.getuid()) if hasattr(os, "getuid") else "65532"
    gid = str(os.getgid()) if hasattr(os, "getgid") else "65532"
    cmd = [
        "docker", "run", "--rm", "--pull", "never", "--network", "none",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--read-only", "--pids-limit", str(config["pids_limit"]),
        "--memory", str(config["memory"]), "--cpus", str(config["cpus"]),
        "--user", f"{uid}:{gid}", "--workdir", "/workspace",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=512m",
        "-e", "HOME=/tmp/airlock-home", "-e", "CI=1",
        "-v", f"{workspace}:/workspace:rw", "--entrypoint", "", image,
        *[str(x) for x in argv],
    ]
    started = time.monotonic()
    try:
        cp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            timeout=timeout, check=False, env={"PATH": os.environ.get("PATH", "")})
        raw = {"argv": list(argv), "exit_code": cp.returncode, "stdout": cp.stdout,
               "stderr": cp.stderr, "duration_seconds": round(time.monotonic()-started, 6), "timed_out": False}
    except subprocess.TimeoutExpired as exc:
        raw = {"argv": list(argv), "exit_code": 124, "stdout": exc.stdout or "", "stderr": exc.stderr or "",
               "duration_seconds": round(time.monotonic()-started, 6), "timed_out": True}
    return compact_result(raw)


def _run_group(workspace: Path, image: str, commands: list[list[str]], config: dict, *, kind: str) -> dict:
    records = []
    for argv in commands:
        before = _git(workspace, "status", "--porcelain", "--untracked-files=no")
        record = _docker_result(workspace, image, argv, config, int(config["evaluation_timeout_seconds"]))
        record["kind"] = kind
        after = _git(workspace, "status", "--porcelain", "--untracked-files=no")
        record["tracked_side_effect"] = bool(before.strip() or after.strip())
        records.append(record)
        if record["tracked_side_effect"]:
            return {"rule": kind, "status": "FAIL", "reason": "EVALUATOR_SIDE_EFFECT", "commands": records}
        if record["exit_code"] != 0 or record["timed_out"]:
            return {"rule": kind, "status": "FAIL", "commands": records}
    return {"rule": kind, "status": "PASS", "commands": records}


def evaluate_submission(submission: dict, *, config: dict, artifact_dir: Path, evaluation_key: str) -> dict:
    artifact_dir.mkdir(parents=True, exist_ok=False)
    temp = Path(tempfile.mkdtemp(prefix=f"airlock-submit-{submission['id']}-"))
    repo = temp / "repo"
    workspace = temp / "workspace"
    try:
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "remote", "add", "target", f"https://github.com/{submission['repo']}.git")
        _git(repo, "fetch", "--no-tags", "target", submission["base_sha"])
        _git(repo, "remote", "add", "source", f"https://github.com/{submission['source_repo']}.git")
        _git(repo, "fetch", "--no-tags", "source", submission["source_sha"], timeout=300)
        ancestor = _run(["git", "merge-base", "--is-ancestor", submission["base_sha"], submission["source_sha"]], repo)
        if ancestor.returncode != 0:
            return {"decision": "BLOCKED", "reason": "BASE_NOT_ANCESTOR"}

        airlock_config = _base_airlock_config(repo, submission["base_sha"])
        protected = list(airlock_config.get("protected_paths", []))
        changed = _changed_paths(repo, submission["base_sha"], submission["source_sha"])
        touched = protected_touches(changed, protected)
        if touched:
            return {"decision": "BLOCKED", "reason": "PROTECTED_FILES_CHANGED", "touched": touched}
        if len(set(changed)) > int(config["max_patch_files"]):
            return {"decision": "BLOCKED", "reason": "PATCH_FILE_LIMIT", "changed_file_count": len(set(changed))}

        patch = artifact_dir / "candidate.patch"
        cp = _run(["git", "diff", "--binary", "--full-index", submission["base_sha"], submission["source_sha"]], repo, text=False, timeout=120)
        if cp.returncode != 0:
            raise RuntimeError(cp.stderr.decode(errors="replace")[-1000:])
        patch.write_bytes(cp.stdout)
        if patch.stat().st_size == 0:
            return {"decision": "BLOCKED", "reason": "NO_PATCH"}
        if patch.stat().st_size > int(config["max_patch_bytes"]):
            return {"decision": "BLOCKED", "reason": "PATCH_SIZE_LIMIT", "patch_bytes": patch.stat().st_size}

        _git(repo, "worktree", "add", "--detach", str(workspace), submission["base_sha"])
        apply = _run(["git", "apply", "--index", "--whitespace=nowarn", str(patch)], workspace, timeout=120)
        if apply.returncode != 0:
            return {"decision": "BLOCKED", "reason": "PATCH_APPLY_FAILED", "stderr_tail": apply.stderr[-1000:]}
        expected_tree = _git(workspace, "write-tree").strip()

        verification = airlock_config.get("verification", {})
        checks = []
        for kind, commands in (
            ("target", verification.get("target_commands", [])),
            ("static", verification.get("static_commands", [])),
            ("regression", verification.get("test_commands", [])),
        ):
            group = _run_group(workspace, config["container_image"], commands, config, kind=kind)
            checks.append(group)
            if group["status"] != "PASS":
                reason = group.get("reason") or ("TARGET_FAILED" if kind == "target" else "LINT_OR_TYPECHECK" if kind == "static" else "TESTS_FAILED")
                return {"decision": "BLOCKED", "reason": reason, "checks": checks}

        test_patterns = [p for p in protected if p.startswith(("tests/", "test/", "spec/", "__tests__/"))]
        test_files = [p for p in _tracked(repo, submission["base_sha"]) if matches_any(p, test_patterns)]
        sufficient = sufficiency_check(repo, submission["base_sha"], sorted(set(changed)), test_files,
                                       verification.get("target_commands", []))
        checks.append(sufficient)
        decision = "SURVIVED" if sufficient["status"] == "PASS" else "NEEDS_EVIDENCE"
        reason = "ALL_CONFIGURED_CHECKS_PASSED" if decision == "SURVIVED" else sufficient.get("basis", "INSUFFICIENT_EVIDENCE")

        evaluation = {
            "schema": "airlock.submit.evaluation.v1",
            "submission_id": submission["id"],
            "repo": submission["repo"],
            "issue_number": submission["issue_number"],
            "submitter": submission["submitter"],
            "source_repo": submission["source_repo"],
            "source_sha": submission["source_sha"],
            "base_sha": submission["base_sha"],
            "decision": decision,
            "reason": reason,
            "changed_paths": sorted(set(changed)),
            "protected_paths": protected,
            "protected_touches": [],
            "airlock_config_sha256": sha256_bytes(json.dumps(airlock_config, sort_keys=True, separators=(",", ":")).encode()),
            "container_image": config["container_image"],
            "checks": checks,
            "expected_tree": expected_tree,
        }
        evaluation_path = artifact_dir / "evaluation.json"
        write_json(evaluation_path, evaluation)
        bundle_payload = {
            "schema": "airlock.submit.bundle.v1",
            "submission_id": submission["id"],
            "evaluation": file_binding(evaluation_path),
            "patch": file_binding(patch),
            "expected_tree": expected_tree,
        }
        write_json(artifact_dir / "bundle.json", seal(bundle_payload, evaluation_key))
        return evaluation
    finally:
        try:
            if workspace.exists():
                _run(["git", "worktree", "remove", "--force", str(workspace)], repo, timeout=30)
        except Exception:
            pass
        shutil.rmtree(temp, ignore_errors=True)


def process_one(*, config_path: Path, db_path: Path, data_dir: Path) -> dict | None:
    config = load_submit_config(config_path)
    store = Store(db_path)
    try:
        row = store.next_queued()
        if not row:
            return None
        store.transition(row["id"], "EVALUATING")
        artifact_dir = Path(data_dir) / "artifacts" / row["id"]
        try:
            result = evaluate_submission(row, config=config, artifact_dir=artifact_dir,
                                         evaluation_key=os.environ.get("AIRLOCK_EVALUATION_KEY", ""))
            decision = result["decision"]
            state = decision if decision in {"BLOCKED", "NEEDS_EVIDENCE", "SURVIVED"} else "ERROR"
            return store.transition(row["id"], state, artifact_dir=str(artifact_dir), detail={"evaluation": result})
        except Exception as exc:
            return store.transition(row["id"], "ERROR", detail={"worker_error": str(exc)})
    finally:
        store.close()
