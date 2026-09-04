from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable


OPERATIONS = {
    "SPAWN_DESCENDANT",
    "SPAWN_NEW_ROOT",
    "EXPAND_ALLOWANCE",
}


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    try:
        fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class CascadeGate:
    """Receiver-owned admission state for interposable agent/task spawning."""

    def __init__(
        self,
        state_dir: Path,
        *,
        root_id: str,
        max_admitted_descendants_total: int,
        max_root_tasks: int = 1,
        root_work_id: str = "ROOT",
    ) -> None:
        if max_admitted_descendants_total < 0:
            raise ValueError("max_admitted_descendants_total must be >= 0")
        if max_root_tasks != 1:
            raise ValueError("Cascade Gate v1 supports exactly one root task")

        self.state_dir = Path(state_dir)
        self.state_path = self.state_dir / "state.json"
        self.receipts_dir = self.state_dir / "receipts"
        self.receipts_dir.mkdir(parents=True, exist_ok=True)

        if self.state_path.exists():
            state = self._state()
            for key, expected in (
                ("root_id", root_id),
                ("root_work_id", root_work_id),
                ("max_admitted_descendants_total", max_admitted_descendants_total),
                ("max_root_tasks", max_root_tasks),
            ):
                if state.get(key) != expected:
                    raise ValueError(f"existing Cascade Gate state disagrees on {key}")
            return

        _atomic_json(
            self.state_path,
            {
                "schema": "airlock.cascade.state.v1",
                "root_id": root_id,
                "root_work_id": root_work_id,
                "max_admitted_descendants_total": max_admitted_descendants_total,
                "max_root_tasks": max_root_tasks,
                "root_task_count": 1,
                "admitted_descendant_count_total": 0,
                "decision_sequence": 0,
                "admission_sequence": 0,
                "known_work": {
                    root_work_id: {
                        "work_id": root_work_id,
                        "parent_work_id": None,
                        "root_id": root_id,
                        "admission_sequence": 0,
                    }
                },
                "first_receipt_by_request_id": {},
            },
        )

    def _state(self) -> dict[str, Any]:
        value = json.loads(self.state_path.read_text(encoding="utf-8"))
        if value.get("schema") != "airlock.cascade.state.v1":
            raise RuntimeError("unexpected Cascade Gate state schema")
        return value

    def _request(self, request: dict[str, Any]) -> dict[str, str]:
        required = (
            "request_id",
            "root_id",
            "parent_work_id",
            "operation",
            "requested_child_work_id",
        )
        out: dict[str, str] = {}
        for key in required:
            value = request.get(key)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{key} must be a non-empty string")
            out[key] = value
        if out["operation"] not in OPERATIONS:
            raise ValueError(f"unsupported operation {out['operation']!r}")
        return out

    def _receipt_name(self, sequence: int, request_id: str) -> str:
        digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:16]
        return f"{sequence:08d}-{digest}.json"

    def _new_receipt(
        self,
        state: dict[str, Any],
        request: dict[str, str],
        decision: str,
        reason: str | None,
    ) -> dict[str, Any]:
        return {
            "schema": "airlock.cascade.receipt.v1",
            "sequence": int(state["decision_sequence"]) + 1,
            "request": request,
            "request_sha256": hashlib.sha256(_canonical(request)).hexdigest(),
            "decision": decision,
            "reason": reason,
            "decided_at_unix_ns": time.time_ns(),
        }

    def _persist(
        self,
        state: dict[str, Any],
        receipt: dict[str, Any],
        *,
        first_use: bool,
    ) -> dict[str, Any]:
        name = self._receipt_name(
            int(receipt["sequence"]),
            receipt["request"]["request_id"],
        )
        receipt["receipt_file"] = name

        # Receipt first, state second. decide() does not return until both are
        # durable. Replays get a new receipt and never overwrite the original.
        _atomic_json(self.receipts_dir / name, receipt)
        state["decision_sequence"] = int(receipt["sequence"])
        request_id = receipt["request"]["request_id"]
        if first_use:
            state["first_receipt_by_request_id"][request_id] = name
        _atomic_json(self.state_path, state)
        return receipt

    def decide(self, request: dict[str, Any]) -> dict[str, Any]:
        req = self._request(request)
        state = self._state()
        request_id = req["request_id"]

        if request_id in state["first_receipt_by_request_id"]:
            return self._persist(
                state,
                self._new_receipt(state, req, "DENY", "REPLAYED_REQUEST"),
                first_use=False,
            )

        parent = state["known_work"].get(req["parent_work_id"])
        if parent is None:
            return self._persist(
                state,
                self._new_receipt(state, req, "DENY", "UNKNOWN_PARENT"),
                first_use=True,
            )

        if req["root_id"] != state["root_id"] or parent["root_id"] != req["root_id"]:
            return self._persist(
                state,
                self._new_receipt(state, req, "DENY", "ROOT_MISMATCH"),
                first_use=True,
            )

        if req["operation"] == "SPAWN_NEW_ROOT":
            return self._persist(
                state,
                self._new_receipt(state, req, "DENY", "NEW_ROOT_FORBIDDEN"),
                first_use=True,
            )

        if req["operation"] == "EXPAND_ALLOWANCE":
            return self._persist(
                state,
                self._new_receipt(
                    state,
                    req,
                    "DENY",
                    "ALLOWANCE_CHANGE_FORBIDDEN",
                ),
                first_use=True,
            )

        child = req["requested_child_work_id"]
        if child in state["known_work"]:
            return self._persist(
                state,
                self._new_receipt(state, req, "DENY", "REPLAYED_REQUEST"),
                first_use=True,
            )

        if (
            state["admitted_descendant_count_total"]
            >= state["max_admitted_descendants_total"]
        ):
            return self._persist(
                state,
                self._new_receipt(
                    state,
                    req,
                    "DENY",
                    "DESCENDANT_LIMIT_REACHED",
                ),
                first_use=True,
            )

        receipt = self._new_receipt(state, req, "ALLOW", None)
        state["admission_sequence"] += 1
        state["admitted_descendant_count_total"] += 1
        state["known_work"][child] = {
            "work_id": child,
            "parent_work_id": req["parent_work_id"],
            "root_id": req["root_id"],
            "admission_sequence": state["admission_sequence"],
        }
        receipt["admission_sequence"] = state["admission_sequence"]
        return self._persist(state, receipt, first_use=True)

    def verify_allow_receipt(
        self,
        receipt: dict[str, Any],
        *,
        requested_child_work_id: str,
    ) -> bool:
        if receipt.get("schema") != "airlock.cascade.receipt.v1":
            return False
        if receipt.get("decision") != "ALLOW":
            return False

        request = receipt.get("request")
        if not isinstance(request, dict):
            return False
        if request.get("requested_child_work_id") != requested_child_work_id:
            return False

        request_id = request.get("request_id")
        if not isinstance(request_id, str):
            return False

        state = self._state()
        first_name = state["first_receipt_by_request_id"].get(request_id)
        if not isinstance(first_name, str):
            return False

        path = self.receipts_dir / first_name
        if not path.exists():
            return False
        try:
            durable = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return False
        if durable != receipt:
            return False

        child = state["known_work"].get(requested_child_work_id)
        return (
            isinstance(child, dict)
            and child.get("root_id") == request.get("root_id")
            and child.get("parent_work_id") == request.get("parent_work_id")
        )

    def snapshot(self) -> dict[str, Any]:
        return self._state()


class CascadeLauncher:
    """Host-owned launcher: no durable ALLOW means no launch."""

    def __init__(self, gate: CascadeGate | None) -> None:
        self.gate = gate

    def request_and_launch(
        self,
        request: dict[str, Any],
        launch: Callable[[], Any],
    ) -> dict[str, Any]:
        if self.gate is None:
            return {
                "launched": False,
                "receipt": None,
                "failure": "GATE_UNAVAILABLE",
            }
        try:
            receipt = self.gate.decide(request)
        except Exception as exc:
            return {
                "launched": False,
                "receipt": None,
                "failure": "GATE_UNAVAILABLE",
                "error_type": type(exc).__name__,
            }

        if receipt["decision"] != "ALLOW":
            return {"launched": False, "receipt": receipt, "failure": None}

        launched = self.launch_with_receipt(
            receipt,
            request["requested_child_work_id"],
            launch,
        )
        return {
            "launched": launched,
            "receipt": receipt,
            "failure": None if launched else "ALLOW_RECEIPT_NOT_VERIFIABLE",
        }

    def launch_with_receipt(
        self,
        receipt: dict[str, Any],
        requested_child_work_id: str,
        launch: Callable[[], Any],
    ) -> bool:
        if self.gate is None:
            return False
        try:
            valid = self.gate.verify_allow_receipt(
                receipt,
                requested_child_work_id=requested_child_work_id,
            )
        except Exception:
            return False
        if not valid:
            return False
        launch()
        return True
