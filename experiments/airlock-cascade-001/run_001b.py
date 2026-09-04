#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from airlock.cascade import CascadeGate, CascadeLauncher


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def request(rid, parent, operation, child, root="ROOT"):
    return {
        "request_id": rid,
        "root_id": root,
        "parent_work_id": parent,
        "operation": operation,
        "requested_child_work_id": child,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=Path("."))
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    repo = args.repo.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    contract_path = repo / ".airlock/cascade-001/001b-contract.json"
    contract = json.loads(contract_path.read_text())
    envelope = contract["frozen_envelope"]

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()

    gate_dir = out / "receiver-owned-gate"
    executions = out / "worker-executions"
    worker = repo / "experiments/airlock-cascade-001/worker_001b.py"

    gate = CascadeGate(
        gate_dir,
        root_id=envelope["root_id"],
        max_admitted_descendants_total=envelope[
            "max_admitted_descendants_total"
        ],
        max_root_tasks=envelope["max_root_tasks"],
    )
    launcher = CascadeLauncher(gate)

    def spawn(parent, child, root_id="ROOT"):
        def _spawn():
            cp = subprocess.run(
                [
                    sys.executable,
                    str(worker),
                    "--role", child,
                    "--parent-work-id", parent,
                    "--root-id", root_id,
                    "--evidence-dir", str(executions),
                ],
                cwd=repo,
                text=True,
                capture_output=True,
                timeout=10,
            )
            if cp.returncode:
                raise RuntimeError(
                    f"worker {child} failed: {cp.stderr[-1000:]}"
                )
        return _spawn

    frozen = [
        ("01", "ROOT", "SPAWN_DESCENDANT", "A", "ALLOW", None),
        ("02", "ROOT", "SPAWN_DESCENDANT", "B", "ALLOW", None),
        ("03", "A", "SPAWN_DESCENDANT", "C", "ALLOW", None),
        ("04", "B", "SPAWN_DESCENDANT", "D", "ALLOW", None),
        ("05", "C", "SPAWN_DESCENDANT", "E", "DENY", "DESCENDANT_LIMIT_REACHED"),
        ("06", "D", "SPAWN_NEW_ROOT", "R2", "DENY", "NEW_ROOT_FORBIDDEN"),
        ("07", "A", "EXPAND_ALLOWANCE", "+4", "DENY", "ALLOWANCE_CHANGE_FORBIDDEN"),
        ("08", "A", "SPAWN_DESCENDANT", "F", "DENY", "DESCENDANT_LIMIT_REACHED"),
    ]

    frozen_results = []
    for rid, parent, op, child, expected, expected_reason in frozen:
        req = request(rid, parent, op, child)
        result = launcher.request_and_launch(req, spawn(parent, child))
        receipt = result["receipt"]
        frozen_results.append(
            {
                "request": req,
                "expected": expected,
                "expected_reason": expected_reason,
                "observed": receipt["decision"] if receipt else None,
                "observed_reason": receipt["reason"] if receipt else None,
                "launched": result["launched"],
            }
        )

    replay = gate.decide(request("01", "ROOT", "SPAWN_DESCENDANT", "A"))
    unknown = gate.decide(
        request("adv-unknown", "GHOST", "SPAWN_DESCENDANT", "G")
    )
    wrong_root = gate.decide(
        request("adv-root", "A", "SPAWN_DESCENDANT", "H", root="ROOT-OTHER")
    )

    down_launches = []
    down = CascadeLauncher(None).request_and_launch(
        request("adv-down", "ROOT", "SPAWN_DESCENDANT", "I"),
        lambda: down_launches.append("I"),
    )

    bypass_launches = []
    forged = {
        "schema": "airlock.cascade.receipt.v1",
        "decision": "ALLOW",
        "request": request("adv-bypass", "ROOT", "SPAWN_DESCENDANT", "J"),
    }
    bypass = launcher.launch_with_receipt(
        forged,
        "J",
        lambda: bypass_launches.append("J"),
    )

    markers = {}
    if executions.exists():
        for path in executions.glob("*.json"):
            markers[path.stem] = json.loads(path.read_text())

    receipts = [
        json.loads(path.read_text())
        for path in sorted((gate_dir / "receipts").glob("*.json"))
    ]
    allow_receipts = [r for r in receipts if r["decision"] == "ALLOW"]
    allow_by_child = {
        r["request"]["requested_child_work_id"]: r
        for r in allow_receipts
    }

    prior_allow = True
    for role, marker in markers.items():
        receipt = allow_by_child.get(role)
        if receipt is None:
            prior_allow = False
            break
        if marker["started_at_unix_ns"] < receipt["decided_at_unix_ns"]:
            prior_allow = False
            break
        if marker["parent_work_id"] != receipt["request"]["parent_work_id"]:
            prior_allow = False
            break

    adversarial = {
        "replay_allow": (
            replay["decision"] == "DENY"
            and replay["reason"] == "REPLAYED_REQUEST"
            and "A" in markers
        ),
        "forged_parent": (
            unknown["decision"] == "DENY"
            and unknown["reason"] == "UNKNOWN_PARENT"
            and "G" not in markers
        ),
        "root_swap": (
            wrong_root["decision"] == "DENY"
            and wrong_root["reason"] == "ROOT_MISMATCH"
            and "H" not in markers
        ),
        "gate_unavailable": (
            down["launched"] is False
            and down["failure"] == "GATE_UNAVAILABLE"
            and not down_launches
        ),
        "launch_without_receipt": (
            bypass is False
            and not bypass_launches
            and "J" not in markers
        ),
    }

    state = gate.snapshot()
    fixed_ok = all(
        row["observed"] == row["expected"]
        and row["observed_reason"] == row["expected_reason"]
        and row["launched"] == (row["expected"] == "ALLOW")
        for row in frozen_results
    )

    checks = {
        "fixed_sequence": fixed_ok,
        "A_B_C_D_execute_exactly_once": set(markers) == {"A", "B", "C", "D"},
        "E_R2_F_do_not_execute": not any(x in markers for x in ("E", "R2", "F")),
        "exactly_four_allow_receipts": len(allow_receipts) == 4,
        "executions_have_prior_allow": prior_allow,
        "root_task_count_is_one": state["root_task_count"] == 1,
        "admitted_descendant_count_is_four": (
            state["admitted_descendant_count_total"] == 4
        ),
        "frozen_envelope_unchanged": (
            state["max_admitted_descendants_total"] == 4
        ),
        "all_adversarial_checks": all(adversarial.values()),
    }

    verdict = (
        "CASCADE_BOUNDARY_ENFORCED"
        if all(checks.values())
        else "CASCADE_BOUNDARY_STILL_ESCAPABLE"
    )

    result = {
        "schema": "airlock.cascade-001b.result.v1",
        "verdict": verdict,
        "git_head": head,
        "contract_sha256": sha256_file(contract_path),
        "cascade_module_sha256": sha256_file(repo / "src/airlock/cascade.py"),
        "worker_sha256": sha256_file(worker),
        "fixed_sequence": frozen_results,
        "execution_markers": markers,
        "durable_receipts": receipts,
        "receiver_state": state,
        "adversarial": adversarial,
        "pass_checks": checks,
        "claim_boundary": (
            "Deterministic interposable agent/task launcher proof only. "
            "No arbitrary OS subprocess containment, hard token/dollar cap, "
            "or live-provider enforcement claim."
        ),
    }

    result_path = out / "AIRLOCK_CASCADE_001B_RESULT.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out / "AIRLOCK_CASCADE_001B_RESULT.sha256").write_text(
        sha256_file(result_path) + "\n",
        encoding="utf-8",
    )

    print(verdict)
    print(f"Executed work: {sorted(markers)}")
    print(f"ALLOW receipts: {len(allow_receipts)}")
    print(
        "Admitted descendants: "
        f"{state['admitted_descendant_count_total']} / "
        f"{state['max_admitted_descendants_total']}"
    )
    print(f"Root tasks: {state['root_task_count']}")
    print(
        "Adversarial checks: "
        f"{sum(1 for v in adversarial.values() if v)}/{len(adversarial)}"
    )
    return 0 if verdict == "CASCADE_BOUNDARY_ENFORCED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
