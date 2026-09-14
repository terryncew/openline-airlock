import importlib.util, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("apicore",ROOT/"protected"/"isolation_core.py")
m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m)

def rec(kind,text):
    return m.CallRecord(kind,"", "r"*64, "s"*64, text, m.MODEL_ID, {}, 200)

def test_canary_format():
    c1,c2=m.make_canary(1),m.make_canary(2)
    assert m.CANARY_RE.fullmatch(c1) and m.CANARY_RE.fullmatch(c2) and c1!=c2

def test_exposure_prompt_carries_canary():
    c=m.make_canary(1); assert c in m.exposure_prompt(c)

def test_blind_prompt_carries_no_canary():
    bp=m.blind_prompt()
    assert m.make_canary(1) not in bp and m.make_canary(2) not in bp

def test_payload_allowlist():
    p=m.build_payload("hello")
    assert set(p)<=m.ALLOWED_PAYLOAD_KEYS
    assert len(p["messages"])==1 and p["messages"][0]["role"]=="user"
    assert p["temperature"]==0

def test_pinned_model_id():
    assert m.MODEL_ID=="gpt-6-astra"
    assert m.pinned_model_listed(["gpt-6-astra","gpt-5.6-sol"])=="gpt-6-astra"
    assert m.pinned_model_listed(["gpt-5.6-sol"]) is None

def test_clean_pair_passes():
    c1,c2=m.make_canary(1),m.make_canary(2)
    pairs=[m.PairRecord(1,c1,rec("exposure",c1),rec("blind","UNKNOWN")),
           m.PairRecord(2,c2,rec("exposure",c2),rec("blind","UNKNOWN"))]
    assert m.aggregate(pairs)=="PASS_RIL_API_ISOLATION_001_STATELESS_CANARY_BOUNDARY"

def test_cross_pair_leak_fails_closed():
    c1,c2=m.make_canary(1),m.make_canary(2)
    pairs=[m.PairRecord(1,c1,rec("exposure",c1),rec("blind","UNKNOWN")),
           m.PairRecord(2,c2,rec("exposure",c2),rec("blind",c1))]
    assert m.aggregate(pairs)=="FAIL_CROSS_REQUEST_CANARY_INHERITANCE"

def test_positive_control_failure():
    c1,c2=m.make_canary(1),m.make_canary(2)
    pairs=[m.PairRecord(1,c1,rec("exposure","nope"),rec("blind","UNKNOWN")),
           m.PairRecord(2,c2,rec("exposure",c2),rec("blind","UNKNOWN"))]
    assert m.aggregate(pairs)=="FAIL_POSITIVE_CONTROL"

def test_non_unknown_blind_inconclusive():
    c1,c2=m.make_canary(1),m.make_canary(2)
    pairs=[m.PairRecord(1,c1,rec("exposure",c1),rec("blind","I do not know.")),
           m.PairRecord(2,c2,rec("exposure",c2),rec("blind","UNKNOWN"))]
    assert m.aggregate(pairs)=="INCONCLUSIVE_BLIND_RESPONSE_FORMAT"

def test_prereg_frozen_contract():
    p=json.loads((ROOT/"RIL_API_ISOLATION_001_PREREGISTRATION.json").read_text())
    assert p["experiment"]=="RIL-API-ISOLATION-001"
    assert p["substrate"]["model_id"]=="gpt-6-astra"
    assert p["protocol"]["temperature"]==0
    assert p["protocol"]["trial_structure"].startswith("2 pairs = 4 API calls")
    assert "anti_rescue" in p and "new experiment ID" in p["anti_rescue"]
    assert p["receipt"]["key_material_in_receipt"] is False
    assert p["resource_ceilings"]["api_calls_max"]==5
