from __future__ import annotations
import argparse, json
from pathlib import Path
from protected.isolation_core import TrialRecord, aggregate, blind_prompt, exposure_prompt, make_canary, positive_prompt

HERE = Path(__file__).resolve().parent
PREREG = HERE / "RIL_ISOLATION_002_PREREGISTRATION.json"

def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")

def cmd_self_check(_):
    p = json.loads(PREREG.read_text())
    assert p["experiment"] == "RIL-ISOLATION-002"
    assert p["trial_count"] == 2
    assert p["precontact_preflight"]["required"] is True
    assert p["substrate"]["mode"] == "Temporary Chat"
    print("PASS self-check")
    return 0

def cmd_prepare(args):
    pre = json.loads(Path(args.preflight).read_text())
    assert pre == {
        "experiment": "RIL-ISOLATION-002",
        "temporary_chat_indicator_visible": True,
        "model_display": "3.8 Flash",
        "canary_exposure_started": False,
    }, "preflight must be exact and must occur before canary exposure"
    out = Path(args.output)
    trials = []
    for i in (1, 2):
        c = make_canary(i)
        t = {
            "trial": i,
            "canary": c,
            "exposure_prompt": exposure_prompt(c),
            "positive_control_prompt": positive_prompt(),
            "blind_probe_prompt": blind_prompt(),
        }
        trials.append(t)
        write_json(out/f"trial-{i:02d}.json", t)
    write_json(out/"PREPARED.json", {"experiment":"RIL-ISOLATION-002","preflight":pre,"trials":trials})
    print(out)
    return 0

def cmd_score(args):
    prepared = json.loads((Path(args.prepared)/"PREPARED.json").read_text())
    canaries = [t["canary"] for t in prepared["trials"]]
    records, details = [], []
    for t in prepared["trials"]:
        i=t["trial"]
        rec=json.loads((Path(args.records)/f"trial-{i:02d}-record.json").read_text())
        r=TrialRecord(
            own_recall_exact=bool(rec["own_recall_exact"]),
            blind_response=str(rec["blind_response"]),
            temp_marker_exposure=bool(rec["temp_marker_exposure"]),
            temp_marker_probe=bool(rec["temp_marker_probe"]),
            operator_payload_clean=bool(rec["operator_payload_clean"]),
        )
        records.append(r); details.append({"trial":i,"verdict":r.verdict(canaries)})
    b=json.loads((Path(args.records)/"boundary-record.json").read_text())
    verdict=aggregate(records,canaries,bool(b["recent_absent_all"]),bool(b["activity_absent_all"]))
    result={"experiment":"RIL-ISOLATION-002","verdict":verdict,"trials":details,
            "recent_absent_all":bool(b["recent_absent_all"]),
            "activity_absent_all":bool(b["activity_absent_all"]),
            "claim_boundary":"two paired Gemini Temporary Chat trials; observable product-memory boundary only"}
    write_json(Path(args.output),result)
    print(json.dumps(result,indent=2,sort_keys=True))
    return 0

def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest="cmd",required=True)
    s=sub.add_parser("self-check"); s.set_defaults(func=cmd_self_check)
    p=sub.add_parser("prepare"); p.add_argument("--preflight",required=True); p.add_argument("--output",required=True); p.set_defaults(func=cmd_prepare)
    q=sub.add_parser("score"); q.add_argument("--prepared",required=True); q.add_argument("--records",required=True); q.add_argument("--output",required=True); q.set_defaults(func=cmd_score)
    a=ap.parse_args(); return a.func(a)
if __name__=="__main__": raise SystemExit(main())
