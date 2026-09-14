from __future__ import annotations
import importlib.util, json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
RUNNER = HERE / "run_ril_anomaly_002.py"

def load_runner():
    spec = importlib.util.spec_from_file_location("ril_anomaly_002_runner", RUNNER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def test_self_check_passes():
    mod = load_runner()
    out = mod.self_check()
    assert out["self_check"] == "PASS"
    assert out["promote_advances_head"] is True
    assert out["weak_anomaly_response_rejected"] is True
    assert out["same_weak_response_valid_as_ordinary_search"] is True

def test_frozen_hashes_match_files():
    mod = load_runner()
    prereg = json.loads((HERE / "RIL_ANOMALY_002_PREREGISTRATION.json").read_text())
    root = HERE.parents[1]
    for rel, expected in prereg["frozen_files"].items():
        assert mod.sha256_file(root / rel) == expected

def test_ratchet_fail_closed():
    mod = load_runner()
    base={"protocol_valid":True,"confirmed_improvement":True,"regression_detected":False}
    assert mod.promotion_decision(base)=="PROMOTE"
    assert mod.promotion_decision({**base,"confirmed_improvement":False})=="REJECT"
    assert mod.promotion_decision({**base,"regression_detected":True})=="REJECT"
    assert mod.promotion_decision({**base,"protocol_valid":False})=="QUARANTINE"

def test_matched_design_frozen():
    p=json.loads((HERE/"RIL_ANOMALY_002_PREREGISTRATION.json").read_text())
    assert p["rounds_per_arm"]==4
    assert p["pass_threshold"]["condition"]=="anomaly_interview promotions - ordinary_search promotions >= 2"
    assert p["researcher"]["one_fresh_temporary_chat_per_arm"] is True
    assert p["researcher"]["same_chat_retained_within_arm_for_four_rounds"] is True
    assert p["lineage"]["failed_match"]["single_arm_promotions_are_not_inherited"] is True
