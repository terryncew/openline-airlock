"""BOUNDED-CALL-001 qualification fixtures for the amended contract.

NOT EXECUTED. Importing this module runs nothing, and the file name matches
no test-discovery pattern, so broad discovery can never invoke Q1-Q6.
Each case encodes its amended-contract check exactly, against a real
durable log on real disk. Q2/Q3 use real child processes and real SIGKILL.
"""
import os
import signal
import tempfile
from decimal import Decimal
from pathlib import Path

from airlock import bounded_call as bc


def _tmp():
    return Path(tempfile.mkdtemp(prefix="bc001-"))


def _gate_fields(**overrides):
    fields = dict(max_iterations=3, budget=Decimal("500"), model="gpt-5.6-sol",
                  provider="openai-api", price_table_sha=bc.PRICE_TABLE_SHA,
                  hermes_pin=bc.HERMES_PIN)
    fields.update(overrides)
    return fields


def _kill_child_after(fn):
    pid = os.fork()
    if pid == 0:
        try:
            fn()
        finally:
            os.kill(os.getpid(), signal.SIGKILL)
    _, status = os.waitpid(pid, 0)
    assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL


def case_q1_gate_and_r_i():
    """Corrected R_i matches the hand-computed value; every refusal is terminal."""
    assert bc.compute_r_i(3) == Decimal("436.35552")
    bound = bc.precontact_gate(**_gate_fields())
    assert bound["r_i"] == "436.35552"
    assert bound["a_slot"] == 12 and bound["c_calls"] == 38
    assert bound["c_model"] == 1050000 and bound["output_cap"] == 32768
    assert bound["p_call"] == "11.48304"
    assert bound["prereg_sha"] == bc.PREREG_SHA
    assert bound["amendment_sha"] == bc.AMENDMENT_SHA
    refusals = [
        dict(budget=Decimal("1")),
        dict(model="gpt-9"),
        dict(provider="other"),
        dict(price_table_sha="0" * 64),
        dict(hermes_pin="0" * 40),
        dict(max_iterations=0),
    ]
    for bad in refusals:
        try:
            bc.precontact_gate(**_gate_fields(**bad))
        except bc.GateRefused:
            pass
        else:
            raise AssertionError("gate failed to refuse %r" % (bad,))


def case_q2_pre_arm_death_proven_not_entered():
    """Real SIGKILL after durable RESERVED, before CONTACT_ARMED."""
    tmp = _tmp()
    log = tmp / "log.jsonl"
    invocation = "q2-inv"
    bound = bc.precontact_gate(**_gate_fields())

    def child():
        bc.reserve(log, invocation, bound)

    _kill_child_after(child)
    assert bc.recover(log, invocation) == "PROVEN_NOT_ENTERED"


def case_q3_post_arm_death_indeterminate():
    """Real SIGKILL after CONTACT_ARMED, driver never invoked."""
    tmp = _tmp()
    log = tmp / "log.jsonl"
    invocation = "q3-inv"
    bound = bc.precontact_gate(**_gate_fields())

    def child():
        bc.reserve(log, invocation, bound)
        bc.arm_contact(log, invocation)

    _kill_child_after(child)
    assert bc.recover(log, invocation) == "INDETERMINATE"


def case_q4_signed_reconciliation():
    """Only correctly invocation-bound, untampered signatures verify."""
    tmp = _tmp()
    log = tmp / "log.jsonl"
    invocation = "q4-inv"
    bound = bc.precontact_gate(**_gate_fields())
    bc.reserve(log, invocation, bound)
    bc.arm_contact(log, invocation)
    auth = bc.ReconciliationAuthority(tmp / "rec.key")
    usage = {"input_tokens": 1000, "cache_read_tokens": 200000,
             "cache_write_tokens": 500, "output_tokens": 300}
    record = auth.reconcile(invocation_id=invocation, log_path=log,
                            usage=usage, prompt_tokens=201500)
    payload = auth.verify(record, invocation)
    assert payload["outcome"] == "EXECUTED"
    assert payload["envelope_violation"] is False
    tampered = {"alg": "HMAC-SHA256",
                "payload": dict(record["payload"], observed_charge="0.01"),
                "signature": record["signature"]}
    for bad, label in ((tampered, "tampered"), ({"payload": record["payload"]}, "unsigned"),
                       ("not-a-record", "non-mapping")):
        try:
            auth.verify(bad, invocation)
        except bc.EvidenceRejected:
            pass
        else:
            raise AssertionError("%s record verified" % label)
    try:
        auth.verify(record, "other-invocation")
    except bc.EvidenceRejected:
        pass
    else:
        raise AssertionError("wrong-invocation record verified")
    resolved = bc.resolve(log, invocation, auth)
    assert resolved["invocation_id"] == invocation


def case_q5_accounting_and_over_envelope():
    """Four-bucket accounting; over-envelope actual charge preserved as violation."""
    usage = {"input_tokens": 100000, "cache_read_tokens": 100000,
             "cache_write_tokens": 100000, "output_tokens": 1000}
    assert bc.price_usage(usage, 300000) == Decimal("1.91")
    assert bc.price_usage(usage, 200000) == Decimal("0.96")
    tmp = _tmp()
    log = tmp / "log.jsonl"
    invocation = "q5-inv"
    bound = bc.precontact_gate(**_gate_fields(max_iterations=1, budget=Decimal("200")))
    assert bound["r_i"] == "160.76256"
    bc.reserve(log, invocation, bound)
    bc.arm_contact(log, invocation)
    auth = bc.ReconciliationAuthority(tmp / "rec.key")
    over = {"input_tokens": 0, "cache_read_tokens": 0,
            "cache_write_tokens": 0, "output_tokens": 10 ** 9}
    record = auth.reconcile(invocation_id=invocation, log_path=log,
                            usage=over, prompt_tokens=10 ** 9)
    payload = record["payload"]
    assert payload["outcome"] == "EXECUTED"
    assert payload["envelope_violation"] is True
    assert Decimal(payload["observed_charge"]) == Decimal("30000")
    assert Decimal(payload["observed_charge"]) > Decimal(payload["r_i"])
    assert payload["r_i"] == "160.76256"


def case_q6_no_self_release():
    """Provider-shaped failures cannot release a CONTACT_ARMED reservation."""
    tmp = _tmp()
    log = tmp / "log.jsonl"
    invocation = "q6-inv"
    bound = bc.precontact_gate(**_gate_fields())
    bc.reserve(log, invocation, bound)
    bc.arm_contact(log, invocation)
    auth = bc.ReconciliationAuthority(tmp / "rec.key")

    class InfrastructureHalt(Exception):
        """PAYBACK-003 halt shape: must stay INDETERMINATE after CONTACT_ARMED."""

    try:
        raise InfrastructureHalt("simulated provider halt after CONTACT_ARMED")
    except InfrastructureHalt:
        pass
    assert bc.recover(log, invocation) == "INDETERMINATE"
    for fake in ({"invocation_id": invocation, "outcome": "PROVEN_NOT_ENTERED"},
                 InfrastructureHalt("not entered")):
        try:
            auth.verify(fake, invocation)
        except bc.EvidenceRejected:
            pass
        else:
            raise AssertionError("self-attestation released the reservation")
    assert bc.resolve(log, invocation, auth) is None
    log2 = tmp / "log2.jsonl"
    bc.reserve(log2, "q6-pre", bc.precontact_gate(**_gate_fields()))
    try:
        auth.reconcile(invocation_id="q6-pre", log_path=log2,
                        usage={b: 0 for b in bc.BUCKETS}, prompt_tokens=0)
    except bc.EvidenceRejected:
        pass
    else:
        raise AssertionError("reconcile signed without CONTACT_ARMED")


CASES = (case_q1_gate_and_r_i, case_q2_pre_arm_death_proven_not_entered,
         case_q3_post_arm_death_indeterminate, case_q4_signed_reconciliation,
         case_q5_accounting_and_over_envelope, case_q6_no_self_release)
