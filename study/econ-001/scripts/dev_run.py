"""Development run: baseline worker over DEV tasks only (paid, <=$5).

Purpose: difficulty validation (solvable yet discriminating?), extraction
reliability, tokenizer drift, pipeline behavior under a real model.
Never touches the eval pool. Findings may change the GENERATOR; the eval
corpus is (re)generated from the final generator and never executed here.
"""
import json
import os
import sys

sys.path.insert(0, "src")
from econ import attempt as attempt_mod
from econ import corpus, ledger as ledger_mod
from econ import orchestrate, prompts, worker

STUDY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_NAME = sys.argv[1] if len(sys.argv) > 1 else "dev-001"
RUN_DIR = os.path.join(STUDY_DIR, "runs", RUN_NAME)
os.makedirs(RUN_DIR, exist_ok=True)

pools = corpus.load_corpus(os.path.join(STUDY_DIR, "corpus", "corpus.json"))
dev = pools["dev"]

lg = ledger_mod.Ledger(5.00, os.path.join(RUN_DIR, "ledger.jsonl"))
provider = worker.RealProvider()
envelopes = orchestrate.load_envelopes(os.path.join(STUDY_DIR, "CONFIG.json"))

results = []
drift_samples = []
for i, t in enumerate(dev):
    a = attempt_mod.attempt(
        t, prompts.BASE_METHOD, ledger=lg, provider=provider,
        envelopes=envelopes, invocation_id=f"dev_baseline_{i:02d}")
    a.pop("code", None)
    results.append(a)
    if a.get("provider_input_tokens"):
        drift_samples.append(abs(a["local_input_tokens"] - a["provider_input_tokens"])
                             / a["provider_input_tokens"])
    print(f"[{i+1}/{len(dev)}] {t.task_id} verdict={a['verdict']} "
          f"reason={a.get('reason')} status={a['status']} "
          f"actual=${(a.get('actual_usd') or 0):.4f}", flush=True)
    if a["status"] == "overrun_abort":
        print("OVERRUN ABORT -- stopping dev run")
        break

by_family = {}
for t, a in zip(dev, results):
    by_family.setdefault(t.family, []).append(a["verdict"])

summary = {
    "n": len(results),
    "pass_rate": sum(a["verdict"] for a in results) / max(len(results), 1),
    "by_family": {f: sum(v) / len(v) for f, v in by_family.items()},
    "extraction_failures": sum(1 for a in results if a.get("reason") == "extraction_failed"),
    "unresolved": sum(1 for a in results if a["status"] == "unresolved"),
    "refused": sum(1 for a in results if a["status"] == "refused_precontact"),
    "mean_tokenizer_drift": sum(drift_samples) / max(len(drift_samples), 1),
    "ledger": lg.summary(),
}
with open(os.path.join(RUN_DIR, "attempts.json"), "w") as f:
    json.dump(results, f, indent=1)
with open(os.path.join(RUN_DIR, "summary.json"), "w") as f:
    json.dump(summary, f, indent=1, sort_keys=True)
print(json.dumps(summary, indent=1, sort_keys=True))
