"""Offline tests for ECON-002 (zero provider contact; free to run)."""
import sys, os, hashlib, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import succ_run as S
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                "econ-001", "src"))
from econ import prompts, tokens


def _att(verdict, usd):
    return {"verdict": verdict, "actual_usd": usd, "status": "ok"}


def test_gate_accepts_clear_winner():
    p = [_att(1, 0.030) for _ in range(12)]
    c = [_att(1, 0.020) for _ in range(12)]  # 33% cheaper
    ok, rec = S.gate(p, c)
    assert ok and rec["vp"] == 12 and rec["vc"] == 12
    assert rec["regressions"] == 0 and rec["ratio"] < 0.8


def test_gate_boundary_around_20_percent():
    p = [_att(1, 0.030) for _ in range(12)]
    c = [_att(1, 0.0239) for _ in range(12)]  # just under 80%
    ok, _ = S.gate(p, c)
    assert ok
    c2 = [_att(1, 0.0241) for _ in range(12)]  # just over 80%
    ok2, _ = S.gate(p, c2)
    assert not ok2


def test_gate_rejects_success_shortfall_and_regression():
    p = [_att(1, 0.030) for _ in range(12)]
    c = [_att(1, 0.020) for _ in range(11)] + [_att(0, 0.020)]
    ok, rec = S.gate(p, c)
    assert not ok and rec["vc"] == 11 and rec["regressions"] == 1


def test_gate_rejects_when_parent_not_saturated():
    p = [_att(1, 0.030) for _ in range(11)] + [_att(0, 0.030)]
    c = [_att(1, 0.020) for _ in range(12)]
    ok, rec = S.gate(p, c)
    assert not ok and rec["vp"] == 11


def test_gate_uses_reservation_when_unsettled():
    p = [_att(1, 0.030) for _ in range(12)]
    c = [{"verdict": 1, "actual_usd": None, "reservation_usd": 0.11,
          "status": "unresolved"} for _ in range(12)]
    ok, rec = S.gate(p, c)
    assert not ok  # unresolved cost falls back to full reservation


def test_d1_removes_visible_check_step():
    r = prompts.apply_delta(prompts.BASE_METHOD, "REMOVE_STEP 6")
    assert "CHECK." not in r and "FIX." in r
    steps = [l for l in r.splitlines()
             if l.strip() and l.strip()[0].isdigit()]
    assert len(steps) == 6  # preamble + 5 remaining steps, renumbered 1..6


def test_numbering_quirk_verified_for_all_candidates():
    # apply_delta block 1 = preamble; visible step k = block k+1.
    r1 = prompts.apply_delta(prompts.BASE_METHOD, "REMOVE_STEP 6")
    assert "CHECK." not in r1 and "REPRODUCE." in r1  # D1 hit CHECK, not REPRO
    r2 = prompts.apply_delta(prompts.BASE_METHOD, "REMOVE_STEP 3")
    assert "REPRODUCE." not in r2 and "DIAGNOSE." in r2  # D2 hit REPRODUCE


def test_stage2_prompt_carries_verbatim_objective():
    assert S.OBJ in S.PROMPT
    assert "at most 80%" in S.CRIT or "80%" in S.CRIT
    assert "REMOVE_STEP 6" in S.NUM  # numbering worked example present


def test_offline_validation_makes_no_contact():
    S.offline()  # raises on any frozen-artifact mismatch
    rundir = os.path.join(S.STUDY2, "runs", S.SID)
    assert not os.path.exists(rundir), "offline mode must not create a run"


def test_frozen_candidate_hashes_match_file():
    cands = json.load(open(os.path.join(S.STUDY2, "CANDIDATES.json")))
    for n in S.ORDER:
        r = cands["candidates"][n]["rendered_method"]
        assert hashlib.sha256(r.encode()).hexdigest() == \
            cands["candidates"][n]["rendered_sha256"]
        assert tokens.count(r) == cands["candidates"][n]["rendered_tokens"]
