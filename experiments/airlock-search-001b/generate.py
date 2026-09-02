#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import statistics
import subprocess
import tarfile
import tempfile
from pathlib import Path

from airlock.runner import run_tournament

SUBSTRATE = "91861c77e4b03ace60df147b0accf94f4351de18"
MODEL = "gpt-5.6-sol"
CANDIDATES = 4
MAX_CHANGED_FILES = 2
MAX_CHANGED_LINES = 120
PROBE_REPEATS = 3
PROBE_TIMEOUT_SECONDS = 30

PROMPT = 'Improve this repository, but measure before you patch.\n\nYour job is to find a small change that fixes a real, observable problem instead of an attractive-looking code smell.\n\nBefore changing any code:\n\n1. Inspect the repo and write down at least three concrete opportunities.\n2. For each opportunity, identify:\n   - the user or engineering problem,\n   - a local command that produces a numeric baseline measurement,\n   - the exact lever you would change,\n   - the files you expect to touch,\n   - the main regression risk.\n3. Ignore ideas that need more than two changed files or a broad rewrite.\n4. Pick one opportunity only after you have run its baseline probe and seen a reproducible non-zero deficit.\n5. Record your discovery dossier at:\n   $HERMES_HOME/search-001b-$AIRLOCK_CANDIDATE_ID.json\n\nThe JSON file must use this shape:\n{\n  "schema": "airlock.search-001b.probe.v1",\n  "candidate_id": "<AIRLOCK_CANDIDATE_ID>",\n  "opportunities": [\n    {\n      "problem": "...",\n      "probe_command": "...",\n      "baseline_observation": "...",\n      "lever": "...",\n      "files": ["path/to/file.py"],\n      "regression_risk": "..."\n    }\n  ],\n  "selected_index": 0,\n  "probe": {\n    "command": "<local command that prints one numeric value>",\n    "direction": "lower",\n    "unit": "seconds",\n    "epsilon": 0.0\n  }\n}\n\nProbe rules:\n- The probe must be local, non-destructive, repeatable, and print exactly one numeric value.\n- It must measure behavior, cost, latency, count, size, or another observable property of the running code. Do not make a probe whose only purpose is to inspect whether your patch text exists.\n- Use "lower" when smaller is better and "higher" when larger is better.\n- Do not edit tests, workflows, Airlock rules, or the hidden grading surface.\n- Do not switch to a different problem after you start implementing.\n\nAfter you patch:\n- run the same probe again;\n- keep the patch only if the same command shows a clear improvement larger than epsilon;\n- keep public checks green;\n- stay within two changed files and 120 changed lines.\n\nAirlock will independently rerun your probe on both the untouched baseline and your candidate. If your measurement does not reproduce, your candidate is discarded before hidden evaluation.\n\nThe independent evaluator remains the judge. Your job is only to find a better target and build the smallest useful fix.'

HIDDEN = [
    ".airlock/self-001/evaluator.py",
    ".airlock/self-001/scope_registry.json",
    ".airlock/self-001/preregistration.json",
    ".airlock/self-001/fixtures",
    "experiments/airlock-self-001/README.md",
    "experiments/airlock-self-001/run_self_001.py",
    "experiments/airlock-self-001/fixtures",
]

PUBLIC = {
    "schema": "airlock.config.v1",
    "parallelism": 4,
    "providers": {
        "hermes": {
            "command": ["python", ".airlock/checks/hermes_live_001_worker.py", "{prompt}"],
            "pass_env": ["HERMES_HOME"],
            "timeout_seconds": 2700,
        }
    },
    "protected_paths": [
        ".github/workflows/**",
        ".airlock/**",
        "experiments/airlock-search-001b/**",
        "tests/**",
        "scripts/verify_*",
        "pyproject.toml",
        "CHANGELOG.md",
    ],
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


def sh(cmd, cwd, *, env=None, text=True):
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def safe_env() -> dict[str, str]:
    keep = {}
    for key in ("PATH", "LANG", "LC_ALL", "PYTHONPATH", "PYTHONHOME"):
        if key in os.environ:
            keep[key] = os.environ[key]
    keep["HOME"] = tempfile.mkdtemp(prefix="search001b-probe-home-")
    return keep


def numeric_probe(repo: Path, command: str) -> dict:
    values = []
    env = safe_env()
    try:
        for _ in range(PROBE_REPEATS):
            cp = subprocess.run(
                command,
                cwd=repo,
                env=env,
                text=True,
                shell=True,
                executable="/bin/bash",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=PROBE_TIMEOUT_SECONDS,
                check=False,
            )
            if cp.returncode != 0:
                return {
                    "status": "FAIL",
                    "reason": "PROBE_COMMAND_FAILED",
                    "exit_code": cp.returncode,
                    "stderr_tail": cp.stderr[-800:],
                }
            raw = cp.stdout.strip()
            try:
                value = float(raw)
            except ValueError:
                return {
                    "status": "FAIL",
                    "reason": "PROBE_NOT_SINGLE_NUMBER",
                    "stdout_tail": raw[-800:],
                }
            values.append(value)
        return {
            "status": "PASS",
            "values": values,
            "median": statistics.median(values),
        }
    finally:
        shutil.rmtree(env["HOME"], ignore_errors=True)


def diff_stats(repo: Path, base: str, commit: str) -> dict:
    cp = sh(["git", "diff", "--numstat", f"{base}..{commit}", "--", "."], repo)
    changed_files = 0
    changed_lines = 0
    if cp.returncode == 0:
        for line in cp.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            changed_files += 1
            try:
                changed_lines += int(parts[0]) + int(parts[1])
            except ValueError:
                changed_lines += MAX_CHANGED_LINES + 1
    return {"changed_files": changed_files, "changed_lines": changed_lines}


def add_worktree(repo: Path, commit: str, prefix: str) -> Path:
    path = Path(tempfile.mkdtemp(prefix=prefix))
    path.rmdir()
    cp = sh(["git", "worktree", "add", "--detach", str(path), commit], repo)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr)
    return path


def remove_worktree(repo: Path, path: Path) -> None:
    sh(["git", "worktree", "remove", "--force", str(path)], repo)
    shutil.rmtree(path, ignore_errors=True)


def validate_dossier(path: Path, candidate_id: str) -> tuple[dict | None, str | None]:
    if not path.is_file():
        return None, "MISSING_PROBE_DOSSIER"
    try:
        dossier = json.loads(path.read_text())
    except Exception:
        return None, "MALFORMED_PROBE_DOSSIER"
    if dossier.get("schema") != "airlock.search-001b.probe.v1":
        return None, "BAD_PROBE_SCHEMA"
    if dossier.get("candidate_id") != candidate_id:
        return None, "CANDIDATE_ID_MISMATCH"
    opportunities = dossier.get("opportunities")
    if not isinstance(opportunities, list) or len(opportunities) < 3:
        return None, "TOO_FEW_OPPORTUNITIES"
    selected = dossier.get("selected_index")
    if not isinstance(selected, int) or selected < 0 or selected >= len(opportunities):
        return None, "BAD_SELECTED_INDEX"
    selected_row = opportunities[selected]
    files = selected_row.get("files")
    if not isinstance(files, list) or not files or len(files) > MAX_CHANGED_FILES:
        return None, "DECLARED_SCOPE_TOO_LARGE"
    probe = dossier.get("probe")
    if not isinstance(probe, dict):
        return None, "MISSING_PROBE"
    if not isinstance(probe.get("command"), str) or not probe["command"].strip():
        return None, "MISSING_PROBE_COMMAND"
    if probe.get("direction") not in ("lower", "higher"):
        return None, "BAD_PROBE_DIRECTION"
    try:
        epsilon = float(probe.get("epsilon", 0.0))
    except (TypeError, ValueError):
        return None, "BAD_EPSILON"
    if epsilon < 0:
        return None, "BAD_EPSILON"
    return dossier, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-repo", default=".")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    src = Path(args.source_repo).resolve()
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    if subprocess.check_output(["git", "rev-parse", SUBSTRATE], cwd=src, text=True).strip() != SUBSTRATE:
        raise RuntimeError("pinned substrate unavailable")

    tmp = Path(tempfile.mkdtemp(prefix="search001b-"))
    repo = tmp / "repo"
    repo.mkdir()

    try:
        archive = subprocess.check_output(["git", "archive", "--format=tar", SUBSTRATE], cwd=src)
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

        if not (repo / "experiments/airlock-self-001/office_ops.py").is_file():
            raise RuntimeError("SEARCH-001B target missing from worker substrate")

        cfg = repo / ".airlock/search-001b-public-config.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps(PUBLIC, indent=2) + "\n")

        sh(["git", "init"], repo)
        sh(["git", "config", "user.name", "SEARCH-001B"], repo)
        sh(["git", "config", "user.email", "search001b@invalid.local"], repo)
        sh(["git", "add", "-A"], repo)
        cp = sh(["git", "commit", "-m", "SEARCH-001B worker substrate"], repo)
        if cp.returncode:
            raise RuntimeError(cp.stderr)

        preflight = sh(["python", ".airlock/self-001/protected_checks.py"], repo)
        if preflight.returncode != 0:
            raise RuntimeError("worker substrate public checks are not green")

        base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()

        report = run_tournament(
            repo,
            PROMPT,
            agents=CANDIDATES,
            models=["hermes"] * CANDIDATES,
            budget=None,
            open_pr=False,
            config_path=cfg,
        )

        hermes_home = Path(os.environ["HERMES_HOME"])
        rows = []
        for row in report.get("candidates", []):
            cid = str(row.get("candidate_id") or "")
            commit = row.get("commit")
            stats = diff_stats(repo, base, commit) if isinstance(commit, str) and commit else {
                "changed_files": 0, "changed_lines": 0
            }

            dossier_path = hermes_home / f"search-001b-{cid}.json"
            dossier, dossier_error = validate_dossier(dossier_path, cid)

            search_filter = {"status": "FAIL", "reason": dossier_error}
            baseline_probe = None
            candidate_probe = None
            measured_delta = None

            if dossier is not None:
                if stats["changed_files"] > MAX_CHANGED_FILES:
                    search_filter = {"status": "FAIL", "reason": "CHANGED_FILE_LIMIT"}
                elif stats["changed_lines"] > MAX_CHANGED_LINES:
                    search_filter = {"status": "FAIL", "reason": "CHANGED_LINE_LIMIT"}
                elif row.get("disposition") != "SURVIVED":
                    search_filter = {
                        "status": "FAIL",
                        "reason": row.get("reason") or "PUBLIC_GATE_REJECTED"
                    }
                else:
                    command = dossier["probe"]["command"]
                    direction = dossier["probe"]["direction"]
                    epsilon = float(dossier["probe"].get("epsilon", 0.0))
                    base_wt = add_worktree(repo, base, f"search001b-base-{cid}-")
                    cand_wt = add_worktree(repo, commit, f"search001b-cand-{cid}-")
                    try:
                        baseline_probe = numeric_probe(base_wt, command)
                        candidate_probe = numeric_probe(cand_wt, command)
                    finally:
                        remove_worktree(repo, base_wt)
                        remove_worktree(repo, cand_wt)

                    if baseline_probe.get("status") != "PASS":
                        search_filter = {"status": "FAIL", "reason": "BASELINE_PROBE_DID_NOT_REPRODUCE"}
                    elif candidate_probe.get("status") != "PASS":
                        search_filter = {"status": "FAIL", "reason": "CANDIDATE_PROBE_DID_NOT_REPRODUCE"}
                    else:
                        before = float(baseline_probe["median"])
                        after = float(candidate_probe["median"])
                        measured_delta = (before - after) if direction == "lower" else (after - before)
                        if measured_delta <= epsilon:
                            search_filter = {
                                "status": "FAIL",
                                "reason": "NO_LOCAL_MEASURED_IMPROVEMENT",
                                "delta": measured_delta,
                                "epsilon": epsilon,
                            }
                        else:
                            search_filter = {
                                "status": "PASS",
                                "reason": "MEASURED_LOCAL_GAIN",
                                "delta": measured_delta,
                                "epsilon": epsilon,
                            }

            patch = ""
            if isinstance(commit, str) and commit and commit != base:
                cp = sh(["git", "diff", "--binary", "--full-index", f"{base}..{commit}", "--", "."], repo)
                patch = cp.stdout if cp.returncode == 0 else ""

            rows.append({
                "candidate_id": cid,
                "public_disposition": row.get("disposition"),
                "public_reason": row.get("reason"),
                "changed_paths": row.get("changed_paths", []),
                "diff": stats,
                "probe_dossier": dossier,
                "probe_dossier_sha256": (
                    hashlib.sha256(dossier_path.read_bytes()).hexdigest()
                    if dossier_path.is_file() else None
                ),
                "baseline_probe": baseline_probe,
                "candidate_probe": candidate_probe,
                "measured_delta": measured_delta,
                "search_filter": search_filter,
                "patch": patch,
                "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
                "agent_execution": row.get("agent_execution"),
                "agent_report": row.get("agent_report", {}),
            })

        payload = {
            "schema": "airlock.search-001b.candidate-bundle.v1",
            "experiment": "AIRLOCK-SEARCH-001B",
            "strategy": "evidence_first",
            "substrate_commit": SUBSTRATE,
            "model": MODEL,
            "airlock_adapter": "hermes",
            "requested_candidates": CANDIDATES,
            "max_changed_files": MAX_CHANGED_FILES,
            "max_changed_lines": MAX_CHANGED_LINES,
            "probe_repeats": PROBE_REPEATS,
            "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
            "public_preflight_green": True,
            "hidden_paths_absent": HIDDEN,
            "tournament": {
                "run_id": report.get("run_id"),
                "status": report.get("status"),
                "survivor_count": report.get("survivor_count"),
                "reported_cost": report.get("cost"),
                "elapsed_seconds": report.get("elapsed_seconds"),
            },
            "candidates": rows,
        }
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(json.dumps({
            "strategy": "evidence_first",
            "candidates": len(rows),
            "probe_passes": sum(r["search_filter"]["status"] == "PASS" for r in rows),
        }))
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
