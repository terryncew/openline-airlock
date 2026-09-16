#!/usr/bin/env python3
"""COMPOUND-001 — precontact contract machinery (implementation only).

Frozen rapid-payback feasibility study. This single runtime module implements
the adjudication, accounting, and integrity machinery of the frozen contract:

- hard physical / calibration / strategy budget reservation arithmetic
- dual ledgers (physical study ledger, standalone strategy ledgers)
- provisional lineage selection rule
- 9-task / 6-task repayment arithmetic, break-even, pooled economics
- task partition schedule generation with non-overlap verification
- fork / immutability / fresh-worker-state integrity checks
- preregistration hash-binding verification
- precontact feasibility gates (budget enforcement, complexity)

Cost-metering semantics mirror experiments/airlock-search-004/run_search_004.py
(token classes, total-consistency, model/provider alias, service-tier, and
long-context aggregate guard; provider estimated price is untrusted metadata).

No scientific contact is performed. No paid model invocation, no live
calibration, no task execution. The precontact budget-enforcement feasibility
gate returns NO_GO_BUDGET_ENFORCEMENT: static and config inspection of the
repository's Hermes/provider invocation path shows no enforceable
per-invocation billable maximum (no max output tokens, no bounded retry or
API-call count; timeout alone does not bound tokens), and the frozen contract
forbids building a new provider gateway to rescue the study.
"""
from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path

from airlock.util import canonical_json_bytes, sha256_bytes, sha256_file

ROOT = Path(__file__).resolve().parents[2]
AIRLOCK_DIR = ROOT / ".airlock" / "compound-001"
PREREG_PATH = AIRLOCK_DIR / "preregistration.json"
PRICE_TABLE_PATH = AIRLOCK_DIR / "price-table.json"
BASELINE_METHOD_PATH = AIRLOCK_DIR / "baseline-method.md"
TASK_SCHEDULE_PATH = AIRLOCK_DIR / "task-schedule.json"

# ---------------- frozen study constants ----------------
PHYSICAL_CAP = Decimal("50.00")
CALIBRATION_CAP = Decimal("5.00")
STRATEGY_T_MAX = Decimal("8.00")
REPETITIONS = 3
GENERATIONS = 3
MEASUREMENT_PER_GENERATION = 3
MEASUREMENT_PER_REPETITION = 9
SECOND_ACQ_DOWNSTREAM_TASKS = 6
FAMILIES = ("logic", "interface", "config")
DISCOVERY_PER_ACQUISITION = 3
PROMOTION_PER_ACQUISITION = 3
PAID_CONCURRENCY = 1
PROMOTION_ACCEPT_MIN = 2

# ---------------- terminal vocabulary (frozen) ----------------
NO_GO_BUDGET_ENFORCEMENT = "NO_GO_BUDGET_ENFORCEMENT"
NO_GO_CALIBRATION_FEASIBILITY = "NO_GO_CALIBRATION_FEASIBILITY"
NO_GO_IMPLEMENTATION_COMPLEXITY = "NO_GO_IMPLEMENTATION_COMPLEXITY"
ABORT_BUDGET_ENFORCEMENT_FAILURE = "ABORT_BUDGET_ENFORCEMENT_FAILURE"
ABORT_COST_TELEMETRY_FAILURE = "ABORT_COST_TELEMETRY_FAILURE"
ABORT_EXPERIMENT_INTEGRITY_FAILURE = "ABORT_EXPERIMENT_INTEGRITY_FAILURE"
ABORT_EXECUTION_FAILURE = "ABORT_EXECUTION_FAILURE"
ABORT_BUDGET_EXCEEDED = "ABORT_BUDGET_EXCEEDED"
INCONCLUSIVE_INCOMPLETE_REPETITIONS = "INCONCLUSIVE_INCOMPLETE_REPETITIONS"
PAYBACK_NOT_OBSERVED_WITHIN_NINE_TASK_HORIZON = "PAYBACK_NOT_OBSERVED_WITHIN_NINE_TASK_HORIZON"
ONE_TIME_AMORTIZATION_OBSERVED = "ONE_TIME_AMORTIZATION_OBSERVED_COMPOUNDING_NOT_ESTABLISHED"
SUCCESSIVE_NOT_ESTABLISHED = "SUCCESSIVE_IMPROVEMENT_ADVANTAGE_NOT_ESTABLISHED"
SUCCESSIVE_OBSERVED = "SUCCESSIVE_IMPROVEMENT_ECONOMIC_ADVANTAGE_OBSERVED"
STRATEGY_CONTACT_THRESHOLD_REACHED = "STRATEGY_CONTACT_THRESHOLD_REACHED"
PROVISIONAL_ACCEPT = "PROVISIONALLY_ACCEPTED_FOR_LINEAGE"
REJECT = "REJECT"


class ContractError(RuntimeError):
    """Deterministic contract violation (maps to a frozen terminal status)."""


def _usd(value: object) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ContractError(f"INVALID_USD:{value}") from exc
    if d < 0:
        raise ContractError(f"NEGATIVE_USD:{value}")
    return d.quantize(Decimal("0.0000001"))


# ---------------- cost metering (SEARCH-004 semantics) ----------------
TOKEN_FIELDS = (
    "input_tokens", "output_tokens", "cache_read_tokens",
    "cache_write_tokens", "reasoning_tokens", "total_tokens",
)


def load_price_table() -> dict:
    table = json.loads(PRICE_TABLE_PATH.read_text())
    if table.get("schema") != "airlock.compound-001.price-table.v1":
        raise ContractError("PRICE_TABLE_SCHEMA")
    return table


def _usage_int(usage: dict, key: str) -> int:
    value = usage.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ContractError(f"INVALID_{key.upper()}")
    return value


def reconstruct_cost(usage: dict, table: dict) -> dict:
    """Reconstruct direct USD from raw provider usage. Mirrors SEARCH-004."""
    if not isinstance(usage, dict):
        raise ContractError("USAGE_NOT_OBJECT")
    known = set(TOKEN_FIELDS) | {"api_calls", "model", "provider", "service_tier"}
    for key, value in usage.items():
        if key.endswith("_tokens") and key not in TOKEN_FIELDS and value not in (None, 0):
            raise ContractError(f"UNMAPPED_TOKEN_CLASS:{key}")
    vals = {k: _usage_int(usage, k) for k in TOKEN_FIELDS}
    api_calls = _usage_int(usage, "api_calls")
    if api_calls <= 0:
        raise ContractError("ZERO_API_CALLS")
    prompt_tokens = vals["input_tokens"] + vals["cache_read_tokens"] + vals["cache_write_tokens"]
    if vals["total_tokens"] != prompt_tokens + vals["output_tokens"]:
        raise ContractError("TOKEN_TOTAL_MISMATCH")
    if vals["total_tokens"] <= 0 or prompt_tokens <= 0:
        raise ContractError("ZERO_RECORDED_TOKENS")
    if vals["reasoning_tokens"] > vals["output_tokens"]:
        raise ContractError("REASONING_EXCEEDS_OUTPUT")
    if usage.get("model") not in set(table["model_aliases"]):
        raise ContractError(f"UNMAPPED_MODEL:{usage.get('model')}")
    if usage.get("provider") not in set(table["provider_aliases"]):
        raise ContractError(f"UNMAPPED_PROVIDER:{usage.get('provider')}")
    if usage.get("service_tier") is not table.get("service_tier_required"):
        raise ContractError(f"UNMAPPED_SERVICE_TIER:{usage.get('service_tier')}")
    threshold = int(table["long_context"]["threshold_prompt_tokens_per_request"])
    if prompt_tokens > threshold:
        raise ContractError("LONG_CONTEXT_TIER_AMBIGUOUS_FROM_AGGREGATE_USAGE")
    rates = table["rates_per_million_tokens"]
    try:
        cost = (
            Decimal(vals["input_tokens"]) * Decimal(rates["input_tokens"])
            + Decimal(vals["cache_read_tokens"]) * Decimal(rates["cache_read_tokens"])
            + Decimal(vals["cache_write_tokens"]) * Decimal(rates["cache_write_tokens"])
            + Decimal(vals["output_tokens"]) * Decimal(rates["output_tokens"])
        ) / Decimal(1_000_000)
    except (InvalidOperation, KeyError) as exc:
        raise ContractError("INVALID_FROZEN_PRICE_TABLE") from exc
    if cost <= 0:
        raise ContractError("ZERO_METERED_COST")
    return {
        "schema": "airlock.compound-001.metered-usage.v1",
        "usd": _usd(cost),
        "price_table_sha256": sha256_file(PRICE_TABLE_PATH),
    }


# ---------------- budget reservation ----------------
def reservation_fits(settled: Decimal, inflight: list, r_i: Decimal, cap: Decimal) -> bool:
    """settled + all in-flight reservations + R_i <= cap, else the call may not start."""
    total = _usd(settled) + sum((_usd(r) for r in inflight), Decimal(0)) + _usd(r_i)
    return total <= _usd(cap)


def strategy_threshold(c_max: Decimal) -> Decimal:
    """T = round_up_to_$0.25(30 * c_max)."""
    raw = _usd(c_max) * 30
    steps = (raw / Decimal("0.25")).to_integral_value(rounding=ROUND_CEILING)
    return _usd(steps * Decimal("0.25"))


def check_settle(actual: Decimal, reserved: Decimal) -> None:
    """Actual reconstructed charge exceeding its reservation aborts the study."""
    if _usd(actual) > _usd(reserved):
        raise ContractError(ABORT_BUDGET_ENFORCEMENT_FAILURE)


class PhysicalLedger:
    """Whole-study physical dollars. The common first acquisition is paid once."""

    def __init__(self) -> None:
        self.settled = Decimal("0")
        self.inflight: list = []
        self.calibration_settled = Decimal("0")
        self.calibration_inflight: list = []

    def reserve(self, r_i: Decimal, *, calibration: bool = False) -> None:
        r_i = _usd(r_i)
        if not reservation_fits(self.settled, self.inflight, r_i, PHYSICAL_CAP):
            raise ContractError(ABORT_BUDGET_EXCEEDED)
        if calibration:
            if not reservation_fits(
                self.calibration_settled, self.calibration_inflight, r_i, CALIBRATION_CAP
            ):
                raise ContractError(NO_GO_CALIBRATION_FEASIBILITY)
            self.calibration_inflight.append(r_i)
        self.inflight.append(r_i)

    def settle(self, reserved: Decimal, actual: Decimal, *, calibration: bool = False) -> None:
        check_settle(actual, reserved)
        self.inflight.remove(_usd(reserved))
        self.settled = _usd(self.settled + _usd(actual))
        if calibration:
            self.calibration_inflight.remove(_usd(reserved))
            self.calibration_settled = _usd(self.calibration_settled + _usd(actual))


class StrategyLedger:
    """Standalone economics of choosing one strategy. B and C each carry full D1."""

    def __init__(self, name: str, threshold: Decimal) -> None:
        self.name = name
        self.threshold = _usd(threshold)
        self.settled = Decimal("0")
        self.debt = Decimal("0")
        self.inflight: list = []

    def allocate_debt(self, amount: Decimal) -> None:
        self.debt = _usd(self.debt + _usd(amount))

    def reserve(self, r_i: Decimal) -> None:
        r_i = _usd(r_i)
        exposure = self.settled + self.debt + sum(self.inflight, Decimal(0)) + r_i
        if exposure > self.threshold:
            raise ContractError(STRATEGY_CONTACT_THRESHOLD_REACHED)
        self.inflight.append(r_i)

    def settle(self, reserved: Decimal, actual: Decimal) -> None:
        check_settle(actual, reserved)
        self.inflight.remove(_usd(reserved))
        self.settled = _usd(self.settled + _usd(actual))

    def all_in(self) -> Decimal:
        return _usd(self.settled + self.debt)


# ---------------- task partition schedule ----------------
def _task_id(rep: int, partition: str, family: str, idx: int) -> str:
    return f"C001-R{rep}-{partition}-{family}-{idx}"


def build_schedule(seed_commitment: str) -> dict:
    """Deterministic frozen task-ID schedule. Matched A/B/C share task IDs per rep."""
    if not seed_commitment or len(seed_commitment) < 16:
        raise ContractError("INVALID_SEED_COMMITMENT")
    schedule = {"schema": "airlock.compound-001.task-schedule.v1",
                "seed_commitment": seed_commitment, "repetitions": {}}
    for rep in range(1, REPETITIONS + 1):
        parts: dict = {"calibration": [], "discovery_1": [], "promotion_1": [],
                       "discovery_2": [], "promotion_2": [],
                       "measurement_g1": [], "measurement_g2": [], "measurement_g3": []}
        for i, fam in enumerate(FAMILIES):
            parts["calibration"].append(_task_id(rep, "CAL", fam, i))
        for i, fam in enumerate(FAMILIES):
            parts["discovery_1"].append(_task_id(rep, "D1", fam, i))
            parts["promotion_1"].append(_task_id(rep, "P1", fam, i))
        for i, fam in enumerate(FAMILIES):
            parts["discovery_2"].append(_task_id(rep, "D2", fam, i))
            parts["promotion_2"].append(_task_id(rep, "P2", fam, i))
        for gen in (1, 2, 3):
            for i, fam in enumerate(FAMILIES):
                parts[f"measurement_g{gen}"].append(_task_id(rep, f"G{gen}", fam, i))
        schedule["repetitions"][str(rep)] = parts
    return schedule


def verify_partitions(schedule: dict) -> None:
    """No task may cross partitions; measurement counts are exact; no 4th generation."""
    for rep, parts in schedule["repetitions"].items():
        if set(parts) != {"calibration", "discovery_1", "promotion_1", "discovery_2",
                          "promotion_2", "measurement_g1", "measurement_g2",
                          "measurement_g3"}:
            raise ContractError(f"PARTITION_SHAPE:{rep}")
        seen: set = set()
        for name, ids in parts.items():
            for tid in ids:
                if tid in seen:
                    raise ContractError(f"TASK_PARTITION_LEAK:{tid}")
                seen.add(tid)
        for gen in (1, 2, 3):
            if len(parts[f"measurement_g{gen}"]) != MEASUREMENT_PER_GENERATION:
                raise ContractError(f"MEASUREMENT_COUNT:{rep}:g{gen}")
        total = sum(len(parts[f"measurement_g{g}"]) for g in (1, 2, 3))
        if total != MEASUREMENT_PER_REPETITION:
            raise ContractError(f"MEASUREMENT_TOTAL:{rep}")


# ---------------- lineage: fork, immutability, fresh state ----------------
def method_hash(artifact: dict) -> str:
    return sha256_bytes(canonical_json_bytes(artifact))


def fork_first_acquisition(common_state: dict) -> tuple:
    """B and C fork from the exact same post-first-acquisition state."""
    frozen = json.loads(json.dumps(common_state, sort_keys=True))
    return frozen, json.loads(json.dumps(common_state, sort_keys=True))


def check_b_immutable(fork_hash: str, current_hash: str) -> None:
    if fork_hash != current_hash:
        raise ContractError(f"{ABORT_EXPERIMENT_INTEGRITY_FAILURE}:B_MUTATED_AFTER_FORK")


def check_c_no_rejected_inheritance(c_hash: str, rejected_hash: str | None,
                                    promoted_hash: str | None) -> None:
    if rejected_hash is not None and c_hash == rejected_hash:
        raise ContractError(f"{ABORT_EXPERIMENT_INTEGRITY_FAILURE}:C_INHERITED_REJECTED")
    if promoted_hash is not None and c_hash != promoted_hash:
        raise ContractError(f"{ABORT_EXPERIMENT_INTEGRITY_FAILURE}:C_LINEAGE_MISMATCH")


class WorkerSessions:
    """Every model contact begins with fresh worker state; nothing crosses calls."""

    def __init__(self) -> None:
        self._issued: set = set()
        self._counter = 0

    def fresh(self) -> str:
        self._counter += 1
        sid = f"worker-{self._counter:06d}"
        if sid in self._issued:
            raise ContractError(f"{ABORT_EXPERIMENT_INTEGRITY_FAILURE}:WORKER_ID_REUSE")
        self._issued.add(sid)
        return sid


# ---------------- provisional lineage selection ----------------
def provisional_select(parent: dict, candidate: dict) -> str:
    """Small selection gate only. Authorizes PROVISIONALLY_ACCEPTED_FOR_LINEAGE."""
    for side in (parent, candidate):
        for key in ("verified", "cost_usd", "telemetry_complete", "quality_ok",
                    "method_hash", "within_method_bound"):
            if key not in side:
                raise ContractError(f"PROMOTION_RECORD_INCOMPLETE:{key}")
    if not candidate["telemetry_complete"] or not parent["telemetry_complete"]:
        return REJECT
    if not candidate["quality_ok"]:
        return REJECT
    if not candidate["within_method_bound"]:
        return REJECT
    if candidate["verified"] < PROMOTION_ACCEPT_MIN:
        return REJECT
    if candidate["verified"] < parent["verified"]:
        return REJECT
    p_cost, c_cost = _usd(parent["cost_usd"]), _usd(candidate["cost_usd"])
    if p_cost <= 0 or c_cost <= 0:
        return REJECT
    parent_vpd = Decimal(parent["verified"]) / p_cost
    cand_vpd = Decimal(candidate["verified"]) / c_cost
    if not cand_vpd > parent_vpd:
        return REJECT
    return PROVISIONAL_ACCEPT


# ---------------- economic arithmetic ----------------
def repayment_holds(debt: Decimal, downstream_new: Decimal, downstream_old: Decimal) -> bool:
    """D + C_new(n) <= C_old(n): the improvement repays inside the horizon."""
    return _usd(debt) + _usd(downstream_new) <= _usd(downstream_old)


def per_task_saving_needed(debt: Decimal, tasks: int) -> Decimal:
    """a - b >= D / n: minimum average per-task saving to repay in n tasks."""
    return _usd(debt) / tasks


def impossible_even_free(debt: Decimal, old_cost: Decimal) -> bool:
    """D > C_old(n): cannot repay even if downstream execution became free."""
    return _usd(debt) > _usd(old_cost)


def dollars_per_verified(cost: Decimal, verified: int) -> Decimal | float:
    if verified < 0:
        raise ContractError("NEGATIVE_VERIFIED")
    if verified == 0:
        return float("inf")
    return _usd(cost) / verified


def compare_strategies(x_cost: Decimal, x_v: int, y_cost: Decimal, y_v: int) -> str:
    """Frozen unequal-output / zero-success rules. Returns a verdict token."""
    if x_v == 0 and y_v == 0:
        return "NO_CLAIM_BOTH_ZERO"
    if x_v == 0 or y_v == 0:
        return "NO_CLAIM_ZERO_OUTPUT_CANNOT_WIN"
    if x_v < y_v:
        return "X_CANNOT_CLAIM_OUTPUT_DEFICIT"
    if x_v == y_v:
        return "COMPARE_ALL_IN_COST" if _usd(x_cost) < _usd(y_cost) else "NO_ADVANTAGE"
    # x_v > y_v: advantage only if X reaches Y's output count at no greater cost.
    return "EXTRA_OUTPUT_REPORT_SEPARATELY"


def break_even(costs_x: list, costs_y: list) -> int | None:
    """Earliest common k with C_X(k) <= C_Y(k) that never reverses later; else None."""
    common = min(len(costs_x), len(costs_y))
    candidate = None
    for k in range(1, common + 1):
        if _usd(costs_x[k - 1]) <= _usd(costs_y[k - 1]):
            if candidate is None:
                candidate = k
        elif candidate is not None:
            return None  # transient crossover reversed: not break-even
    return candidate


def pooled_economics(costs: list, verified_counts: list) -> dict:
    """POOL SUMS. Never average per-repetition ratios."""
    total_cost = sum((_usd(c) for c in costs), Decimal(0))
    total_verified = sum(int(v) for v in verified_counts)
    return {
        "pooled_cost": _usd(total_cost),
        "pooled_verified": total_verified,
        "pooled_cost_per_verified": dollars_per_verified(total_cost, total_verified),
    }


def completed_repetition(record: dict) -> bool:
    required = ("first_acquisition_terminal", "second_acquisition_terminal",
                "a_measured", "b_measured", "c_measured",
                "costs_reconciled", "hashes_reconciled", "no_abort")
    return all(record.get(k) is True for k in required) and record.get("a_tasks") == 9 \
        and record.get("b_tasks") == 9 and record.get("c_tasks") == 9


def study_claim_status(rep_records: list) -> str:
    completed = [r for r in rep_records if completed_repetition(r)]
    if len(completed) < REPETITIONS:
        return INCONCLUSIVE_INCOMPLETE_REPETITIONS
    return "READY_FOR_ECONOMIC_ADJUDICATION"


# ---------------- precontact feasibility gates ----------------
def budget_enforcement_feasible() -> tuple:
    """Can a finite conservative R_i be proven and enforced for the paid path?

    The repository's paid provider invocation is `hermes -z <prompt>
    --usage-file <path>` (see .airlock/search-004/worker.py and the
    search-004 PUBLIC_CONFIG provider command). Static and config inspection
    finds: no max output/completion tokens passthrough, no per-invocation
    API-call or retry bound in the controller, and timeout alone does not
    bound billable tokens (a call can emit up to the context maximum inside
    the timeout). A finite conservative R_i therefore cannot be proven without
    building a new provider gateway, which the frozen contract forbids.
    """
    return (False, NO_GO_BUDGET_ENFORCEMENT,
            "no enforceable per-invocation billable maximum in hermes path")


def runtime_modules() -> list:
    return sorted(p for p in Path(__file__).parent.glob("*.py")
                  if p.name != "__init__.py")


def effective_loc(path: Path) -> int:
    count = 0
    for line in path.read_text().splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            count += 1
    return count


def complexity_gate() -> dict:
    mods = runtime_modules()
    loc = {p.name: effective_loc(p) for p in mods}
    total = sum(loc.values())
    ok = len(mods) <= 2 and total <= 500
    return {"modules": [p.name for p in mods], "loc_per_module": loc,
            "total_loc": total,
            "status": "PASS" if ok else NO_GO_IMPLEMENTATION_COMPLEXITY}


def precontact_feasibility() -> dict:
    feasible, status, reason = budget_enforcement_feasible()
    gate = complexity_gate()
    if not feasible:
        return {"scientific_contact": "FORBIDDEN", "status": status,
                "budget_reason": reason, "complexity": gate}
    if gate["status"] != "PASS":
        return {"scientific_contact": "FORBIDDEN", "status": gate["status"],
                "budget_reason": reason, "complexity": gate}
    return {"scientific_contact": "PERMITTED", "status": "READY_PRECONTACT",
            "budget_reason": reason, "complexity": gate}


# ---------------- preregistration binding verification ----------------
PREREG_REQUIRED = (
    "schema", "study", "question", "repetitions", "tracks", "generations",
    "measurement_tasks_per_strategy_per_repetition", "task_families",
    "partitions", "physical_cap_usd", "calibration_cap_usd",
    "strategy_threshold_formula", "strategy_threshold_max_usd",
    "paid_concurrency", "price_table_sha256", "baseline_method_sha256",
    "task_schedule_sha256", "seed_commitment", "terminal_vocabulary",
    "causal_boundary", "complexity_gate", "reservation_rule",
    "accounting_rule", "positive_claim_requirements",
)


def verify_prereg() -> list:
    problems = []
    try:
        prereg = json.loads(PREREG_PATH.read_text())
    except Exception as exc:
        return [f"PREREG_UNREADABLE:{exc}"]
    for key in PREREG_REQUIRED:
        if key not in prereg:
            problems.append(f"PREREG_MISSING:{key}")
    if problems:
        return problems
    if prereg.get("schema") != "airlock.compound-001.preregistration.v1":
        problems.append("PREREG_SCHEMA")
    bindings = {
        "price_table_sha256": PRICE_TABLE_PATH,
        "baseline_method_sha256": BASELINE_METHOD_PATH,
        "task_schedule_sha256": TASK_SCHEDULE_PATH,
    }
    for key, path in bindings.items():
        if not path.is_file():
            problems.append(f"BINDING_MISSING_FILE:{path.name}")
        elif prereg.get(key) != sha256_file(path):
            problems.append(f"BINDING_MISMATCH:{key}")
    if prereg.get("physical_cap_usd") != "50.00":
        problems.append("CAP_MISMATCH:physical")
    if prereg.get("calibration_cap_usd") != "5.00":
        problems.append("CAP_MISMATCH:calibration")
    if prereg.get("repetitions") != REPETITIONS or prereg.get("generations") != GENERATIONS:
        problems.append("SHAPE_MISMATCH")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="COMPOUND-001 precontact contract checks")
    parser.add_argument("--check-feasibility", action="store_true")
    parser.add_argument("--verify-prereg", action="store_true")
    parser.add_argument("--complexity", action="store_true")
    args = parser.parse_args()
    out: dict = {}
    if args.check_feasibility:
        out["feasibility"] = precontact_feasibility()
    if args.verify_prereg:
        problems = verify_prereg()
        out["prereg"] = {"problems": problems, "ok": not problems}
    if args.complexity:
        out["complexity"] = complexity_gate()
    if not out:
        out = {"feasibility": precontact_feasibility(),
               "prereg": {"problems": verify_prereg(),
                          "ok": not verify_prereg()},
               "complexity": complexity_gate()}
    print(json.dumps(out, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
