#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import statistics
import subprocess
import tarfile
import tempfile
from pathlib import Path

from airlock.runner import run_tournament

SUBSTRATE = "91861c77e4b03ace60df147b0accf94f4351de18"
MODEL = "gpt-5.6-sol"
TRACKS = 4
PLAN_MAX_TURNS = 25
IMPLEMENT_MAX_TURNS = 65
MAX_CHANGED_FILES = 2
MAX_CHANGED_LINES = 120
PROBE_REPEATS = 3
PROBE_TIMEOUT_SECONDS = 30

PLAN_PROMPT = 'Find one small improvement in this repository, but do not change any repository file yet.\n\nStart from something a user or developer can already observe. Valid starting points are:\n- documented behavior or a documented workflow;\n- a public CLI command or public API contract;\n- a public test/check or official benchmark;\n- changelog or git-history evidence of a regression or repeated pain.\n\nDo not start from a code smell or an arbitrary micro-benchmark by itself.\n\nBuild at least three opportunity cards. Each card must contain:\n- public_anchor_type: one of documentation, cli, public_api, public_check, benchmark, changelog, git_history;\n- public_anchor_path: a real repository path that contains the public evidence;\n- public_anchor_contract: a short description of the behavior or workflow that matters;\n- trace_paths: an ordered list of real repository paths from the public anchor to the file you would change;\n- expected_outcome: what gets better at the public surface if the lever works;\n- files: the exact source files you would change, maximum two;\n- outcome_probe: a local command that exercises the public outcome and prints exactly one number, plus direction, unit, and epsilon;\n- regression_risk: the main way the change could break existing behavior.\n\nPick one card and freeze it before implementation. If no card can show a public anchor, a trace to a controllable lever, a reproducible numeric outcome probe, and a <=2-file patch, return no target.\n\nWrite the plan only to:\n$HERMES_HOME/search-001c-plan.json\n\nUse this JSON shape:\n{\n  "schema": "airlock.search-001c.plan.v1",\n  "opportunities": [\n    {\n      "public_anchor_type": "public_check",\n      "public_anchor_path": "path/in/repo.py",\n      "public_anchor_contract": "...",\n      "trace_paths": ["path/in/repo.py", "source/file.py"],\n      "expected_outcome": "...",\n      "files": ["source/file.py"],\n      "outcome_probe": {\n        "command": "python -c \'...\'",\n        "direction": "lower",\n        "unit": "count",\n        "epsilon": 0.0\n      },\n      "regression_risk": "..."\n    }\n  ],\n  "selected_index": 0\n}\n\nDo not edit, create, delete, or rename any repository file in this planning step. The implementation step will only happen if this plan passes an independent pre-code check.'
IMPLEMENT_PROMPT_TEMPLATE = 'Implement exactly the frozen opportunity below.\n\nYou may change only the declared source files. Do not switch targets. Do not edit tests, workflows, Airlock rules, the plan, or grading code. Keep the patch <=2 files and <=120 changed lines.\n\nThe public anchor, trace, expected outcome, and outcome probe were validated before this implementation call. Preserve existing behavior while making the public outcome better. Run the same outcome probe and public checks before finishing.\n\nFROZEN OPPORTUNITY:\n{opportunity_json}\n'

ALLOWED_ANCHORS = {
    "documentation", "cli", "public_api", "public_check",
    "benchmark", "changelog", "git_history"
}

HIDDEN = [
    ".airlock/self-001/evaluator.py",
    ".airlock/self-001/scope_registry.json",
    ".airlock/self-001/preregistration.json",
    ".airlock/self-001/fixtures",
    "experiments/airlock-self-001/README.md",
    "experiments/airlock-self-001/run_self_001.py",
    "experiments/airlock-self-001/fixtures",
]

PROTECTED = [
    ".github/workflows/**",
    ".airlock/**",
    "experiments/airlock-search-001c/**",
    "tests/**",
    "scripts/verify_*",
    "pyproject.toml",
    "CHANGELOG.md",
]

PUBLIC = {
    "schema": "airlock.config.v1",
    "parallelism": 1,
    "providers": {
        "hermes": {
            "command": ["python", ".airlock/checks/hermes_live_001_worker.py", "{prompt}"],
            "pass_env": ["HERMES_HOME"],
            "timeout_seconds": 2700,
        }
    },
    "protected_paths": PROTECTED,
    "baseline": {
        "check_commands": [["python", ".airlock/self-001/protected_checks.py"]],
        "timeout_seconds": 1200,
    },
    "verification": {
        "target_commands": [],
        "static_commands": [],
        "test_commands": [["python", ".airlock/self-001/protected_checks.py"]],
        "timeout_seconds": 1200,
    },
}


def sh(cmd, cwd, *, text=True, env=None):
    return subprocess.run(
        cmd, cwd=cwd, text=text, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )


def fresh_repo(source_repo: Path) -> tuple[Path, Path, str]:
    tmp = Path(tempfile.mkdtemp(prefix="search001c-repo-"))
    repo = tmp / "repo"
    repo.mkdir()
    archive = subprocess.check_output(
        ["git", "archive", "--format=tar", SUBSTRATE], cwd=source_repo
    )
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tf:
        tf.extractall(repo)

    for rel in HIDDEN:
        p = repo / rel
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()

    if any((repo / rel).exists() for rel in HIDDEN):
        raise RuntimeError("hidden evaluation material leaked into worker repo")

    cfg = repo / ".airlock/search-001c-public-config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps(PUBLIC, indent=2) + "\n")

    sh(["git", "init"], repo)
    sh(["git", "config", "user.name", "SEARCH-001C"], repo)
    sh(["git", "config", "user.email", "search001c@invalid.local"], repo)
    sh(["git", "add", "-A"], repo)
    cp = sh(["git", "commit", "-m", "SEARCH-001C worker substrate"], repo)
    if cp.returncode:
        raise RuntimeError(cp.stderr)

    preflight = sh(["python", ".airlock/self-001/protected_checks.py"], repo)
    if preflight.returncode:
        raise RuntimeError("public starting checks are not green")

    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    return tmp, repo, base


def copy_home(seed: Path, track: int, max_turns: int) -> Path:
    home = Path(tempfile.mkdtemp(prefix=f"search001c-home-{track:02d}-"))
    for name in (".env", "config.yaml"):
        src = seed / name
        if not src.is_file():
            raise RuntimeError(f"missing Hermes seed file: {name}")
        shutil.copy2(src, home / name)
    config = (home / "config.yaml").read_text()
    if re.search(r"(?m)^\s*max_turns:\s*\d+\s*$", config):
        config = re.sub(
            r"(?m)^(\s*max_turns:)\s*\d+\s*$",
            rf"\1 {max_turns}",
            config,
            count=1,
        )
    else:
        config += f"\nagent:\n  max_turns: {max_turns}\n"
    (home / "config.yaml").write_text(config)
    return home


def set_turns(home: Path, max_turns: int) -> None:
    config_path = home / "config.yaml"
    config = config_path.read_text()
    config = re.sub(
        r"(?m)^(\s*max_turns:)\s*\d+\s*$",
        rf"\1 {max_turns}",
        config,
        count=1,
    )
    config_path.write_text(config)


def is_protected(path: str) -> bool:
    if path.startswith((".github/", ".airlock/", "tests/", "scripts/verify_")):
        return True
    return path in {"pyproject.toml", "CHANGELOG.md"} or path.startswith("experiments/airlock-search-001c/")


def validate_plan(repo: Path, plan_path: Path) -> tuple[dict | None, str | None]:
    if not plan_path.is_file():
        return None, "MISSING_PLAN"
    try:
        plan = json.loads(plan_path.read_text())
    except Exception:
        return None, "MALFORMED_PLAN"
    if plan.get("schema") != "airlock.search-001c.plan.v1":
        return None, "BAD_PLAN_SCHEMA"
    cards = plan.get("opportunities")
    if not isinstance(cards, list) or len(cards) < 3:
        return None, "TOO_FEW_OPPORTUNITIES"
    selected = plan.get("selected_index")
    if not isinstance(selected, int) or not (0 <= selected < len(cards)):
        return None, "BAD_SELECTED_INDEX"

    card = cards[selected]
    if card.get("public_anchor_type") not in ALLOWED_ANCHORS:
        return None, "BAD_PUBLIC_ANCHOR_TYPE"
    anchor = card.get("public_anchor_path")
    if not isinstance(anchor, str) or not anchor or not (repo / anchor).is_file():
        return None, "PUBLIC_ANCHOR_NOT_FOUND"
    if any(anchor.startswith(prefix) for prefix in (".airlock/self-001/evaluator", ".airlock/self-001/scope_registry")):
        return None, "HIDDEN_ANCHOR_FORBIDDEN"
    if not isinstance(card.get("public_anchor_contract"), str) or not card["public_anchor_contract"].strip():
        return None, "MISSING_PUBLIC_CONTRACT"

    trace = card.get("trace_paths")
    if not isinstance(trace, list) or len(trace) < 1:
        return None, "MISSING_TRACE"
    if trace[0] != anchor:
        return None, "TRACE_MUST_START_AT_ANCHOR"
    if any(not isinstance(p, str) or not (repo / p).is_file() for p in trace):
        return None, "TRACE_PATH_NOT_FOUND"

    declared = card.get("files")
    if not isinstance(declared, list) or not declared or len(declared) > MAX_CHANGED_FILES:
        return None, "DECLARED_SCOPE_TOO_LARGE"
    if any(not isinstance(p, str) or not (repo / p).is_file() for p in declared):
        return None, "DECLARED_FILE_NOT_FOUND"
    if any(is_protected(p) for p in declared):
        return None, "DECLARED_PROTECTED_FILE"
    if trace[-1] not in declared:
        return None, "TRACE_MUST_END_AT_DECLARED_LEVER"

    if not isinstance(card.get("expected_outcome"), str) or not card["expected_outcome"].strip():
        return None, "MISSING_EXPECTED_OUTCOME"
    if not isinstance(card.get("regression_risk"), str) or not card["regression_risk"].strip():
        return None, "MISSING_REGRESSION_RISK"

    probe = card.get("outcome_probe")
    if not isinstance(probe, dict):
        return None, "MISSING_OUTCOME_PROBE"
    if not isinstance(probe.get("command"), str) or not probe["command"].strip():
        return None, "MISSING_OUTCOME_PROBE_COMMAND"
    if probe.get("direction") not in ("lower", "higher"):
        return None, "BAD_PROBE_DIRECTION"
    try:
        epsilon = float(probe.get("epsilon", 0.0))
    except (TypeError, ValueError):
        return None, "BAD_EPSILON"
    if epsilon < 0:
        return None, "BAD_EPSILON"

    return card, None


def probe_env() -> dict[str, str]:
    env = {}
    for key in ("PATH", "LANG", "LC_ALL", "PYTHONPATH", "PYTHONHOME"):
        if key in os.environ:
            env[key] = os.environ[key]
    env["HOME"] = tempfile.mkdtemp(prefix="search001c-probe-home-")
    return env


def numeric_probe(repo: Path, command: str) -> dict:
    env = probe_env()
    values = []
    try:
        for _ in range(PROBE_REPEATS):
            cp = subprocess.run(
                command, cwd=repo, env=env, text=True, shell=True,
                executable="/bin/bash", stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=PROBE_TIMEOUT_SECONDS,
                check=False,
            )
            if cp.returncode:
                return {
                    "status": "FAIL", "reason": "PROBE_COMMAND_FAILED",
                    "exit_code": cp.returncode, "stderr_tail": cp.stderr[-800:]
                }
            raw = cp.stdout.strip()
            try:
                values.append(float(raw))
            except ValueError:
                return {"status": "FAIL", "reason": "PROBE_NOT_SINGLE_NUMBER", "stdout_tail": raw[-800:]}
        return {"status": "PASS", "values": values, "median": statistics.median(values)}
    finally:
        shutil.rmtree(env["HOME"], ignore_errors=True)


def diff_stats(repo: Path, base: str, commit: str) -> dict:
    cp = sh(["git", "diff", "--numstat", f"{base}..{commit}", "--", "."], repo)
    files = lines = 0
    if cp.returncode == 0:
        for line in cp.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            files += 1
            try:
                lines += int(parts[0]) + int(parts[1])
            except ValueError:
                lines += MAX_CHANGED_LINES + 1
    return {"changed_files": files, "changed_lines": lines}


def patch_text(repo: Path, base: str, commit: str) -> str:
    cp = sh(["git", "diff", "--binary", "--full-index", f"{base}..{commit}", "--", "."], repo)
    return cp.stdout if cp.returncode == 0 else ""


def outcome_delta(before: float, after: float, direction: str) -> float:
    return before - after if direction == "lower" else after - before


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-repo", default=".")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    source = Path(args.source_repo).resolve()
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    seed_home = Path(os.environ["HERMES_HOME"]).resolve()

    if subprocess.check_output(["git", "rev-parse", SUBSTRATE], cwd=source, text=True).strip() != SUBSTRATE:
        raise RuntimeError("pinned substrate unavailable")

    tracks = []
    original_home = os.environ.get("HERMES_HOME")
    try:
        for track in range(1, TRACKS + 1):
            home = copy_home(seed_home, track, PLAN_MAX_TURNS)
            plan_tmp = impl_tmp = None
            try:
                os.environ["HERMES_HOME"] = str(home)

                # Stage 1: read-only discovery. Implementation is impossible unless
                # this stage leaves the repository unchanged and passes the plan gate.
                plan_tmp, plan_repo, plan_base = fresh_repo(source)
                plan_report = run_tournament(
                    plan_repo, PLAN_PROMPT, agents=1, models=["hermes"],
                    budget=None, open_pr=False,
                    config_path=plan_repo / ".airlock/search-001c-public-config.json",
                )
                plan_row = (plan_report.get("candidates") or [{}])[0]
                plan_changed = list(plan_row.get("changed_paths") or [])
                plan_path = home / "search-001c-plan.json"

                if plan_changed:
                    tracks.append({
                        "track_id": f"track-{track:02d}",
                        "status": "REJECT",
                        "reason": "PRECODE_MUTATION",
                        "plan_changed_paths": plan_changed,
                    })
                    continue
                if (plan_row.get("agent_execution") or {}).get("exit_code") != 0:
                    tracks.append({
                        "track_id": f"track-{track:02d}",
                        "status": "REJECT",
                        "reason": "PLAN_WORKER_FAILED",
                        "agent_execution": plan_row.get("agent_execution"),
                    })
                    continue

                card, plan_error = validate_plan(plan_repo, plan_path)
                if card is None:
                    tracks.append({
                        "track_id": f"track-{track:02d}",
                        "status": "REJECT",
                        "reason": plan_error,
                    })
                    continue

                # Pre-code anchor check: the public outcome must be measurable on
                # untouched code before an implementation call is allowed.
                baseline_precode = numeric_probe(plan_repo, card["outcome_probe"]["command"])
                if baseline_precode.get("status") != "PASS":
                    tracks.append({
                        "track_id": f"track-{track:02d}",
                        "status": "REJECT",
                        "reason": "PUBLIC_OUTCOME_NOT_MEASURABLE",
                        "baseline_probe": baseline_precode,
                    })
                    continue

                # Stage 2: only now may Hermes write code.
                set_turns(home, IMPLEMENT_MAX_TURNS)
                impl_tmp, impl_repo, impl_base = fresh_repo(source)
                impl_prompt = IMPLEMENT_PROMPT_TEMPLATE.format(
                    opportunity_json=json.dumps(card, indent=2, sort_keys=True)
                )
                impl_report = run_tournament(
                    impl_repo, impl_prompt, agents=1, models=["hermes"],
                    budget=None, open_pr=False,
                    config_path=impl_repo / ".airlock/search-001c-public-config.json",
                )
                impl_row = (impl_report.get("candidates") or [{}])[0]
                commit = impl_row.get("commit")
                changed = list(impl_row.get("changed_paths") or [])
                declared = set(card["files"])

                if impl_row.get("disposition") != "SURVIVED" or not isinstance(commit, str) or commit == impl_base:
                    tracks.append({
                        "track_id": f"track-{track:02d}",
                        "status": "REJECT",
                        "reason": impl_row.get("reason") or "NO_PUBLIC_SURVIVOR",
                        "public_disposition": impl_row.get("disposition"),
                    })
                    continue
                if not set(changed).issubset(declared):
                    tracks.append({
                        "track_id": f"track-{track:02d}",
                        "status": "REJECT",
                        "reason": "TARGET_SWITCH_OR_SCOPE_ESCAPE",
                        "declared_files": sorted(declared),
                        "changed_paths": changed,
                    })
                    continue

                stats = diff_stats(impl_repo, impl_base, commit)
                if stats["changed_files"] > MAX_CHANGED_FILES:
                    tracks.append({
                        "track_id": f"track-{track:02d}",
                        "status": "REJECT", "reason": "CHANGED_FILE_LIMIT", "diff": stats
                    })
                    continue
                if stats["changed_lines"] > MAX_CHANGED_LINES:
                    tracks.append({
                        "track_id": f"track-{track:02d}",
                        "status": "REJECT", "reason": "CHANGED_LINE_LIMIT", "diff": stats
                    })
                    continue

                base_wt = Path(tempfile.mkdtemp(prefix="search001c-base-"))
                cand_wt = Path(tempfile.mkdtemp(prefix="search001c-cand-"))
                base_wt.rmdir(); cand_wt.rmdir()
                try:
                    if sh(["git", "worktree", "add", "--detach", str(base_wt), impl_base], impl_repo).returncode:
                        raise RuntimeError("failed to create baseline probe worktree")
                    if sh(["git", "worktree", "add", "--detach", str(cand_wt), commit], impl_repo).returncode:
                        raise RuntimeError("failed to create candidate probe worktree")
                    before = numeric_probe(base_wt, card["outcome_probe"]["command"])
                    after = numeric_probe(cand_wt, card["outcome_probe"]["command"])
                finally:
                    sh(["git", "worktree", "remove", "--force", str(base_wt)], impl_repo)
                    sh(["git", "worktree", "remove", "--force", str(cand_wt)], impl_repo)
                    shutil.rmtree(base_wt, ignore_errors=True)
                    shutil.rmtree(cand_wt, ignore_errors=True)

                if before.get("status") != "PASS" or after.get("status") != "PASS":
                    tracks.append({
                        "track_id": f"track-{track:02d}",
                        "status": "REJECT",
                        "reason": "OUTCOME_PROBE_DID_NOT_REPRODUCE",
                        "baseline_probe": before, "candidate_probe": after,
                    })
                    continue

                delta = outcome_delta(
                    float(before["median"]), float(after["median"]),
                    card["outcome_probe"]["direction"],
                )
                epsilon = float(card["outcome_probe"].get("epsilon", 0.0))
                if delta <= epsilon:
                    tracks.append({
                        "track_id": f"track-{track:02d}",
                        "status": "REJECT", "reason": "NO_PUBLIC_OUTCOME_GAIN",
                        "delta": delta, "epsilon": epsilon,
                    })
                    continue

                patch = patch_text(impl_repo, impl_base, commit)
                tracks.append({
                    "track_id": f"track-{track:02d}",
                    "status": "READY_FOR_HIDDEN_EVALUATION",
                    "plan": card,
                    "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                    "diff": stats,
                    "changed_paths": changed,
                    "baseline_probe": before,
                    "candidate_probe": after,
                    "outcome_delta": delta,
                    "patch": patch,
                    "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
                    "agent_execution": impl_row.get("agent_execution"),
                    "agent_report": impl_row.get("agent_report", {}),
                })
            finally:
                if plan_tmp is not None:
                    shutil.rmtree(plan_tmp, ignore_errors=True)
                if impl_tmp is not None:
                    shutil.rmtree(impl_tmp, ignore_errors=True)
                shutil.rmtree(home, ignore_errors=True)
    finally:
        if original_home is not None:
            os.environ["HERMES_HOME"] = original_home

    payload = {
        "schema": "airlock.search-001c.bundle.v1",
        "experiment": "AIRLOCK-SEARCH-001C",
        "strategy": "outcome_trace",
        "substrate_commit": SUBSTRATE,
        "model": MODEL,
        "tracks": TRACKS,
        "plan_max_turns_per_track": PLAN_MAX_TURNS,
        "implement_max_turns_per_track": IMPLEMENT_MAX_TURNS,
        "total_max_turns_per_track": PLAN_MAX_TURNS + IMPLEMENT_MAX_TURNS,
        "max_changed_files": MAX_CHANGED_FILES,
        "max_changed_lines": MAX_CHANGED_LINES,
        "probe_repeats": PROBE_REPEATS,
        "hidden_paths_absent": HIDDEN,
        "tracks_result": tracks,
        "claim_boundary": (
            "Planning and implementation are separate Hermes calls. Implementation is never contacted "
            "until the public anchor/trace/scope/outcome plan passes a read-only pre-code gate. "
            "Native worker execution is not a strong filesystem sandbox."
        ),
    }
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "ready_for_hidden_evaluation": sum(
            r.get("status") == "READY_FOR_HIDDEN_EVALUATION" for r in tracks
        ),
        "tracks": len(tracks),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
