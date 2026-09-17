"""Generate and freeze the PAYBACK-001 corpus, allocation, and arm-order schedules.

Offline: no provider contact. Run once; outputs are frozen artifacts.

  corpus.json        465 tasks, byte-disjoint from prior ECON instances
  ALLOCATION.json    discovery[0:3] / promotion[3:15] / operating pool[15:465]
  OPERATING_ORDER.json  frozen permutation of the 450 operating tasks
  ARM_ORDER.json     frozen per-pair arm order (CT or TC), 225/225 balanced

Declared seeds:
  PB1_CORPUS_SEED   = 20260921  (task generation; derived gen<k> streams)
  PB1_ORDER_SEED    = 20260924  (operating permutation)
  PB1_ARM_SEED      = 20260916  (arm-order schedule)
  PB1_PROMO_SEED    = 20260925  (promotion arm order, 12 pairs)

Apparatus limit (frozen finding): the preserved ECON generator's reachable
task space is ~815 distinct tasks; 482 are disjoint from all prior ECON
scientific instances. 715 fresh tasks do not exist, so H=450 (465 tasks)
is the largest clean horizon. Over-generate with derived seeds, keep the
first 465 draws whose content hash is new (declared procedure, frozen here).
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import sys

sys.path.insert(0, "/home/hatch/workspace/openline-airlock/study/econ-001/src")
from econ import corpus  # noqa: E402

STUDY_DIR = "/home/hatch/workspace/openline-airlock/study/payback-001"
CORPUS_DIR = os.path.join(STUDY_DIR, "corpus")

PB1_CORPUS_SEED = 20260921
PB1_ORDER_SEED = 20260924
PB1_ARM_SEED = 20260916
PB1_PROMO_SEED = 20260925

N_DISCOVERY, N_PROMOTION, N_OPERATING = 3, 12, 450
N_TOTAL = N_DISCOVERY + N_PROMOTION + N_OPERATING  # 465
PRIOR = [
    "/home/hatch/workspace/openline-airlock/study/econ-001/corpus/corpus.json",
    "/home/hatch/workspace/openline-airlock/study/econ-001/corpus/corpus_r2.json",
    "/home/hatch/workspace/openline-airlock/study/econ-001/corpus/corpus_r3.json",
    "/home/hatch/workspace/openline-airlock/study/econ-002/corpus/corpus.json",
]


def content_hash(t: dict) -> str:
    canon = json.dumps({k: t[k] for k in ("statement", "target_code", "hidden_tests")},
                       sort_keys=True)
    return hashlib.sha256(canon.encode()).hexdigest()


def sha_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def main() -> None:
    os.makedirs(CORPUS_DIR, exist_ok=True)

    # Disjointness against all prior ECON scientific instances.
    # The generator's task space is small enough that raw draws collide;
    # deterministically over-generate with derived seeds and keep the first
    # 715 draws whose content hash is new (declared procedure, frozen here).
    prior_hashes = set()
    for p in PRIOR:
        d = json.load(open(p))
        for pool in ("eval", "calib", "dev"):
            for t in d.get(pool, []):
                prior_hashes.add(content_hash(t))
    tasks, seen = [], set()
    k = 0
    while len(tasks) < N_TOTAL:
        batch = corpus.build_corpus(f"{PB1_CORPUS_SEED}:gen{k}", 0, 2000, 0)["eval"]
        for t in batch:
            d = t.to_dict()
            h = content_hash(d)
            if h in prior_hashes or h in seen:
                continue
            seen.add(h)
            d["task_id"] = f"pb1-{d['family'][:4]}-{len(tasks):04d}"
            tasks.append(d)
            if len(tasks) == N_TOTAL:
                break
        k += 1
        assert k < 50, "generator space exhausted"
    assert len({content_hash(t) for t in tasks}) == N_TOTAL

    corpus_path = os.path.join(CORPUS_DIR, "corpus.json")
    with open(corpus_path, "w") as f:
        json.dump({"meta": {"study": "PAYBACK-001", "seeds": [PB1_CORPUS_SEED],
                            "n_tasks": N_TOTAL,
                            "rule": "content-disjoint from all prior ECON scientific instances",
                            "apparatus_limit": "generator space ~815 distinct; 482 new available"},
                   "tasks": tasks}, f, indent=1, sort_keys=True)
    corpus_sha = sha_file(corpus_path)

    allocation = {"discovery": list(range(0, 3)),
                  "promotion": list(range(3, 15)),
                  "operating_pool": list(range(15, N_TOTAL))}
    alloc_path = os.path.join(CORPUS_DIR, "ALLOCATION.json")
    json.dump(allocation, open(alloc_path, "w"), indent=1, sort_keys=True)

    rng = random.Random(PB1_ORDER_SEED)
    operating_order = list(range(N_OPERATING))
    rng.shuffle(operating_order)  # positions in operating_pool
    order_path = os.path.join(CORPUS_DIR, "OPERATING_ORDER.json")
    json.dump({"seed": PB1_ORDER_SEED, "order": operating_order},
              open(order_path, "w"), indent=1)

    rng = random.Random(PB1_ARM_SEED)
    arm_order = ["CT"] * 225 + ["TC"] * 225
    rng.shuffle(arm_order)
    assert arm_order.count("CT") == 225 and arm_order.count("TC") == 225
    arm_path = os.path.join(CORPUS_DIR, "ARM_ORDER.json")
    json.dump({"seed": PB1_ARM_SEED, "order": arm_order,
               "balance": {"CT": 225, "TC": 225}}, open(arm_path, "w"), indent=1)
    arm_sha = sha_file(arm_path)

    rng = random.Random(PB1_PROMO_SEED)
    promo_order = (["PC"] * 6 + ["CP"] * 6)
    rng.shuffle(promo_order)
    promo_path = os.path.join(CORPUS_DIR, "PROMOTION_ORDER.json")
    json.dump({"seed": PB1_PROMO_SEED, "order": promo_order}, open(promo_path, "w"), indent=1)

    manifest = {
        "seeds": {"corpus": PB1_CORPUS_SEED, "operating_order": PB1_ORDER_SEED,
                  "arm_order": PB1_ARM_SEED, "promotion_order": PB1_PROMO_SEED},
        "counts": {"discovery": N_DISCOVERY, "promotion": N_PROMOTION,
                   "operating": N_OPERATING},
        "corpus_sha256": corpus_sha,
        "arm_order_sha256": arm_sha,
        "prior_overlap": 0,
    }
    json.dump(manifest, open(os.path.join(CORPUS_DIR, "MANIFEST.json"), "w"), indent=1)
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
