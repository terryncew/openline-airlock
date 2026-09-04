#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from airlock import unattended

ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / ".airlock/hydrafusion-001/task-freeze.json"
PATCH = ROOT / ".airlock/hydrafusion-001/stage-a-candidate.patch"
ORACLE = ROOT / ".airlock/search-002/oracle.py"
SUBSTRATE = ROOT / "experiments/airlock-search-002/substrate"
PRODUCERS = ["hydrafusion", "opus", "codex"]
ISSUE_NUMBER = 1001
IMAGE = "python:3.12-slim"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def run(argv: list[str], cwd: Path, *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)


def git(repo: Path, *args: str) -> str:
    cp = run(["git", *args], repo)
    if cp.returncode:
        raise RuntimeError(cp.stderr.strip() or f"git {' '.join(args)} failed")
    return cp.stdout.strip()


def tree_sha(path: Path) -> str:
    rows = []
    for file in sorted((p for p in path.rglob("*") if p.is_file()), key=lambda p: p.relative_to(path).as_posix()):
        rows.append({"path": file.relative_to(path).as_posix(), "sha256": sha256_file(file), "size": file.stat().st_size})
    return sha256_bytes(canonical(rows))


def copy_substrate(dest: Path) -> None:
    shutil.copytree(SUBSTRATE, dest)
    (dest / ".airlock").mkdir(exist_ok=True)


def configure_fixture(repo: Path, freeze: dict) -> str:
    config = {
        "schema": "airlock.config.v1",
        "protected_paths": freeze["protected_paths"],
        "baseline": {"check_commands": freeze["evaluation"]["public_commands"], "timeout_seconds": 300},
        "verification": {
            "target_commands": [],
            "static_commands": [],
            "test_commands": freeze["evaluation"]["public_commands"],
            "timeout_seconds": 300,
        },
    }
    policy = {
        "schema": "airlock.unattended.policy.v1",
        "candidate_count": 3,
        "label": "hydrafusion-001-stage-a",
        "evaluation": {
            "image": IMAGE,
            "memory": "2g",
            "cpus": "2",
            "pids_limit": 512,
        },
    }
    (repo / ".airlock/config.json").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    (repo / ".airlock/unattended.json").write_text(json.dumps(policy, indent=2, sort_keys=True) + "\n")
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Airlock Stage A")
    git(repo, "config", "user.email", "airlock-stage-a@example.invalid")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "frozen Stage A substrate")
    return git(repo, "rev-parse", "HEAD")


def baseline_preflight(repo: Path, freeze: dict) -> dict:
    public = run(["python", "public_checks.py"], repo)
    contract = run(["python", "tests/test_public_contract.py"], repo)
    oracle = run([sys.executable, str(ORACLE), "--repo", str(repo)], ROOT)
    if oracle.returncode:
        raise RuntimeError(oracle.stderr.strip() or "baseline oracle failed")
    oracle_json = json.loads(oracle.stdout)
    observed = {
        "public_checks_exit_code": public.returncode,
        "protected_contract_exit_code": contract.returncode,
        "oracle_passed_count": oracle_json["passed_count"],
        "oracle_authority_clean": oracle_json["authority_clean"],
    }
    if observed != freeze["baseline_preflight"]["required"]:
        raise RuntimeError(f"baseline preflight mismatch: {observed!r}")
    return observed


def make_candidates(root: Path, base: str, freeze: dict) -> None:
    patch_bytes = PATCH.read_bytes()
    patch_sha = sha256_bytes(patch_bytes)
    expected_sha = freeze["stage_a"]["candidate_patch_sha256"]
    if patch_sha != expected_sha:
        raise RuntimeError("frozen Stage A patch hash mismatch")
    changed_paths = ["maintbox/retry.py"]
    for index, producer in enumerate(PRODUCERS, start=1):
        candidate_id = f"{index:02d}"
        out = root / f"airlock-candidate-{candidate_id}"
        out.mkdir(parents=True)
        (out / "candidate.patch").write_bytes(patch_bytes)
        body = {
            "schema": unattended.CANDIDATE_SCHEMA,
            "candidate_id": candidate_id,
            "producer": producer,
            "issue_number": ISSUE_NUMBER,
            "issue_url": "https://github.com/terryncew/openline-airlock",
            "base_commit": base,
            "prompt_sha256": freeze["task"]["prompt_sha256"],
            "agent_outcome": "success",
            "patch_sha256": patch_sha,
            "patch_bytes": len(patch_bytes),
            "changed_paths": changed_paths,
            "final_message_sha256": None,
        }
        manifest = {"candidate_manifest_sha256": sha256_bytes(canonical(body)), **body}
        (out / "candidate.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def oracle_after_patch(repo: Path) -> dict:
    cp = run(["git", "apply", "--index", "--binary", str(PATCH)], repo)
    if cp.returncode:
        raise RuntimeError(cp.stderr.strip() or "could not apply frozen Stage A patch for oracle")
    oracle = run([sys.executable, str(ORACLE), "--repo", str(repo)], ROOT)
    if oracle.returncode:
        raise RuntimeError(oracle.stderr.strip() or "candidate oracle failed")
    return json.loads(oracle.stdout)


def substantive_projection(row: dict, producer: str, oracle: dict, baseline: int) -> dict:
    check_projection = []
    for check in row["checks"]:
        projected = {"rule": check.get("rule"), "status": check.get("status")}
        if check.get("rule") == "protected_files":
            projected["touched"] = check.get("touched", [])
        if check.get("rule") == "evidence_sufficiency":
            projected["basis"] = check.get("basis")
            projected["matched_tests"] = check.get("matched_tests", [])
        if "commands" in check:
            projected["command_results"] = [
                {
                    "argv": cmd.get("argv"),
                    "exit_code": cmd.get("exit_code"),
                    "timed_out": cmd.get("timed_out"),
                    "side_effect": cmd.get("side_effect"),
                    "stdout_sha256": cmd.get("stdout_sha256"),
                    "stderr_sha256": cmd.get("stderr_sha256"),
                }
                for cmd in check.get("commands", [])
            ]
        check_projection.append(projected)
    verified = int(oracle["passed_count"]) - int(baseline)
    return {
        "producer": producer,
        "airlock_disposition": row["disposition"],
        "airlock_reason": row["reason"],
        "changed_paths": row.get("changed_paths", []),
        "checks": check_projection,
        "oracle_passed_count": oracle["passed_count"],
        "verified_improvements": verified,
        "oracle_authority_clean": oracle["authority_clean"],
        "eligibility": "ELIGIBLE" if row["disposition"] == "SURVIVED" and oracle["authority_clean"] and verified >= 1 else "INELIGIBLE",
    }


def comparison_projection(value: dict) -> dict:
    out = dict(value)
    out.pop("producer", None)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("airlock-hydrafusion-001-stage-a"))
    args = ap.parse_args()
    freeze = json.loads(FREEZE.read_text())
    if freeze.get("schema") != "airlock.hydrafusion-001.task-freeze.v1":
        raise RuntimeError("unexpected task-freeze schema")
    if tree_sha(SUBSTRATE) != freeze["target"]["substrate_tree_sha256"]:
        raise RuntimeError("frozen substrate tree mismatch")
    if sha256_file(ORACLE) != freeze["target"]["external_oracle"]["sha256"]:
        raise RuntimeError("frozen oracle hash mismatch")

    temp = Path(tempfile.mkdtemp(prefix="airlock-hydrafusion-stage-a-"))
    try:
        fixture = temp / "fixture"
        copy_substrate(fixture)
        base = configure_fixture(fixture, freeze)
        baseline = baseline_preflight(fixture, freeze)

        candidates = temp / "candidates"
        candidates.mkdir()
        make_candidates(candidates, base, freeze)
        gate_out = temp / "gate-out"
        result = unattended.evaluate_candidates(
            fixture,
            base=base,
            issue_number=ISSUE_NUMBER,
            candidates_root=candidates,
            out_dir=gate_out,
            workflow_run_id=os.environ.get("GITHUB_RUN_ID", "local-stage-a"),
            workflow_run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        )

        oracle_fixture = temp / "oracle-fixture"
        copy_substrate(oracle_fixture)
        oracle = oracle_after_patch(oracle_fixture)

        rows = result["candidates"]
        if len(rows) != 3:
            raise RuntimeError(f"expected 3 Airlock rows, got {len(rows)}")
        projections = [
            substantive_projection(row, producer, oracle, baseline["oracle_passed_count"])
            for row, producer in zip(rows, PRODUCERS, strict=True)
        ]
        comparable = [comparison_projection(row) for row in projections]
        invariant = all(row == comparable[0] for row in comparable[1:])
        expected = freeze["stage_a"]["expected_substantive_result"]
        expected_ok = all(
            p["eligibility"] == expected["disposition"]
            and p["oracle_passed_count"] == expected["oracle_passed_count"]
            and p["verified_improvements"] == expected["verified_improvements"]
            and p["oracle_authority_clean"] == expected["oracle_authority_clean"]
            for p in projections
        )
        gate_ok = (
            result["decision"] == "READY_FOR_REVIEW"
            and result["survivor_count"] == 3
            and result["unique_survivor_count"] == 1
            and all(row["disposition"] == "SURVIVED" for row in rows)
        )
        verdict = "STAGE_A_PRODUCER_LABEL_INVARIANCE_PASS" if invariant and expected_ok and gate_ok else "STAGE_A_PRODUCER_LABEL_INVARIANCE_FAIL"

        image = run(["docker", "image", "inspect", IMAGE, "--format", "{{json .RepoDigests}}"], ROOT)
        image_digests = []
        if image.returncode == 0 and image.stdout.strip():
            try: image_digests = json.loads(image.stdout.strip()) or []
            except Exception: image_digests = []

        report = {
            "schema": "airlock.hydrafusion-001.stage-a.v1",
            "verdict": verdict,
            "task_freeze_sha256": sha256_file(FREEZE),
            "candidate_patch_sha256": sha256_file(PATCH),
            "substrate_tree_sha256": tree_sha(SUBSTRATE),
            "oracle_sha256": sha256_file(ORACLE),
            "evaluation_image": IMAGE,
            "evaluation_image_repo_digests": image_digests,
            "baseline": baseline,
            "airlock": {
                "decision": result["decision"],
                "survivor_count": result["survivor_count"],
                "unique_survivor_count": result["unique_survivor_count"],
                "receipt_sha256": result["receipt_sha256"],
                "config_sha256": result["config_sha256"],
                "policy_sha256": result["policy_sha256"],
            },
            "producer_results": projections,
            "checks": {
                "producer_label_substantive_invariance": invariant,
                "frozen_expected_result_met": expected_ok,
                "same_patch_collapsed_to_one_unique_survivor": gate_ok,
            },
        }
        args.out.mkdir(parents=True, exist_ok=True)
        result_path = args.out / "stage-a-result.json"
        result_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        (args.out / "stage-a-result.sha256").write_text(sha256_file(result_path) + "\n")
        shutil.copy2(gate_out / "result.json", args.out / "airlock-result.json")
        shutil.copy2(gate_out / "result.sha256", args.out / "airlock-result.sha256")
        shutil.copy2(PATCH, args.out / "stage-a-candidate.patch")

        print(verdict)
        print(f"Airlock: {result['decision']} / {result['survivor_count']} survivors / {result['unique_survivor_count']} unique patch")
        for p in projections:
            print(f"{p['producer']}: {p['airlock_disposition']} / {p['airlock_reason']} / {p['verified_improvements']} verified improvement")
        return 0 if verdict.endswith("PASS") else 1
    finally:
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
