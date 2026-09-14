import importlib.util, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("iso2",ROOT/"protected"/"isolation_core.py")
m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m)

def good():
    return m.TrialRecord(True,"UNKNOWN",True,True,True)

def test_clean_pair_passes():
    cs=["RILISO2-1-"+"a"*48,"RILISO2-2-"+"b"*48]
    assert m.aggregate([good(),good()],cs,True,True)=="PASS_RIL_ISOLATION_002_GEMINI_TEMPORARY_CHAT_BOUNDARY"

def test_leak_fails():
    cs=["RILISO2-1-"+"a"*48,"RILISO2-2-"+"b"*48]
    bad=m.TrialRecord(True,cs[0],True,True,True)
    assert m.aggregate([bad,good()],cs,True,True)=="FAIL_CROSS_CHAT_SEMANTIC_LEAK"

def test_unverified_mode_fails():
    cs=["RILISO2-1-"+"a"*48,"RILISO2-2-"+"b"*48]
    bad=m.TrialRecord(True,"UNKNOWN",False,True,True)
    assert m.aggregate([bad,good()],cs,True,True)=="PROTOCOL_FAILURE_TEMPORARY_MODE_UNVERIFIED"

def test_prereg_fast_and_preflighted():
    p=json.loads((ROOT/"RIL_ISOLATION_002_PREREGISTRATION.json").read_text())
    assert p["trial_count"]==2
    assert p["precontact_preflight"]["must_occur_before_canary_generation"] is True
