"""ECON-001 study run: calibration + 3 repetitions on the eval pool (paid, <=$50).

Frozen protocol (commit 51b4e0d). Corpus: eval pool (162 tasks, never
executed before this run), calib pool (3 tasks, one per family).
Ledger: runs/study-001/ledger.jsonl, $50 ceiling, fail closed on overrun.
Checkpointed per-rep (rep JSON written after each rep) against transport
flakiness. Run with: <venv>/python scripts/study_run.py
"""
import json
import os
import sys

sys.path.insert(0, "src")
from econ import corpus, ledger as ledger_mod
from econ import orchestrate, report, worker

STUDY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_DIR = os.path.join(STUDY_DIR, "runs", "study-001")
os.makedirs(RUN_DIR, exist_ok=True)

pools = corpus.load_corpus(os.path.join(STUDY_DIR, "corpus", "corpus.json"))
eval_tasks = pools["eval"]
calib_tasks = pools["calib"]
assert len(eval_tasks) == 162, f"eval pool: {len(eval_tasks)}"
assert len(calib_tasks) == 3, f"calib pool: {len(calib_tasks)}"
fams = sorted(t.family for t in calib_tasks)
assert fams == ["config", "interface", "logic"], f"calib families: {fams}"

lg = ledger_mod.Ledger(50.00, os.path.join(RUN_DIR, "ledger.jsonl"))
provider = worker.RealProvider()

# Stop-before-next-call control: creating RUN_DIR/STOP halts the study
# before the next paid invocation is issued (no new reservation, no new
# provider contact). The in-flight call, if any, settles normally first.
STOP_FILE = os.path.join(RUN_DIR, "STOP")
RAW_DIR = os.path.join(RUN_DIR, "raw")

print(f"starting study: 162 eval + 3 calib tasks, $50 ledger", flush=True)
print(f"stop control: touch {STOP_FILE} to halt before the next paid call",
      flush=True)
study = orchestrate.run_study(
    eval_tasks=eval_tasks, calib_tasks=calib_tasks,
    config_path=os.path.join(STUDY_DIR, "CONFIG.json"),
    ledger=lg, provider=provider, outdir=RUN_DIR, timeout_s=300.0,
    stop_file=STOP_FILE, raw_dir=RAW_DIR)

rep = report.build_report(study)
with open(os.path.join(RUN_DIR, "report.json"), "w") as f:
    json.dump(rep, f, indent=1, sort_keys=True)

print("=== calibration ===")
print(json.dumps(study["calibration"], indent=1, sort_keys=True))
print("=== report ===")
print(json.dumps(rep, indent=1, sort_keys=True))
