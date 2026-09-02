#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREREG = ROOT / ".airlock/search-004/preregistration.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_sha(path: Path) -> str:
    rows = []
    for file in sorted((p for p in path.rglob("*") if p.is_file()), key=lambda p: p.relative_to(path).as_posix()):
        rows.append({"path": file.relative_to(path).as_posix(), "sha256": sha256(file), "size": file.stat().st_size})
    raw = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def fail(message: str) -> int:
    print(f"SEARCH-004 preregistration invalid: {message}", file=sys.stderr)
    return 1


def main() -> int:
    data = json.loads(PREREG.read_text())
    if data.get("schema") != "airlock.search-004.preregistration.v1":
        return fail("schema")
    if data.get("experiment_parent_sha") != "971750ee6d5bda0e2195dd87ca8ee9d37afb9187":
        return fail("base commit")
    amendment = data.get("infrastructure_amendment", {})
    if amendment.get("id") != "SEARCH-004-INFRA-001":
        return fail("infrastructure amendment")
    if amendment.get("prior_valid_arm_worker_contacts") != 0:
        return fail("amendment is not prospective")
    if amendment.get("failed_run_id") != 33681402437:
        return fail("amendment run identity")
    cp = subprocess.run(
        ["git", "merge-base", "--is-ancestor", data["experiment_parent_sha"], "HEAD"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if cp.returncode != 0:
        return fail("HEAD is not descended from frozen parent")
    for rel, expected in data.get("frozen_files", {}).items():
        path = ROOT / rel
        if not path.is_file() or sha256(path) != expected:
            return fail(f"frozen file mismatch: {rel}")
    substrate = ROOT / "experiments/airlock-search-002/substrate"
    if tree_sha(substrate) != data.get("substrate_tree_sha256"):
        return fail("substrate tree mismatch")

    tasks = json.loads((ROOT / ".airlock/search-004/guided-tasks.json").read_text())
    score = json.loads((ROOT / ".airlock/search-002/scorecard.json").read_text())
    task_dims = [row["dimension"] for row in tasks["tasks"]]
    score_dims = [row["id"] for row in score["dimensions"]]
    if len(task_dims) != 9 or len(set(task_dims)) != 9 or set(task_dims) != set(score_dims):
        return fail("guided schedule is not the exact nine-opportunity surface")
    if data.get("opportunity_pool", {}).get("scope") != "INTRA_ARM_ONLY":
        return fail("opportunity pool is not arm-local")
    if data.get("arm_order") != ["A", "B"]:
        return fail("resolved arm order")
    if data.get("resource_bounds", {}).get("max_worker_contacts_per_arm") != 4:
        return fail("worker contact ceiling")
    if data.get("resource_bounds", {}).get("spend_ceiling_usd_per_arm") != "5.00":
        return fail("spend ceiling")

    table = json.loads((ROOT / ".airlock/search-004/price-table.json").read_text())
    expected_rates = {
        "input_tokens": "4.00",
        "cache_read_tokens": "0.40",
        "cache_write_tokens": "5.00",
        "output_tokens": "20.00",
    }
    if table.get("rates_per_million_tokens") != expected_rates:
        return fail("frozen GPT-5.6 Sol rates")
    if table.get("long_context", {}).get("threshold_prompt_tokens_per_request") != 272000:
        return fail("long-context threshold")

    print("SEARCH-004 preregistration: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
