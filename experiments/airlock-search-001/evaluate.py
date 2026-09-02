#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, shutil, subprocess, sys, tempfile
from pathlib import Path

SUBSTRATE = "91861c77e4b03ace60df147b0accf94f4351de18"
BASELINE = "baseline_freeform"
MODIFIED = {"repo_scout"}

FROZEN_BLOBS = {
    ".airlock/self-001/scope_registry.json": "a09198480999cd4172ef77b4d81b22f837016a79",
    ".airlock/self-001/evaluator.py": "6cfe569eae7dc96bbefc9ec974555a55669e7bc1",
    ".airlock/self-001/protected_checks.py": "3c54bf80e3d6ad0f33bfad466a60f978c50d5d40",
    "experiments/airlock-self-001/run_self_001.py": "25ccfbfa30489ba8d0aec2eab745f9f071adf737",
}

INVALID_TOURNAMENT = {"BASELINE_NOT_GREEN", "INFRA_FAILURE", "ERROR"}


def git(repo: Path, *args: str) -> str:
    cp = subprocess.run(["git", *args], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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


def evaluate_candidate(repo: Path, candidate: str) -> dict:
    cp = subprocess.run(
        [sys.executable, ".airlock/self-001/evaluator.py",
         "--repo", str(repo), "--base", SUBSTRATE, "--candidate", candidate],
        cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        result = json.loads(cp.stdout)
    except Exception:
        return {"candidate_commit": candidate, "disposition": "REJECT", "reason": "EVALUATOR_ERROR"}
    result["evaluator_exit_code"] = cp.returncode
    return result


def select(rows: list[dict], minimum_gap: float) -> dict:
    eligible = [r for r in rows if r.get("disposition") == "ACCEPT"]
    if not eligible:
        return {"status": "NO_WINNER", "winner": None, "eligible": 0}
    ordered = sorted(
        eligible,
        key=lambda r: (float(r["net_gain_score"]), -int(r["diff"]["changed_lines"]), r["candidate_commit"]),
        reverse=True,
    )
    if len(ordered) == 1:
        return {"status": "UNIQUE_WINNER", "winner": ordered[0], "eligible": 1}
    gap = float(ordered[0]["net_gain_score"]) - float(ordered[1]["net_gain_score"])
    if gap <= minimum_gap:
        return {"status": "AMBIGUOUS", "winner": None, "eligible": len(ordered), "score_gap": gap}
    return {"status": "UNIQUE_WINNER", "winner": ordered[0], "eligible": len(ordered), "score_gap": gap}


def materialize(repo: Path, patch: str, cid: str):
    wt = Path(tempfile.mkdtemp(prefix="search001-eval-"))
    wt.rmdir()
    cp = subprocess.run(["git", "worktree", "add", "--detach", str(wt), SUBSTRATE],
                        cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if cp.returncode:
        raise RuntimeError(cp.stderr.strip())
    try:
        subprocess.run(["git", "config", "user.name", "SEARCH-001 Evaluator"], cwd=wt, check=True)
        subprocess.run(["git", "config", "user.email", "eval@invalid.local"], cwd=wt, check=True)
        ap = subprocess.run(["git", "apply", "--index", "--binary", "-"], cwd=wt,
                            input=patch, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if ap.returncode:
            raise ValueError("PATCH_APPLY_FAILED")
        subprocess.run(["git", "commit", "-m", f"SEARCH-001 candidate {cid}"], cwd=wt,
                       text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return wt, git(wt, "rev-parse", "HEAD")
    except Exception:
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=repo)
        shutil.rmtree(wt, ignore_errors=True)
        raise


def evaluate_bundle(repo: Path, bundle: dict, minimum_gap: float) -> dict:
    strategy = bundle.get("strategy")
    if strategy not in {BASELINE, *MODIFIED}:
        raise RuntimeError(f"unknown strategy {strategy}")
    if bundle.get("substrate_commit") != SUBSTRATE or bundle.get("model") != "gpt-5.6-sol" or bundle.get("requested_candidates") != 4:
        raise RuntimeError(f"resource/substrate mismatch {strategy}")
    if not bundle.get("target_present") or not bundle.get("public_preflight_green"):
        return {"strategy": strategy, "invalid": True, "reason": "BROKEN_WORKER_SUBSTRATE"}
    status = (bundle.get("tournament") or {}).get("status")
    if status in INVALID_TOURNAMENT:
        return {"strategy": strategy, "invalid": True, "reason": status}

    rows = []
    for candidate in bundle.get("candidates", []):
        cid = str(candidate.get("candidate_id") or "unknown")
        patch = candidate.get("patch") or ""
        if candidate.get("disposition") != "SURVIVED" or not patch:
            rows.append({"candidate_id": cid, "disposition": "REJECT",
                         "reason": candidate.get("reason") or "NO_STRUCTURAL_SURVIVOR"})
            continue
        wt = None
        try:
            wt, commit = materialize(repo, patch, cid)
            row = evaluate_candidate(wt, commit)
            row["candidate_id"] = cid
            row["patch_sha256"] = candidate.get("patch_sha256")
            rows.append(row)
        except ValueError as exc:
            rows.append({"candidate_id": cid, "disposition": "REJECT", "reason": str(exc)})
        finally:
            if wt is not None:
                subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=repo,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                shutil.rmtree(wt, ignore_errors=True)

    return {"strategy": strategy, "invalid": False, "candidates": rows,
            "selection": select(rows, minimum_gap), "tournament": bundle.get("tournament")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--artifacts")
    ap.add_argument("--out")
    ap.add_argument("--self-check", action="store_true")
    a = ap.parse_args()
    repo = Path(a.repo).resolve()

    verify_frozen(repo)
    evaluator_self_check(repo)

    if a.self_check:
        print(json.dumps({"frozen_selector": "PASS", "substrate": SUBSTRATE}))
        return 0

    registry = json.loads((repo / ".airlock/self-001/scope_registry.json").read_text())
    minimum_gap = float(registry["minimum_score_gap"])
    files = sorted(Path(a.artifacts).resolve().rglob("bundle.json"))
    if len(files) != 2:
        raise RuntimeError(f"expected 2 bundles, got {len(files)}")

    results = [evaluate_bundle(repo, json.loads(p.read_text()), minimum_gap) for p in files]
    if any(r.get("invalid") for r in results):
        outcome = "INVALID_EXPERIMENT"
        baseline_won = False
        modified_winners = []
    else:
        by = {r["strategy"]: r for r in results}
        if set(by) != {BASELINE, *MODIFIED}:
            raise RuntimeError("strategy set mismatch")
        baseline_won = by[BASELINE]["selection"]["status"] == "UNIQUE_WINNER"
        modified_winners = sorted(s for s in MODIFIED if by[s]["selection"]["status"] == "UNIQUE_WINNER")
        if baseline_won:
            outcome = "BASELINE_RECOVERED"
        elif modified_winners:
            outcome = "SEARCH_STRATEGY_GAIN"
        else:
            outcome = "SEARCH_GAP_PERSISTS"

    output = {
        "schema": "airlock.search-001.result.v2",
        "experiment": "AIRLOCK-SEARCH-001",
        "outcome": outcome,
        "baseline_unique_winner": baseline_won,
        "modified_unique_winners": modified_winners,
        "strategy_results": sorted(results, key=lambda x: x["strategy"]),
        "claim": (
            "A structured repo-search workflow found an independently admissible improvement that the same model and budget missed with a free-form prompt."
            if outcome == "SEARCH_STRATEGY_GAIN" else None
        ),
        "next_if_earned": "Repeat on fresh hidden repo opportunities before trying multi-step self-improvement.",
    }

    out = Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"outcome": outcome, "modified_unique_winners": modified_winners}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
