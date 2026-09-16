"""Q6 recorder units: canonical env bytes + frozen collision case."""

import hashlib

import q6_testkit as kit  # noqa: F401
import q6_recorder as qr


def _old_rejected_encoding(env):
    # The encoding the prereg rejects as non-injective: newline-joined
    # key=value. Both collision mappings below encode identically here.
    return "\n".join(f"{k}={v}" for k, v in sorted(env.items()))


def test_env_collision_canonical_json_distinguishes():
    # Frozen prereg example: {"A": "x\nB=y"} vs {"A": "x", "B": "y"}
    # both encode to "A=x\nB=y" under the rejected serializer.
    a = {"A": "x\nB=y"}
    b = {"A": "x", "B": "y"}
    assert _old_rejected_encoding(a) == _old_rejected_encoding(b)
    ba, bb = qr.canonical_env_bytes(a), qr.canonical_env_bytes(b)
    assert ba != bb
    assert hashlib.sha256(ba).hexdigest() != \
        hashlib.sha256(bb).hexdigest()


def test_canonical_env_bytes_is_deterministic():
    env = {"Z": "1", "A": "x\ny", "M": "ü"}
    assert qr.canonical_env_bytes(env) == qr.canonical_env_bytes(
        dict(reversed(list(env.items()))))
    # Exact JSON shape: sorted keys, compact separators, unicode kept.
    assert qr.canonical_env_bytes({"b": "2", "a": "1"}) == b'{"a":"1","b":"2"}'


def test_coordinator_and_recorder_share_canonicalization(work_dir):
    # build_recorder_config and the recorder must hash identically.
    import os as _os
    from pathlib import Path
    work = Path(work_dir)
    tx = kit.make_tx(work)
    _env = dict(_os.environ)
    _env.update({"Q6_UNIT": "1"})
    prep = {
        "classification": "scientific",
        "argv": ["true"],
        "run_dir": work,
        "env": _env,
        "repo_name": "fixture-repo",
        "mutant": {"mutant_id": "m"},
        "baseline": {},
        "python": "python3",
        "junit_path": str(work / "junit.xml"),
        "builder_context": {},
        "env_overrides": {"Q6_UNIT": "1"},
        "timeout_s": 5,
        "builder": "fixture_builders.fixture_completion",
        "spawn_failure_builder":
            "fixture_builders.fixture_spawn_failure",
    }
    cfg_bytes, cfg_sha = kit.q6_adapter.build_recorder_config(
        work_dir=work, tx=tx, receipt_sha256=kit.RECEIPT_SHA,
        code_hashes=kit.CODE_HASHES, observation_id="obs-unit-1",
        phase="discovery", attempt=1, prep=prep,
        marker_path=work / "m.json")
    import json
    cfg = json.loads(cfg_bytes)
    # The digest is over the exact prep["env"] mapping.
    assert hashlib.sha256(
        qr.canonical_env_bytes(_env)).hexdigest() == \
        cfg["prepared_env_sha256"]
    assert cfg_sha == hashlib.sha256(cfg_bytes).hexdigest()
    # The recorder's reconstruction rule agrees.
    rec_env = dict(_os.environ)
    rec_env.update(cfg["env_overrides"])
    assert hashlib.sha256(
        qr.canonical_env_bytes(rec_env)).hexdigest() == \
        cfg["prepared_env_sha256"]


def _minimal_prep(work):
    import os as _os
    _env = dict(_os.environ)
    return {
        "classification": "scientific",
        "argv": ["true"],
        "run_dir": work,
        "env": _env,
        "repo_name": "fixture-repo",
        "mutant": {"mutant_id": "m"},
        "baseline": {},
        "python": "python3",
        "junit_path": str(work / "junit.xml"),
        "builder_context": {},
        "env_overrides": {},
        "timeout_s": 5,
        "builder": "fixture_builders.fixture_completion",
        "spawn_failure_builder": "fixture_builders.fixture_spawn_failure",
    }


def test_recorder_config_exact_frozen_bytes(work_dir):
    """Frozen §7: config bytes are exactly
    json.dumps(config, sort_keys=True).encode("utf-8") -- not compact."""
    import json as _json
    from pathlib import Path
    work = Path(work_dir)
    tx = kit.make_tx(work)
    cfg_bytes, cfg_sha = kit.q6_adapter.build_recorder_config(
        work_dir=work, tx=tx, receipt_sha256=kit.RECEIPT_SHA,
        code_hashes=kit.CODE_HASHES, observation_id="obs-unit-bytes",
        phase="discovery", attempt=1, prep=_minimal_prep(work),
        marker_path=work / "m.json")
    cfg = _json.loads(cfg_bytes)
    frozen = _json.dumps(cfg, sort_keys=True).encode("utf-8")
    assert cfg_bytes == frozen
    compact = _json.dumps(cfg, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False).encode("utf-8")
    assert cfg_bytes != compact  # the frozen form is not the compact form
    import hashlib as _hl
    assert cfg_sha == _hl.sha256(frozen).hexdigest()


def test_config_create_once_race(work_dir):
    """Two concurrent writers: exactly one wins, loser fails closed,
    final bytes are exactly the winner's bytes, no overwrite."""
    import threading
    from pathlib import Path
    import execution_ledger as ledger
    from execution_ledger import UncertainExecution
    work = Path(work_dir)
    ledger.ledger_dir(str(work)).mkdir(parents=True, exist_ok=True)
    obs_id = "obs-race-1"
    bytes_a = b'{"winner": "a", "pad": "xxxxxxxxxxxxxxxx"}'
    bytes_b = b'{"winner": "b", "pad": "yyyyyyyyyyyyyyyy"}'
    barrier = threading.Barrier(2)
    results = {}

    def writer(name, payload):
        barrier.wait(timeout=30)
        try:
            kit.q6_adapter.write_recorder_config(
                str(work), obs_id, payload)
            results[name] = "won"
        except UncertainExecution:
            results[name] = "refused"

    ta = threading.Thread(target=writer, args=("a", bytes_a))
    tb = threading.Thread(target=writer, args=("b", bytes_b))
    ta.start()
    tb.start()
    ta.join(timeout=30)
    tb.join(timeout=30)
    assert sorted(results.values()) == ["refused", "won"]
    final = (ledger.ledger_dir(str(work)) /
             f"{obs_id}.q6_config.json").read_bytes()
    winner = "a" if results["a"] == "won" else "b"
    assert final == (bytes_a if winner == "a" else bytes_b)
