"""Unit tests for the Q5 execution ledger state machine.

State: ``prepared -> started | spawn_failed``. Resume classification:

- journaled -> ``committed`` (skip);
- no prepared record -> ``fresh``;
- prepared + matching definitive ``spawn_failed`` -> ``retry_allowed``;
- started + verified completion -> ``recoverable``;
- started without verified completion -> fail closed;
- prepared without definitive ``spawn_failed`` -> fail closed.
"""

import json

import pytest

import execution_ledger as ledger
from execution_ledger import UncertainExecution


OBS = "obs-unit-1"
PHASE = "discovery"


def _bindings(tx, bindings):
    return dict(txid=tx.txid, observation_id=OBS, phase=PHASE,
                receipt_sha256=bindings["receipt_sha256"],
                code_hashes=bindings["code_hashes"])


def _classify(work_dir, tx, bindings, obs=OBS, phase=PHASE):
    return ledger.classify(
        work_dir=work_dir, tx=tx, observation_id=obs, phase=phase,
        receipt_sha256=bindings["receipt_sha256"],
        code_hashes=bindings["code_hashes"])


def test_fresh_when_no_records(work_dir, tx, bindings):
    status, payload = _classify(work_dir, tx, bindings)
    assert status == "fresh"
    assert payload == {"attempt": 1}


def test_prepared_then_spawn_failed_allows_retry(work_dir, tx, bindings):
    kw = _bindings(tx, bindings)
    ledger.record_prepared(work_dir=work_dir, attempt=1, pid=1234, **kw)
    ledger.record_spawn_failed(work_dir=work_dir, attempt=1,
                               error="FileNotFoundError: boom", **kw)
    status, payload = _classify(work_dir, tx, bindings)
    assert status == "retry_allowed"
    assert payload == {"attempt": 2}


def test_prepared_without_spawn_failed_fails_closed(work_dir, tx, bindings):
    kw = _bindings(tx, bindings)
    ledger.record_prepared(work_dir=work_dir, attempt=1, pid=1234, **kw)
    with pytest.raises(UncertainExecution, match="cannot prove"):
        _classify(work_dir, tx, bindings)


def test_prepared_with_stale_spawn_failed_fails_closed(
        work_dir, tx, bindings):
    # Attempt 1 provably never spawned; attempt 2 was prepared and then
    # the coordinator died. The old spawn_failed answers attempt 1, not
    # attempt 2: fail closed.
    kw = _bindings(tx, bindings)
    ledger.record_spawn_failed(work_dir=work_dir, attempt=1,
                               error="FileNotFoundError: boom", **kw)
    ledger.record_prepared(work_dir=work_dir, attempt=2, pid=1234, **kw)
    with pytest.raises(UncertainExecution, match="cannot prove"):
        _classify(work_dir, tx, bindings)


def test_corrupt_spawn_failed_fails_closed(work_dir, tx, bindings):
    kw = _bindings(tx, bindings)
    ledger.record_prepared(work_dir=work_dir, attempt=1, pid=1234, **kw)
    bad = (work_dir / "artifacts" / "execution_ledger"
           / f"{OBS}.spawn_failed.json")
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{not json")
    with pytest.raises(UncertainExecution):
        _classify(work_dir, tx, bindings)


def test_started_without_completion_fails_closed(work_dir, tx, bindings):
    kw = _bindings(tx, bindings)
    ledger.record_prepared(work_dir=work_dir, attempt=1, pid=1234, **kw)
    ledger.record_started(work_dir=work_dir, attempt=1, child_pid=999,
                          exec_nonce="abc123", **kw)
    with pytest.raises(UncertainExecution, match="without verified"):
        _classify(work_dir, tx, bindings)


def test_started_with_verified_completion_recovers(work_dir, tx, bindings):
    kw = _bindings(tx, bindings)
    ledger.record_prepared(work_dir=work_dir, attempt=1, pid=1234, **kw)
    ledger.record_started(work_dir=work_dir, attempt=1, child_pid=999,
                          exec_nonce="abc123", **kw)
    outcome = b'{"first": "exact-bytes"}'
    digest = ledger.write_outcome(work_dir=work_dir,
                                  observation_id=OBS,
                                  outcome_bytes=outcome)
    ledger.record_completion(work_dir=work_dir, outcome_digest=digest,
                             **kw)
    status, payload = _classify(work_dir, tx, bindings)
    assert status == "recoverable"
    assert payload["outcome_bytes"] == outcome
    assert payload["evidence"]["schema"] == \
        ledger.ADOPT_EVIDENCE_SCHEMA
    assert payload["evidence"]["outcome_digest"] == digest


def test_started_with_missing_outcome_fails_closed(work_dir, tx, bindings):
    kw = _bindings(tx, bindings)
    ledger.record_prepared(work_dir=work_dir, attempt=1, pid=1234, **kw)
    ledger.record_started(work_dir=work_dir, attempt=1, child_pid=999,
                          exec_nonce="abc123", **kw)
    ledger.record_completion(
        work_dir=work_dir, outcome_digest="0" * 64, **kw)
    with pytest.raises(UncertainExecution, match="outcome bytes missing"):
        _classify(work_dir, tx, bindings)


def test_started_with_digest_mismatch_fails_closed(work_dir, tx, bindings):
    kw = _bindings(tx, bindings)
    ledger.record_prepared(work_dir=work_dir, attempt=1, pid=1234, **kw)
    ledger.record_started(work_dir=work_dir, attempt=1, child_pid=999,
                          exec_nonce="abc123", **kw)
    ledger.write_outcome(work_dir=work_dir, observation_id=OBS,
                         outcome_bytes=b"tampered")
    ledger.record_completion(
        work_dir=work_dir, outcome_digest="f" * 64, **kw)
    with pytest.raises(UncertainExecution, match="do not match"):
        _classify(work_dir, tx, bindings)


def test_corrupt_prepared_fails_closed(work_dir, tx, bindings):
    bad = (work_dir / "artifacts" / "execution_ledger"
           / f"{OBS}.prepared.json")
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{not json")
    with pytest.raises(UncertainExecution, match="unreadable"):
        _classify(work_dir, tx, bindings)


def test_foreign_txid_binding_fails_closed(work_dir, tx, bindings):
    kw = _bindings(tx, bindings)
    kw["txid"] = "forged-txid"
    ledger.record_prepared(work_dir=work_dir, attempt=1, pid=1234, **kw)
    with pytest.raises(UncertainExecution, match="binding mismatch"):
        _classify(work_dir, tx, bindings)


def test_wrong_phase_binding_fails_closed(work_dir, tx, bindings):
    kw = _bindings(tx, bindings)
    kw["phase"] = "confirmation"
    ledger.record_prepared(work_dir=work_dir, attempt=1, pid=1234, **kw)
    with pytest.raises(UncertainExecution, match="binding mismatch"):
        _classify(work_dir, tx, bindings)


def test_wrong_schema_fails_closed(work_dir, tx, bindings):
    kw = _bindings(tx, bindings)
    rec = ledger.record_prepared(work_dir=work_dir, attempt=1, pid=1234,
                                 **kw)
    rec["schema"] = "airlock.rsi-006-q5.something-else.v9"
    p = (work_dir / "artifacts" / "execution_ledger"
         / f"{OBS}.prepared.json")
    p.write_text(json.dumps(rec))
    with pytest.raises(UncertainExecution, match="wrong schema"):
        _classify(work_dir, tx, bindings)


def test_committed_skips_regardless_of_ledger(work_dir, tx, bindings):
    tx.commit_observation(mutant_id=OBS, phase=PHASE,
                          canonical=b'{"done": true}',
                          launch={"schema": "test"})
    status, digest = _classify(work_dir, tx, bindings)
    assert status == "committed"
    assert digest == tx.observations[OBS]


def test_unsafe_observation_id_rejected(work_dir, tx, bindings):
    with pytest.raises(ValueError, match="unsafe observation id"):
        _classify(work_dir, tx, bindings, obs="../evil")


def test_record_started_validates_child(work_dir, tx, bindings):
    kw = _bindings(tx, bindings)
    with pytest.raises(ValueError, match="child_pid"):
        ledger.record_started(work_dir=work_dir, attempt=1, child_pid=0,
                              exec_nonce="x", **kw)
    with pytest.raises(ValueError, match="exec_nonce"):
        ledger.record_started(work_dir=work_dir, attempt=1,
                              child_pid=999, exec_nonce="", **kw)
    with pytest.raises(ValueError, match="attempt"):
        ledger.record_prepared(work_dir=work_dir, attempt=0, pid=1,
                               **kw)


def test_records_are_bound_and_atomic(work_dir, tx, bindings):
    kw = _bindings(tx, bindings)
    prepared = ledger.record_prepared(work_dir=work_dir, attempt=3,
                                     pid=4242, **kw)
    assert prepared["schema"] == ledger.PREPARED_SCHEMA
    assert prepared["attempt"] == 3
    assert prepared["txid"] == tx.txid
    started = ledger.record_started(
        work_dir=work_dir, attempt=3, child_pid=7777,
        exec_nonce="nonce-xyz", **kw)
    assert started["schema"] == ledger.STARTED_SCHEMA
    assert started["child_pid"] == 7777
    assert started["exec_nonce"] == "nonce-xyz"
    failed = ledger.record_spawn_failed(
        work_dir=work_dir, attempt=3, error="OSError: nope", **kw)
    assert failed["schema"] == ledger.SPAWN_FAILED_SCHEMA
    assert failed["attempt"] == 3
    # No torn temp files may survive an atomic write.
    leftovers = list((work_dir / "artifacts" / "execution_ledger")
                     .glob(".prepared.json.tmp-*"))
    assert leftovers == []
