from __future__ import annotations

import argparse
import json
from pathlib import Path
from protected.isolation_core import (
    TrialRecord, aggregate_verdict, blind_prompt, exposure_prompt, make_canary, positive_prompt
)

HERE = Path(__file__).resolve().parent
PREREG = HERE / "RIL_ISOLATION_001_PREREGISTRATION.json"


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cmd_self_check(_: argparse.Namespace) -> int:
    p = json.loads(PREREG.read_text())
    assert p["experiment"] == "RIL-ISOLATION-001"
    assert p["trial_count"] == 4
    assert p["substrate"]["mode"] == "Temporary Chat"
    assert p["substrate"]["api_key_required"] is False
    assert p["documented_boundary"]["provider_internal_retention_up_to_hours"] == 72
    print("PASS self-check")
    return 0


def cmd_prepare(args: argparse.Namespace) -> int:
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    trials = []
    for i in range(1, 5):
        a, b = make_canary(i, "A"), make_canary(i, "B")
        trial = {
            "trial": i,
            "canary_a": a,
            "canary_b": b,
            "exposure_a_prompt": exposure_prompt(a),
            "positive_control_prompt": positive_prompt(),
            "blind_probe_prompt": blind_prompt(),
            "exposure_b_prompt": exposure_prompt(b),
        }
        trials.append(trial)
        write_json(out / f"trial-{i:02d}.json", trial)
    operator = {
        "experiment": "RIL-ISOLATION-001",
        "model": "3.8 Flash",
        "mode": "Temporary Chat",
        "instructions": [
            "Use only the generated trial file for the current trial.",
            "Every exposure and blind probe starts in a brand-new Temporary Chat.",
            "Verify the Temporary Chat indicator and 3.8 Flash before sending each prompt.",
            "Never paste a prior chat, canary, or response into a blind probe.",
            "After closing each exposure chat, verify it is absent from Recent chats and Gemini Apps Activity.",
            "Record exact model outputs and booleans in trial-NN-record.json using the template."
        ],
        "record_template": {
            "trial": 1,
            "own_recall_a": False,
            "own_recall_b": False,
            "blind_after_a": "UNKNOWN",
            "blind_after_b": "UNKNOWN",
            "temp_marker_all_chats": False,
            "recent_absent_a": False,
            "recent_absent_b": False,
            "activity_absent_a": False,
            "activity_absent_b": False,
            "operator_payload_clean": False
        }
    }
    write_json(out / "OPERATOR_PROTOCOL.json", operator)
    write_json(out / "PREPARED.json", {"experiment": "RIL-ISOLATION-001", "trials": trials})
    print(out)
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    prepared = json.loads((Path(args.prepared) / "PREPARED.json").read_text())
    records = []
    details = []
    for trial in prepared["trials"]:
        i = trial["trial"]
        rec_path = Path(args.records) / f"trial-{i:02d}-record.json"
        rec = json.loads(rec_path.read_text())
        record = TrialRecord(
            own_recall_a=bool(rec["own_recall_a"]),
            own_recall_b=bool(rec["own_recall_b"]),
            blind_after_a=str(rec["blind_after_a"]),
            blind_after_b=str(rec["blind_after_b"]),
            canary_a=trial["canary_a"],
            canary_b=trial["canary_b"],
            temp_marker_all_chats=bool(rec["temp_marker_all_chats"]),
            recent_absent_a=bool(rec["recent_absent_a"]),
            recent_absent_b=bool(rec["recent_absent_b"]),
            activity_absent_a=bool(rec["activity_absent_a"]),
            activity_absent_b=bool(rec["activity_absent_b"]),
            operator_payload_clean=bool(rec["operator_payload_clean"]),
        )
        records.append(record)
        details.append({"trial": i, "verdict": record.verdict()})
    result = {
        "experiment": "RIL-ISOLATION-001",
        "verdict": aggregate_verdict(records),
        "trials": details,
        "claim_boundary": "observable Gemini Temporary Chat inheritance boundary only; provider-internal deletion not claimed"
    }
    write_json(Path(args.output), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("self-check"); s.set_defaults(func=cmd_self_check)
    p = sub.add_parser("prepare"); p.add_argument("--output", required=True); p.set_defaults(func=cmd_prepare)
    q = sub.add_parser("score"); q.add_argument("--prepared", required=True); q.add_argument("--records", required=True); q.add_argument("--output", required=True); q.set_defaults(func=cmd_score)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
