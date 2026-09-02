#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SUBSTRATE = "91861c77e4b03ace60df147b0accf94f4351de18"
BASELINE = "baseline_freeform"
MODIFIED = {"triage_rank", "hypotheses_first", "planner_select"}

# Git blob identities from the exact frozen SELF-001 substrate.
# This avoids a bookkeeping failure caused by preregistering incorrect SHA-256
# strings for files whose actual content never changed.
FROZEN_BLOBS = {
    ".airlock/self-001/scope_registry.json": "a09198480999cd4172ef77b4d81b22f837016a79",
    ".airlock/self-001/evaluator.py": "6cfe569eae7dc96bbefc9ec974555a55669e7bc1",
    ".airlock/self-001/protected_checks.py": "3c54bf80e3d6ad0f33bfad466a60f978c50d5d40",
    "experiments/airlock-self-001/run_self_001.py": "25ccfbfa30489ba8d0aec2eab745f9f071adf737",
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


def verify_frozen(repo: Path) -> None:
    if git(repo, "rev-parse", SUBSTRATE) != SUBSTRATE:
        raise RuntimeError("exact SELF-001 substrate unavailable")

    for rel, expected_blob in FROZEN_BLOBS.items():
        substrate_blob = git(repo, "rev-parse", f"{SUBSTRATE}:{rel}")
        current_blob = git(repo, "rev-parse", f"HEAD:{rel}")
        if substrate_blob != expected_blob:
            raise RuntimeError(f"substrate selector mismatch {rel}")
        if current_blob != expected_blob:
            raise RuntimeError(f"current frozen selector mismatch {rel}")


def evaluator_self_check(repo: Path) -> None:
    cp = subprocess.run(
        [sys.executable, ".airlock/self-001/evaluator.py", "--self-test"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if cp.returncode != 0:
        raise RuntimeError(
            "frozen evaluator self-test failed: "
            + (cp.stderr.strip() or cp.stdout.strip())
        )


def load_registry(repo: Path) -> dict:
    return json.loads((repo / ".airlock/self-001/scope_registry.json").read_text())


def evaluate_candidate(repo: Path, candidate_commit: str) -> dict:
    cp = subprocess.run(
        [
            sys.executable,
            ".airlock/self-001/evaluator.py",
            "--repo",
            str(repo),
            "--base",
            SUBSTRATE,
            "--candidate",
            candidate_commit,
        ],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    try:
        data = json.loads(cp.stdout)
    except Exception:
        return {
            "candidate_commit": candidate_commit,
            "disposition": "REJECT",
            "reason": "EVALUATOR_ERROR",
            "stderr_tail": cp.stderr[-1000:],
            "stdout_tail": cp.stdout[-1000:],
        }
    data["evaluator_exit_code"] = cp.returncode
    return data


def select(rows: list[dict], minimum_gap: float) -> dict:
    # Exact selection semantics copied from frozen SELF-001 run_self_001.py.
    eligible = [row for row in rows if row.get("disposition") == "ACCEPT"]
    if not eligible:
        return {"status": "NO_WINNER", "winner": None, "eligible": 0}

    ordered = sorted(
        eligible,
        key=lambda row: (
            float(row["net_gain_score"]),
            -int(row["diff"]["changed_lines"]),
            row["candidate_commit"],
        ),
        reverse=True,
    )
    if len(ordered) == 1:
        return {"status": "UNIQUE_WINNER", "winner": ordered[0], "eligible": 1}

    gap = float(ordered[0]["net_gain_score"]) - float(ordered[1]["net_gain_score"])
    if gap <= minimum_gap:
        return {
            "status": "AMBIGUOUS",
            "winner": None,
            "eligible": len(ordered),
            "score_gap": gap,
        }
    return {
        "status": "UNIQUE_WINNER",
        "winner": ordered[0],
        "eligible": len(ordered),
        "score_gap": gap,
    }


def materialize_candidate(repo: Path, patch: str, candidate_id: str) -> tuple[Path, str]:
    wt = Path(tempfile.mkdtemp(prefix="search001-eval-"))
    wt.rmdir()

    cp = subprocess.run(
        ["git", "worktree", "add", "--detach", str(wt), SUBSTRATE],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if cp.returncode:
        raise RuntimeError(cp.stderr.strip())

    try:
        subprocess.run(
            ["git", "config", "user.name", "SEARCH-001 Evaluator"],
            cwd=wt,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "eval@invalid.local"],
            cwd=wt,
            check=True,
        )
        applied = subprocess.run(
            ["git", "apply", "--index", "--binary", "-"],
            cwd=wt,
            input=patch,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if applied.returncode:
            raise ValueError("PATCH_APPLY_FAILED")

        committed = subprocess.run(
            ["git", "commit", "-m", f"SEARCH-001 candidate {candidate_id}"],
            cwd=wt,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if committed.returncode:
            raise ValueError("PATCH_COMMIT_FAILED")

        return wt, git(wt, "rev-parse", "HEAD")
    except Exception:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(wt)],
            cwd=repo,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        shutil.rmtree(wt, ignore_errors=True)
        raise


def remove_worktree(repo: Path, wt: Path) -> None:
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(wt)],
        cwd=repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    shutil.rmtree(wt, ignore_errors=True)


def evaluate_bundle(repo: Path, bundle: dict, minimum_gap: float) -> dict:
    strategy = bundle.get("strategy")
    if strategy not in {BASELINE, *MODIFIED}:
        raise RuntimeError(f"unknown strategy {strategy}")

    if (
        bundle.get("substrate_commit") != SUBSTRATE
        or bundle.get("model") != "gpt-5.6-sol"
        or bundle.get("requested_candidates") != 4
    ):
        raise RuntimeError(f"resource/substrate mismatch {strategy}")

    rows = []
    for candidate in bundle.get("candidates", []):
        cid = str(candidate.get("candidate_id") or "unknown")
        patch = candidate.get("patch") or ""

        if candidate.get("disposition") != "SURVIVED" or not patch:
            rows.append(
                {
                    "candidate_id": cid,
                    "disposition": "REJECT",
                    "reason": candidate.get("reason") or "NO_STRUCTURAL_SURVIVOR",
                }
            )
            continue

        wt = None
        try:
            wt, commit = materialize_candidate(repo, patch, cid)
            result = evaluate_candidate(wt, commit)
            result["candidate_id"] = cid
            result["patch_sha256"] = candidate.get("patch_sha256")
            rows.append(result)
        except ValueError as exc:
            rows.append(
                {
                    "candidate_id": cid,
                    "disposition": "REJECT",
                    "reason": str(exc),
                }
            )
        finally:
            if wt is not None:
                remove_worktree(repo, wt)

    return {
        "strategy": strategy,
        "candidates": rows,
        "selection": select(rows, minimum_gap),
        "tournament": bundle.get("tournament"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    parser.add_argument("--artifacts")
    parser.add_argument("--out")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    verify_frozen(repo)
    evaluator_self_check(repo)

    if args.self_check:
        print(
            json.dumps(
                {
                    "frozen_selector": "PASS",
                    "substrate": SUBSTRATE,
                    "selector_identity": "git-blob",
                    "evaluator_selftest": "PASS",
                }
            )
        )
        return 0

    if not args.artifacts or not args.out:
        parser.error("--artifacts and --out are required unless --self-check is used")

    registry = load_registry(repo)
    minimum_gap = float(registry["minimum_score_gap"])

    files = sorted(Path(args.artifacts).resolve().rglob("bundle.json"))
    if len(files) != 4:
        raise RuntimeError(f"expected 4 bundles, got {len(files)}")

    seen = set()
    results = []
    for path in files:
        bundle = json.loads(path.read_text())
        strategy = bundle.get("strategy")
        if strategy in seen:
            raise RuntimeError(f"duplicate strategy {strategy}")
        seen.add(strategy)
        results.append(evaluate_bundle(repo, bundle, minimum_gap))

    expected = {BASELINE, *MODIFIED}
    if seen != expected:
        raise RuntimeError(
            f"strategy set mismatch: expected {sorted(expected)}, got {sorted(seen)}"
        )

    by_strategy = {row["strategy"]: row for row in results}
    baseline_won = by_strategy[BASELINE]["selection"]["status"] == "UNIQUE_WINNER"
    modified_winners = sorted(
        strategy
        for strategy in MODIFIED
        if by_strategy[strategy]["selection"]["status"] == "UNIQUE_WINNER"
    )

    if baseline_won:
        outcome = "BASELINE_RECOVERED"
        earned = False
    elif modified_winners:
        outcome = "SEARCH_STRATEGY_GAIN"
        earned = True
    else:
        outcome = "SEARCH_GAP_PERSISTS"
        earned = False

    output = {
        "schema": "airlock.search-001.result.v1",
        "experiment": "AIRLOCK-SEARCH-001",
        "substrate_commit": SUBSTRATE,
        "outcome": outcome,
        "earned_label": "SEARCH_STRATEGY_GAIN" if earned else None,
        "baseline_unique_winner": baseline_won,
        "modified_unique_winners": modified_winners,
        "strategy_results": sorted(results, key=lambda row: row["strategy"]),
        "frozen_selector_git_blobs": FROZEN_BLOBS,
        "claim": (
            "Under the frozen SELF-001 gate and equal resource budget, a "
            "preregistered modified autonomous search strategy produced at least "
            "one independently admissible improvement that baseline Hermes failed "
            "to discover."
            if earned
            else None
        ),
        "claim_boundary": (
            "Proposal/search strategy varies only. The hidden SELF-001 selector "
            "was absent from generation jobs and unchanged in evaluation. "
            "Fresh-target replication is required before SELF-002 compounding."
        ),
        "next_if_earned": "AIRLOCK-SEARCH-002 fresh-target replication",
    }

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "outcome": outcome,
                "modified_unique_winners": modified_winners,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
