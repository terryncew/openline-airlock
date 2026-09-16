"""Spend ledger: reservations gate every call; settlement is local.

Budgets are enforced here, not by the provider. Every invocation posts a
reservation BEFORE contact. Settlement replaces the reservation with the
actual reconstructed cost. Missing usage -> unresolved exposure: the
reservation is RETAINED (never treated as a free failure).
"""
from __future__ import annotations

import json
import os
import time
import uuid


class InsufficientBudget(Exception):
    pass


class Ledger:
    def __init__(self, budget_usd: float, path: str, clock=None):
        self.budget = budget_usd
        self.path = path
        self.clock = clock or time.time
        self.entries: list[dict] = []
        self.reserved_total = 0.0   # currently encumbered
        self.settled_total = 0.0    # finalized actual spend
        self.unresolved_total = 0.0 # retained reservations, no usage
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self._replay(json.loads(line))

    def _replay(self, e: dict):
        self.entries.append(e)
        k = e["kind"]
        if k == "reserve":
            self.reserved_total += e["amount"]
        elif k == "settle":
            self.reserved_total -= e["reservation"]
            self.settled_total += e["actual"]
        elif k == "unresolved":
            self.reserved_total -= e["reservation"]
            self.unresolved_total += e["reservation"]

    def _append(self, e: dict):
        e = dict(e)
        e["t"] = self.clock()
        e["seq"] = len(self.entries)
        with open(self.path, "a") as f:
            f.write(json.dumps(e, sort_keys=True) + "\n")
        self._replay(e)
        return e

    @property
    def encumbered(self) -> float:
        return self.settled_total + self.unresolved_total + self.reserved_total

    def headroom(self) -> float:
        return self.budget - self.encumbered

    def reserve(self, amount: float, invocation_id: str, envelope: str) -> dict:
        if self.headroom() < amount - 1e-9:
            raise InsufficientBudget(
                f"ledger headroom ${self.headroom():.4f} < reservation ${amount:.4f}"
            )
        rid = "rsv_" + uuid.uuid4().hex[:12]
        return self._append({
            "kind": "reserve",
            "reservation_id": rid,
            "invocation_id": invocation_id,
            "envelope": envelope,
            "amount": amount,
        })

    def settle(self, reservation_id: str, invocation_id: str, reservation: float,
               actual: float, usage: dict, status: str) -> dict:
        return self._append({
            "kind": "settle",
            "reservation_id": reservation_id,
            "invocation_id": invocation_id,
            "reservation": reservation,
            "actual": actual,
            "usage": usage,
            "status": status,
        })

    def unresolved(self, reservation_id: str, invocation_id: str,
                   reservation: float, reason: str) -> dict:
        # Reservation retained as exposure; NOT a free failure.
        return self._append({
            "kind": "unresolved",
            "reservation_id": reservation_id,
            "invocation_id": invocation_id,
            "reservation": reservation,
            "reason": reason,
        })

    def note(self, kind: str, **fields) -> dict:
        return self._append({"kind": kind, **fields})

    def summary(self) -> dict:
        return {
            "budget": self.budget,
            "settled": round(self.settled_total, 6),
            "unresolved_retained": round(self.unresolved_total, 6),
            "reserved_open": round(self.reserved_total, 6),
            "encumbered": round(self.encumbered, 6),
            "headroom": round(self.headroom(), 6),
            "entries": len(self.entries),
        }
