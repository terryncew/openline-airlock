#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from airlock.runner import run_tournament

SUBSTRATE = "91861c77e4b03ace60df147b0accf94f4351de18"
MODEL = "gpt-5.6-sol"
CANDIDATES = 4

STRATEGIES = {
    "baseline_freeform": 'Improve this repository. Find the highest-value small, reversible change you can justify. You choose the problem and the implementation. The independent checks decide whether anything is good enough.',
    "repo_scout": 'Improve this repository, but do not start coding immediately.\n\nFirst understand what the repo is trying to do and where it is getting in its own way. Look for slow paths, brittle code, repeated failure points, awkward developer experience, risky seams, unnecessary complexity, and missing small affordances.\n\nThen:\n1. Write down at least five concrete improvement ideas.\n2. For each idea, identify the thing you can actually change on purpose.\n3. Stress-check each idea: is this a real weakness or just something unusual? Would it still matter if the implementation looked different? Would fixing it solve more than one symptom? What could the fix break?\n4. Check the idea from six practical angles: speed, reliability, developer experience, security, maintainability, and user impact.\n5. If the diagnosis is fuzzy, identify the single measurement or repo fact that would settle it, then inspect that before choosing.\n6. Rank the ideas by expected value, confidence, reversibility, patch size, and regression risk.\n7. Implement the best small reversible improvement. If the top idea has no clear controllable lever, skip it and take the next one.\n\nDo not change the independent checks or grading rules. Your job is to find and build a better change; the repo decides whether it earns admission.',
}

# Keep the code under test. Remove only material that could tell the worker how
# the hidden evaluation works or reveal the directed SELF-001 harness.
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


def sh(cmd, cwd, *, text=True):
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-repo", default=".")
    ap.add_argument("--strategy", required=True, choices=sorted(STRATEGIES))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    src = Path(args.source_repo).resolve()
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    if subprocess.check_output(["git", "rev-parse", SUBSTRATE], cwd=src, text=True).strip() != SUBSTRATE:
        raise RuntimeError("pinned substrate unavailable")

    tmp = Path(tempfile.mkdtemp(prefix=f"search001-{args.strategy}-"))
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

        target = repo / "experiments/airlock-self-001/office_ops.py"
        if not target.is_file():
            raise RuntimeError("SEARCH-001 target was removed during sanitization")

        cfg = repo / ".airlock/search-public-config.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps(PUBLIC, indent=2) + "\n")

        sh(["git", "init"], repo)
        sh(["git", "config", "user.name", "SEARCH-001"], repo)
        sh(["git", "config", "user.email", "search001@invalid.local"], repo)
        sh(["git", "add", "-A"], repo)
        cp = sh(["git", "commit", "-m", "SEARCH-001 worker substrate"], repo)
        if cp.returncode:
            raise RuntimeError(cp.stderr)

        # Fail before any model spend if the public starting checks are broken.
        preflight = sh(["python", ".airlock/self-001/protected_checks.py"], repo)
        if preflight.returncode != 0:
            raise RuntimeError(
                "worker substrate is not green before search: "
                + (preflight.stderr or preflight.stdout)
            )

        base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()

        report = run_tournament(
            repo,
            STRATEGIES[args.strategy],
            agents=CANDIDATES,
            models=["hermes"] * CANDIDATES,
            budget=None,
            open_pr=False,
            config_path=cfg,
        )

        rows = []
        for row in report.get("candidates", []):
            commit = row.get("commit")
            patch = ""
            if isinstance(commit, str) and commit and commit != base:
                diff = sh(
                    ["git", "diff", "--binary", "--full-index", f"{base}..{commit}", "--", "."],
                    repo,
                )
                patch = diff.stdout if diff.returncode == 0 else ""

            rows.append({
                "candidate_id": row.get("candidate_id"),
                "model": row.get("model"),
                "disposition": row.get("disposition"),
                "reason": row.get("reason"),
                "changed_paths": row.get("changed_paths", []),
                "patch": patch,
                "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
                "agent_execution": row.get("agent_execution"),
                "agent_report": row.get("agent_report", {}),
                "checks": row.get("checks", []),
            })

        payload = {
            "schema": "airlock.search-001.candidate-bundle.v2",
            "strategy": args.strategy,
            "substrate_commit": SUBSTRATE,
            "model": MODEL,
            "airlock_adapter": "hermes",
            "requested_candidates": CANDIDATES,
            "prompt_sha256": hashlib.sha256(STRATEGIES[args.strategy].encode()).hexdigest(),
            "target_present": True,
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
            "strategy": args.strategy,
            "candidates": len(rows),
            "survivors": sum(r.get("disposition") == "SURVIVED" for r in rows),
            "tournament_status": report.get("status"),
        }))
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
