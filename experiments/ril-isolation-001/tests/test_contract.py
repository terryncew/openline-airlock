import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "protected" / "isolation_core.py"
spec = importlib.util.spec_from_file_location("isolation_core", CORE_PATH)
core = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = core
spec.loader.exec_module(core)


def good_record():
    return core.TrialRecord(
        own_recall_a=True,
        own_recall_b=True,
        blind_after_a="UNKNOWN",
        blind_after_b="UNKNOWN",
        canary_a="RILISO-1-A-" + "a" * 48,
        canary_b="RILISO-1-B-" + "b" * 48,
        temp_marker_all_chats=True,
        recent_absent_a=True,
        recent_absent_b=True,
        activity_absent_a=True,
        activity_absent_b=True,
        operator_payload_clean=True,
    )


def test_clean_trial_passes():
    assert good_record().verdict() == "PASS_TRIAL"


def test_cross_chat_canary_fails():
    r = good_record()
    bad = core.TrialRecord(**{**r.__dict__, "blind_after_a": r.canary_a})
    assert bad.verdict() == "FAIL_CROSS_CHAT_SEMANTIC_LEAK"


def test_recents_or_activity_visibility_fails():
    r = good_record()
    assert core.TrialRecord(**{**r.__dict__, "recent_absent_a": False}).verdict() == "FAIL_TEMP_CHAT_VISIBLE_IN_RECENTS"
    assert core.TrialRecord(**{**r.__dict__, "activity_absent_b": False}).verdict() == "FAIL_TEMP_CHAT_VISIBLE_IN_ACTIVITY"


def test_prereg_is_consumer_ui_no_api_key():
    p = json.loads((ROOT / "RIL_ISOLATION_001_PREREGISTRATION.json").read_text())
    assert p["substrate"]["api_key_required"] is False
    assert p["substrate"]["mode"] == "Temporary Chat"
    assert p["trial_count"] == 4
