"""RPI-001 frozen allocation + operating arm-order schedule.

Reads study/rpi-001/corpus/corpus.json (100 tasks rpi-eva-0000..0099).
Writes TASK_ALLOCATION.json and SCHEDULE.json.

Allocation (frozen, no task reuse across phases):
  phase1 round1: discovery 0000-0002, promotion 0003-0014
  phase1 round2: discovery 0015-0017, promotion 0018-0029
  phase2 round1: discovery 0030-0032, promotion 0033-0044
  operating:     0045-0080 (36 tasks, one attempt per arm)
  spares:        0081-0099 (19, unused)

Operating schedule: for each operating task, a seeded Fisher-Yates
permutation of ["A","B","C"] (rng = random.Random(f"rpi-schedule:{task_id}")).
SHA-256 of the canonical JSON is frozen in SCHEDULE.json and re-verified
by the runner before any scientific contact.
"""
import json, os, random, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)

with open(os.path.join(STUDY, "corpus", "corpus.json")) as f:
    corpus = json.load(f)["eval"]
ids = [t["task_id"] for t in corpus]
assert ids == [f"rpi-eva-{i:04d}" for i in range(100)], "corpus ID order changed"

alloc = {
    "rule": "fixed before contact; no task reuse across phases; no reuse across rounds",
    "phase1": {
        "rounds": 2,
        "round1": {"discovery": ids[0:3], "promotion": ids[3:15]},
        "round2": {"discovery": ids[15:18], "promotion": ids[18:30]},
    },
    "phase2": {
        "rounds": 1,
        "round1": {"discovery": ids[30:33], "promotion": ids[33:45]},
    },
    "operating": ids[45:81],
    "spares": ids[81:100],
}
assert len(alloc["operating"]) == 36
with open(os.path.join(STUDY, "TASK_ALLOCATION.json"), "w") as f:
    json.dump(alloc, f, indent=1, sort_keys=True)

sched = {}
for tid in alloc["operating"]:
    rng = random.Random(f"rpi-schedule:{tid}")
    order = ["A", "B", "C"]
    rng.shuffle(order)
    sched[tid] = order
sched_json = json.dumps(sched, indent=1, sort_keys=True)
sched_hash = hashlib.sha256(sched_json.encode()).hexdigest()
with open(os.path.join(STUDY, "SCHEDULE.json"), "w") as f:
    f.write(json.dumps({"schedule_sha256": sched_hash,
                        "schedule": sched}, indent=1, sort_keys=True))

print("allocation: phase1 r1/r2, phase2 r1, operating 36, spares 19")
print("schedule_sha256:", sched_hash)
