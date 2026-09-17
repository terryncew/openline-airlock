"""BOUNDED-CALL-001 frozen qualification fixtures Q1-Q6.

DO NOT EXECUTE without explicit qualification authorization. This module
defines case functions only; importing it runs nothing, and executing it
as a script refuses.

File naming is deliberate: `cases.py` matches no test-discovery pattern
(`test*.py`), so broad discovery can never accidentally invoke Q1-Q6.

Each case encodes its frozen preregistration case exactly, against the real
DurableStore on real disk. Q2/Q3 use real child processes and real SIGKILL.
"""

import http.client
import multiprocessing as mp
import os
import signal
import tempfile
import time
from decimal import Decimal

from airlock import bounded_call as bc

PRICE_TABLE = (
    "/home/hatch/workspace/openline-airlock/.airlock/search-004/price-table.json"
)


def _envelope(**overrides):
    """Fixed fixture envelope. Hand-computed R_i = 41.18 (see case_q1)."""
    env = {
        "provider": "openai-api",
        "model": "gpt-5.6-sol",
        "tier": None,
        "price_table_path": PRICE_TABLE,
        "price_table_sha": bc.PRICE_TABLE_SHA256,
        "hermes_pin": bc.HERMES_PIN,
        "config_sha": "0" * 64,
        "max_iterations": 10,
        "max_api_attempts": 6,
        "max_compression_attempts": 3,
        "max_input_tokens": 100000,
        "max_output_tokens": 4000,
    }
    env.update(overrides)
    return env


def _store(prefix):
    return bc.DurableStore(tempfile.mkdtemp(prefix=prefix))


def case_q1():
    """Q1 -- gate and R_i correctness; every independent refusal.

    R_i = ((10+1)*6 + 2 + 3) * (100000 * 5.00e-6 + 4000 * 20.00e-6)
        = 71 * (0.5 + 0.08) = 41.18.
    """
    store = _store("bcq1")
    env = _envelope()
    table = bc.load_price_table(PRICE_TABLE, bc.PRICE_TABLE_SHA256)
    assert bc.compute_R_i(env, table) == Decimal("41.18")

    def refuses(overrides, exc):
        try:
            bc.reserve(store, _envelope(**overrides), budget_usd="100.00")
        except exc:
            return
        raise AssertionError("expected %s for %r" % (exc.__name__, overrides))

    refuses({"model": "gpt-4o"}, bc.EnvelopeInvalid)
    refuses({"provider": "other"}, bc.EnvelopeInvalid)
    refuses({"price_table_sha": "1" * 64}, bc.EnvelopeInvalid)
    refuses({"hermes_pin": "0" * 40}, bc.EnvelopeInvalid)
    refuses({"config_sha": "xyz"}, bc.EnvelopeInvalid)
    refuses({"max_output_tokens": None}, bc.EnvelopeInvalid)  # unbounded
    refuses({"max_iterations": 0}, bc.EnvelopeInvalid)  # unenforced
    try:
        bc.reserve(store, env, budget_usd="41.17")
    except bc.BudgetExceeded:
        pass
    else:
        raise AssertionError("expected BudgetExceeded")
    assert store.list_records() == [], "a refusal must leave no RESERVED record"

    call = bc.reserve(store, env, budget_usd="41.18")  # boundary: R_i == B passes
    rec = store.read(call.invocation_id)
    assert rec["state"] == bc.RESERVED and Decimal(rec["r_i"]) == Decimal("41.18")
    try:
        call.invoke(lambda: {"usage": {}})
    except bc.NotContactArmed:
        pass
    else:
        raise AssertionError("invoke before CONTACT_ARMED must be refused")


def _q2_child(store_dir, reserved_evt, invocation_id):
    from airlock import bounded_call as bc

    store = bc.DurableStore(store_dir)
    bc.reserve(store, _envelope(), budget_usd="100.00", invocation_id=invocation_id)
    reserved_evt.set()  # RESERVED is durable; CONTACT_ARMED never written
    time.sleep(60)


def case_q2():
    """Q2 -- real process death after RESERVED, before CONTACT_ARMED."""
    store_dir = tempfile.mkdtemp(prefix="bcq2")
    ctx = mp.get_context("spawn")
    reserved = ctx.Event()
    p = ctx.Process(target=_q2_child, args=(store_dir, reserved, "q2-case"))
    p.start()
    assert reserved.wait(timeout=20), "child never reached durable RESERVED"
    time.sleep(0.5)
    os.kill(p.pid, signal.SIGKILL)
    p.join(timeout=20)
    assert p.exitcode == -signal.SIGKILL
    store = bc.DurableStore(store_dir)
    assert bc.recover(store) == [("q2-case", bc.PROVEN_NOT_ENTERED)]
    rec = store.read("q2-case")
    assert rec["state"] == bc.PROVEN_NOT_ENTERED, rec
    assert rec["settled_usd"] == "0" and rec["encumbered"] is False


def _q3_child(store_dir, armed_evt, invocation_id):
    from airlock import bounded_call as bc

    store = bc.DurableStore(store_dir)
    call = bc.reserve(store, _envelope(), budget_usd="100.00",
                      invocation_id=invocation_id)
    call.arm()
    armed_evt.set()  # CONTACT_ARMED is durable on disk from here on

    def hang():
        time.sleep(60)

    call.invoke(hang)  # killed inside the provider execution window


def case_q3():
    """Q3 -- abrupt-death qualification across the real persistence boundary.

    A separate enclosing process durably writes RESERVED then CONTACT_ARMED,
    enters the fake-provider window, and is SIGKILLed before completion.
    Restart reads the durable bytes produced before death: the reservation
    must remain encumbered, classify INDETERMINATE, and never auto-release.
    """
    store_dir = tempfile.mkdtemp(prefix="bcq3")
    ctx = mp.get_context("spawn")
    armed = ctx.Event()
    p = ctx.Process(target=_q3_child, args=(store_dir, armed, "q3-case"))
    p.start()
    assert armed.wait(timeout=20), "child never reached durable CONTACT_ARMED"
    time.sleep(0.5)
    os.kill(p.pid, signal.SIGKILL)
    p.join(timeout=20)
    assert p.exitcode == -signal.SIGKILL
    store = bc.DurableStore(store_dir)
    assert bc.recover(store) == [("q3-case", bc.INDETERMINATE)]
    rec = store.read("q3-case")
    assert rec["state"] == bc.INDETERMINATE, rec
    assert rec["encumbered"] is True, "INDETERMINATE must stay encumbered"
    assert rec["settled_usd"] is None, "no automatic settlement allowed"
    assert bc.recover(store) == [], "second recovery must change nothing"
    assert store.read("q3-case")["encumbered"] is True


def case_q4():
    """Q4 -- exact PAYBACK-003 InfrastructureHalt escape shape.

    The worker raises InfrastructureHalt as a plain Exception from inside
    invoke(); the surrounding runner catches only narrower transport
    classes; the halt escapes that inner taxonomy. The BOUNDED-CALL outer
    boundary must still leave the correct durable classification from
    state (CONTACT_ARMED held, no terminal evidence -> INDETERMINATE).
    Exception class is diagnostics, not truth: the bare halt carries no
    attested pre-dispatch evidence, so the conservative bias applies.
    """
    class InfrastructureHalt(Exception):
        """PAYBACK-003 shape: documented 'callers must let it propagate'."""

    def worker():
        raise InfrastructureHalt("ECONNREFUSED pre-dispatch -> halt")

    store = _store("bcq4")
    call = bc.reserve(store, _envelope(), budget_usd="100.00",
                      invocation_id="q4-case")
    call.arm()
    escaped = None
    try:
        try:
            call.invoke(worker)
        except (OSError, http.client.HTTPException):
            pass  # runner's narrow taxonomy: must NOT catch the halt
    except InfrastructureHalt as e:
        escaped = e
    assert escaped is not None, "halt did not escape the narrow taxonomy"
    rec = store.read("q4-case")
    assert rec["state"] == bc.INDETERMINATE, rec
    assert rec["encumbered"] is True
    assert "InfrastructureHalt" in (rec["note"] or ""), "class kept as diagnostics"


def case_q5():
    """Q5 -- bounded happy-path settlement: settled == usage x table <= R_i."""
    store = _store("bcq5")
    call = bc.reserve(store, _envelope(), budget_usd="100.00",
                      invocation_id="q5-case")
    call.arm()
    out = call.invoke(lambda: {"usage": {"input_tokens": 1000,
                                        "output_tokens": 50},
                               "text": "ok"})
    assert out["text"] == "ok"
    rec = store.read("q5-case")
    assert rec["state"] == bc.EXECUTED, rec
    assert Decimal(rec["settled_usd"]) == Decimal("0.006"), rec
    assert Decimal(rec["settled_usd"]) <= Decimal(rec["r_i"])
    assert rec["encumbered"] is False


def case_q6():
    """Q6 -- provider error after possible entry + authenticated reconciliation.

    Also covers the adapter-attested pre-dispatch variant: a
    ProvenNotEnteredSignal carries the adapter's own attestation (authenticated
    evidence, not exception-class inference) -> PROVEN_NOT_ENTERED, released,
    and the signal still propagates.
    """
    store = _store("bcq6")
    call = bc.reserve(store, _envelope(), budget_usd="100.00",
                      invocation_id="q6-case")
    call.arm()

    def flaky():
        raise RuntimeError("connection reset mid-response")

    try:
        call.invoke(flaky)
    except RuntimeError:
        pass
    rec = store.read("q6-case")
    assert rec["state"] == bc.INDETERMINATE and rec["encumbered"] is True, rec

    # Unauthenticated inference never releases: wrong/missing evidence refused.
    call2 = bc.BoundedCall(store, "q6-case")
    for bad in ({"kind": "not_entered"},
                {"invocation_id": "q6-case", "kind": "maybe"}):
        try:
            call2.reconcile(bad)
        except bc.BoundedCallError:
            pass
        else:
            raise AssertionError("unauthenticated reconcile must fail: %r" % (bad,))
    assert store.read("q6-case")["encumbered"] is True

    # Authenticated independent evidence resolves: provider attests non-entry.
    evidence = {"invocation_id": "q6-case", "kind": "not_entered",
                "receipt": {"provider": "openai-api",
                            "note": "no request id issued"}}
    final = call2.reconcile(evidence)
    assert final["state"] == bc.PROVEN_NOT_ENTERED, final
    assert final["encumbered"] is False and final["settled_usd"] == "0"

    # Attested pre-dispatch variant: adapter proves no byte reached provider.
    call3 = bc.reserve(store, _envelope(), budget_usd="100.00",
                       invocation_id="q6b-case")
    call3.arm()

    def pre_dispatch():
        raise bc.ProvenNotEnteredSignal("dns failure before socket creation")

    try:
        call3.invoke(pre_dispatch)
    except bc.ProvenNotEnteredSignal:
        pass
    else:
        raise AssertionError("attested signal must propagate after terminalizing")
    rec3 = store.read("q6b-case")
    assert rec3["state"] == bc.PROVEN_NOT_ENTERED, rec3
    assert rec3["encumbered"] is False and rec3["settled_usd"] == "0"


if __name__ == "__main__":
    raise SystemExit(
        "BOUNDED-CALL-001 qualification is NOT authorized; do not execute.")
