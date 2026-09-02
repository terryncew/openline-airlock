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

FROZEN_BLOBS = {
    ".airlock/self-001/scope_registry.json": "a09198480999cd4172ef77b4d81b22f837016a79",
    ".airlock/self-001/evaluator.py": "6cfe569eae7dc96bbefc9ec974555a55669e7bc1",
    ".airlock/self-001/protected_checks.py": "3c54bf80e3d6ad0f33bfad466a60f978c50d5d40",
    "experiments/airlock-self-001/run_self_001.py": "25ccfbfa30489ba8d0aec2eab745f9f071adf737",
}


def git(repo: Path, *args: str) -> str:
    cp = subprocess.run(["git", *args], cwd=repo, text=True,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if cp.returncode:
        raise RuntimeError(cp.stderr.strip())
    return cp.stdout.strip()


def verify_frozen(repo: Path) -> None:
    if git(repo, "rev-parse", SUBSTRATE) != SUBSTRATE:
        raise RuntimeError("exact SELF-001 substrate unavailable")
    for rel, blob in FROZEN_BLOBS.items():
        if git(repo, "rev-parse", f"{SUBSTRATE}:{rel}") != blob:
            raise RuntimeError(f"substrate selector mismatch {rel}")
        if git(repo, "rev-parse", f"HEAD:{rel}") != blob:
            raise RuntimeError(f"current frozen selector mismatch {rel}")


def evaluator_self_check(repo: Path) -> None:
    cp = subprocess.run([sys.executable, ".airlock/self-001/evaluator.py", "--self-test"],
                        cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if cp.returncode:
        raise RuntimeError(cp.stderr.strip() or cp.stdout.strip())


def evaluate_candidate(repo: Path, commit: str) -> dict:
    cp = subprocess.run(
        [sys.executable, ".airlock/self-001/evaluator.py",
         "--repo", str(repo), "--base", SUBSTRATE, "--candidate", commit],
        cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        result = json.loads(cp.stdout)
    except Exception:
        return {"candidate_commit": commit, "disposition": "REJECT", "reason": "EVALUATOR_ERROR"}
    result["evaluator_exit_code"] = cp.returncode
    return result


def select(rows: list[dict], minimum_gap: float) -> dict:
    eligible = [r for r in rows if r.get("disposition") == "ACCEPT"]
    if not eligible:
        return {"status": "NO_WINNER", "winner": None, "eligible": 0}
    ordered = sorted(
        eligible,
        key=lambda r: (
            float(r["net_gain_score"]),
            -int(r["diff"]["changed_lines"]),
            r["candidate_commit"],
        ),
        reverse=True,
    )
    if len(ordered) == 1:
        return {"status": "UNIQUE_WINNER", "winner": ordered[0], "eligible": 1}
    gap = float(ordered[0]["net_gain_score"]) - float(ordered[1]["net_gain_score"])
    if gap <= minimum_gap:
        return {"status": "AMBIGUOUS", "winner": None, "eligible": len(ordered), "score_gap": gap}
    return {"status": "UNIQUE_WINNER", "winner": ordered[0], "eligible": len(ordered), "score_gap": gap}


def materialize(repo: Path, patch: str, track_id: str):
    wt = Path(tempfile.mkdtemp(prefix="search001c-eval-"))
    wt.rmdir()
    cp = subprocess.run(["git", "worktree", "add", "--detach", str(wt), SUBSTRATE],
                        cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if cp.returncode:
        raise RuntimeError(cp.stderr.strip())
    try:
        subprocess.run(["git", "config", "user.name", "SEARCH-001C Evaluator"], cwd=wt, check=True)
        subprocess.run(["git", "config", "user.email", "eval@invalid.local"], cwd=wt, check=True)
        ap = subprocess.run(["git", "apply", "--index", "--binary", "-"], cwd=wt,
                            input=patch, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if ap.returncode:
            raise ValueError("PATCH_APPLY_FAILED")
        subprocess.run(["git", "commit", "-m", f"SEARCH-001C {track_id}"], cwd=wt,
                       text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return wt, git(wt, "rev-parse", "HEAD")
    except Exception:
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=repo)
        shutil.rmtree(wt, ignore_errors=True)
        raise


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--bundle")
    ap.add_argument("--out")
    ap.add_argument("--self-check", action="store_true")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    verify_frozen(repo)
    evaluator_self_check(repo)

    if args.self_check:
        print(json.dumps({"frozen_selector": "PASS", "substrate": SUBSTRATE}))
        return 0

    if not args.bundle or not args.out:
        ap.error("--bundle and --out are required unless --self-check")

    bundle = json.loads(Path(args.bundle).read_text())
    if (
        bundle.get("schema") != "airlock.search-001c.bundle.v1"
        or bundle.get("substrate_commit") != SUBSTRATE
        or bundle.get("strategy") != "outcome_trace"
        or bundle.get("model") != "gpt-5.6-sol"
        or bundle.get("tracks") != 4
        or bundle.get("total_max_turns_per_track") != 90
        or bundle.get("max_changed_files") != 2
    ):
        raise RuntimeError("SEARCH-001C bundle boundary mismatch")

    registry = json.loads((repo / ".airlock/self-001/scope_registry.json").read_text())
    minimum_gap = float(registry["minimum_score_gap"])
    rows = []
    prefilter = []

    for track in bundle.get("tracks_result", []):
        track_id = str(track.get("track_id") or "unknown")
        if track.get("status") != "READY_FOR_HIDDEN_EVALUATION":
            prefilter.append({
                "track_id": track_id,
                "status": track.get("status"),
                "reason": track.get("reason"),
            })
            continue

        patch = track.get("patch") or ""
        if not patch:
            prefilter.append({"track_id": track_id, "status": "REJECT", "reason": "NO_PATCH"})
            continue

        wt = None
        try:
            wt, commit = materialize(repo, patch, track_id)
            row = evaluate_candidate(wt, commit)
            row["track_id"] = track_id
            row["public_outcome"] = {
                "anchor_type": (track.get("plan") or {}).get("public_anchor_type"),
                "anchor_path": (track.get("plan") or {}).get("public_anchor_path"),
                "expected_outcome": (track.get("plan") or {}).get("expected_outcome"),
                "outcome_delta": track.get("outcome_delta"),
                "plan_sha256": track.get("plan_sha256"),
            }
            rows.append(row)
        except ValueError as exc:
            rows.append({"track_id": track_id, "disposition": "REJECT", "reason": str(exc)})
        finally:
            if wt is not None:
                subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=repo,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                shutil.rmtree(wt, ignore_errors=True)

    selection = select(rows, minimum_gap)
    won = selection["status"] == "UNIQUE_WINNER"
    outcome = "SEARCH_STRATEGY_GAIN" if won else "OUTCOME_LINK_SEARCH_DEFICIT"

    output = {
        "schema": "airlock.search-001c.result.v1",
        "experiment": "AIRLOCK-SEARCH-001C",
        "strategy": "Outcome Trace",
        "outcome": outcome,
        "earned_label": "SEARCH_STRATEGY_GAIN" if won else None,
        "selection": selection,
        "hidden_evaluated_candidates": rows,
        "pre_hidden_filter": prefilter,
        "claim": (
            "A public-outcome-linked search process found an independently admissible improvement under the unchanged frozen SELF-001 evaluator."
            if won else None
        ),
        "claim_boundary": (
            "The worker received no hidden evaluator output, hidden registry names, positive-control patch, "
            "or hidden proximity feedback. The directed control was used only to audit channel type; because it "
            "was maintainer-targeted rather than publicly discovered, it contributed no search weighting."
        ),
        "next_if_earned": "AIRLOCK-SEARCH-002 fresh-target replication",
    }

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"outcome": outcome, "hidden_candidates": len(rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
