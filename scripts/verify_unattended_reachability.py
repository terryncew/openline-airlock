#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from airlock import unattended


GOOD_OLD = '    print(\'  airlock swarm "fix issue #417"\')\n'
GOOD_NEW = '    print("  airlock solve 417")\n'
BAD_NEW = '    print(\'  airlock solve "fix issue #417"\')\n'


def run(argv: list[str], cwd: Path, *, timeout: int | None = None, env: dict[str, str] | None = None) -> dict:
    started = time.monotonic()
    try:
        cp = subprocess.run(
            argv,
            cwd=cwd,
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


def git(repo: Path, *args: str) -> str:
    cp = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if cp.returncode:
        raise RuntimeError(cp.stderr.strip() or f"git {' '.join(args)} failed")
    return cp.stdout.strip()


def copy_tracked_repo(source: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    names = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=source,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout.split(b"\0")
    for raw in names:
        if not raw:
            continue
        rel = Path(raw.decode())
        src = source / rel
        dst = dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            dst.symlink_to(os.readlink(src))
        else:
            shutil.copy2(src, dst)


def init_fixture(source: Path) -> tuple[Path, str]:
    repo = Path(tempfile.mkdtemp(prefix="airlock-reachability-repo-"))
    copy_tracked_repo(source, repo)

    # This proof models the issue #23 starting state under the current gate.
    # Once the real fix is present in the branch being tested, reconstruct only
    # the pre-fix source line in the isolated fixture so the good/bad arms remain
    # meaningful instead of failing because the bug has already been fixed.
    cli = repo / "src" / "airlock" / "cli.py"
    cli_text = cli.read_text(encoding="utf-8")
    has_old = GOOD_OLD in cli_text
    has_new = GOOD_NEW in cli_text
    if has_old and has_new:
        raise RuntimeError("issue #23 fixture is ambiguous: both old and fixed source lines are present")
    if has_new:
        cli.write_text(cli_text.replace(GOOD_NEW, GOOD_OLD, 1), encoding="utf-8")
    elif not has_old:
        raise RuntimeError("issue #23 fixture source line is no longer recognizable")

    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Airlock reachability")
    git(repo, "config", "user.email", "airlock-reachability@example.invalid")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "frozen gate")
    return repo, git(repo, "rev-parse", "HEAD")


def make_artifact(repo: Path, base: str, candidate_id: str, replacement: str) -> Path:
    git(repo, "reset", "--hard", base)
    cli = repo / "src" / "airlock" / "cli.py"
    text = cli.read_text(encoding="utf-8")
    if GOOD_OLD not in text:
        raise RuntimeError("known issue #23 source line is no longer present")
    cli.write_text(text.replace(GOOD_OLD, replacement, 1), encoding="utf-8")

    scratch = repo / ".airlock-unattended"
    scratch.mkdir(exist_ok=True)
    prompt = scratch / "prompt.txt"
    prompt.write_text("reachability proof for issue #23", encoding="utf-8")
    final = scratch / "final.txt"
    final.write_text("fixture candidate", encoding="utf-8")

    out = Path(tempfile.mkdtemp(prefix=f"airlock-reachability-{candidate_id}-"))
    unattended.capture_candidate(
        repo,
        base=base,
        candidate_id=candidate_id,
        issue_number=23,
        issue_url="https://github.com/terryncew/openline-airlock/issues/23",
        prompt_path=prompt,
        expected_prompt_sha256=unattended.sha256_file(prompt),
        expected_git_config_sha256=unattended.sha256_file(repo / ".git" / "config"),
        final_message_path=final,
        agent_outcome="success",
        out_dir=out,
    )
    git(repo, "reset", "--hard", base)
    return out


def candidate_set(repo: Path, base: str, replacement: str) -> Path:
    root = Path(tempfile.mkdtemp(prefix="airlock-reachability-candidates-"))
    for candidate_id in ("01", "02", "03", "04"):
        artifact = make_artifact(repo, base, candidate_id, replacement)
        target = root / f"airlock-candidate-{candidate_id}"
        target.mkdir()
        for name in ("candidate.json", "candidate.patch"):
            shutil.copy2(artifact / name, target / name)
        shutil.rmtree(artifact, ignore_errors=True)
    return root


def local_runner(
    worktree: Path,
    image: str,
    argv: list[str],
    timeout: int,
    policy: dict,
) -> dict:
    del image, policy
    env = dict(os.environ)
    candidate_path = os.pathsep.join([str(worktree / "src"), str(worktree)])
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = candidate_path + (os.pathsep + existing if existing else "")
    env["GITHUB_TOKEN"] = ""
    env["GH_TOKEN"] = ""
    env["GIT_TERMINAL_PROMPT"] = "0"
    return run(list(argv), worktree, timeout=timeout, env=env)


def evaluate_arm(repo: Path, base: str, replacement: str, name: str) -> dict:
    candidates = candidate_set(repo, base, replacement)
    out = Path(tempfile.mkdtemp(prefix=f"airlock-reachability-{name}-out-"))
    try:
        return unattended.evaluate_candidates(
            repo,
            base=base,
            issue_number=23,
            candidates_root=candidates,
            out_dir=out,
            workflow_run_id=f"reachability-{name}",
            workflow_run_attempt="1",
            command_runner=local_runner,
        )
    finally:
        shutil.rmtree(candidates, ignore_errors=True)
        shutil.rmtree(out, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=Path("."))
    ap.add_argument("--out", type=Path, default=Path("airlock-unattended-reachability.json"))
    args = ap.parse_args()

    source = args.repo.resolve()
    repo, base = init_fixture(source)
    try:
        good = evaluate_arm(repo, base, GOOD_NEW, "good")
        bad = evaluate_arm(repo, base, BAD_NEW, "bad")
    finally:
        shutil.rmtree(repo, ignore_errors=True)

    errors: list[str] = []
    if good.get("decision") != "READY_FOR_REVIEW":
        errors.append(f"good patch decision={good.get('decision')!r}")
    if good.get("survivor_count") != 4:
        errors.append(f"good patch survivor_count={good.get('survivor_count')!r}")
    if good.get("unique_survivor_count") != 1:
        errors.append(f"good patch unique_survivor_count={good.get('unique_survivor_count')!r}")
    if any(row.get("disposition") != "SURVIVED" for row in good.get("candidates", [])):
        errors.append("at least one known-good candidate did not survive")

    if bad.get("decision") != "NO_PATCH_READY":
        errors.append(f"bad patch decision={bad.get('decision')!r}")
    if bad.get("survivor_count") != 0:
        errors.append(f"bad patch survivor_count={bad.get('survivor_count')!r}")
    bad_reasons = [row.get("reason") for row in bad.get("candidates", [])]
    if bad_reasons != ["TARGET_FAILED"] * 4:
        errors.append(f"bad patch reasons={bad_reasons!r}")

    report = {
        "schema": "airlock.unattended.reachability.v1",
        "issue_number": 23,
        "known_good": {
            "edit": 'airlock swarm "fix issue #417" -> airlock solve 417',
            "decision": good.get("decision"),
            "survivor_count": good.get("survivor_count"),
            "unique_survivor_count": good.get("unique_survivor_count"),
            "candidate_dispositions": [row.get("disposition") for row in good.get("candidates", [])],
        },
        "known_bad": {
            "edit": 'airlock swarm "fix issue #417" -> airlock solve "fix issue #417"',
            "decision": bad.get("decision"),
            "survivor_count": bad.get("survivor_count"),
            "candidate_reasons": bad_reasons,
        },
        "claim": "KNOWN_GOOD_REACHABLE_AND_KNOWN_BAD_REJECTED" if not errors else "REACHABILITY_PROOF_FAILED",
        "errors": errors,
    }
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if errors:
        print("Airlock unattended reachability: FAIL", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("Airlock unattended reachability: PASS")
    print("- known-good issue #23 edit: READY_FOR_REVIEW (4 survivors, 1 unique patch)")
    print("- wrong solve argument shape: NO_PATCH_READY (4 TARGET_FAILED)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
