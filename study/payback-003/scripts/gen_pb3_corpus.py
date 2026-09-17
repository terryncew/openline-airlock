"""Generate and freeze the PAYBACK-003 corpus, allocation, and arm-order schedules.

Offline: no provider contact. Run once; outputs are frozen artifacts.

  corpus.json        465 tasks, fresh draws (new declared seeds)
  ALLOCATION.json    discovery[0:3] / promotion[3:15] / operating pool[15:465]
  OPERATING_ORDER.json  frozen permutation of the 450 operating tasks
  ARM_ORDER.json     frozen per-pair arm order (CT or TC), 225/225 balanced

Declared seeds:
  PB3_CORPUS_SEED   = 20260926  (task generation; derived gen<k> streams)
  PB3_ORDER_SEED    = 20260927  (operating permutation)
  PB3_ARM_SEED      = 20260928  (arm-order schedule)
  PB3_PROMO_SEED    = 20260929  (promotion arm order, 12 pairs)

Apparatus limit (frozen finding, declared pre-contact): the preserved ECON
generator's reachable task space is 815 distinct tasks (verified by
saturation: 80,000 draws -> 815 unique). PAYBACK-002 consumed 465 of the 482
instances disjoint from prior ECON work, leaving 17. A fully
fresh-from-everything 465-task corpus is therefore an apparatus
impossibility, so the exclusion set is adapted as follows (declared here,
before any PAYBACK-003 contact):
  - discovery (3) + promotion (12): drawn disjoint from prior ECON
    scientific instances AND from PAYBACK-002's provider-contacted
    instances. The method is developed and promoted on fully clean tasks.
  - operating (450): drawn disjoint from PAYBACK-002's provider-contacted
    instances (186: 3 discovery + 12 promotion + 171 operating attempts).
    These tasks are unseen by the PAYBACK-003 successor; reuse of prior
    ECON instances is permitted here by the apparatus limit.
Disjointness is verified mechanically and recorded in MANIFEST.json.
Over-generate with derived seeds, keep the first 465 draws whose content
hash is new under the applicable exclusion set (declared procedure).
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import sys

sys.path.insert(0, "/home/hatch/workspace/openline-airlock/study/econ-001/src")
from econ import corpus  # noqa: E402

STUDY_DIR = "/home/hatch/workspace/openline-airlock/study/payback-003"
CORPUS_DIR = os.path.join(STUDY_DIR, "corpus")

PB3_CORPUS_SEED = 20260926
PB3_ORDER_SEED = 20260927
PB3_ARM_SEED = 20260928
PB3_PROMO_SEED = 20260929

N_DISCOVERY, N_PROMOTION, N_OPERATING = 3, 12, 450
N_TOTAL = N_DISCOVERY + N_PROMOTION + N_OPERATING  # 465
N_CLEAN = N_DISCOVERY + N_PROMOTION  # 15 fully-clean tasks
PRIOR = [
    "/home/hatch/workspace/openline-airlock/study/econ-001/corpus/corpus.json",
    "/home/hatch/workspace/openline-airlock/study/econ-001/corpus/corpus_r2.json",
    "/home/hatch/workspace/openline-airlock/study/econ-001/corpus/corpus_r3.json",
    "/home/hatch/workspace/openline-airlock/study/econ-002/corpus/corpus.json",
]
# PAYBACK-002 corpus (pre-regeneration copy on this branch) + schedules, to
# derive the provider-contacted exclusion set.
PB2_CORPUS = "/home/hatch/workspace/openline-airlock/study/payback-002/corpus/corpus.json"
PB2_ALLOC = "/home/hatch/workspace/openline-airlock/study/payback-002/corpus/ALLOCATION.json"
PB2_ORDER = "/home/hatch/workspace/openline-airlock/study/payback-002/corpus/OPERATING_ORDER.json"


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

    prior_hashes = set()
    for p in PRIOR:
        d = json.load(open(p))
        for pool in ("eval", "calib", "dev"):
            for t in d.get(pool, []):
                prior_hashes.add(content_hash(t))

    # PAYBACK-002 provider-contacted instances: discovery idx 0..2,
    # promotion idx 3..14, operating positions 0..170.
    pb2 = json.load(open(PB2_CORPUS))["tasks"]
    pb2_alloc = json.load(open(PB2_ALLOC))
    pb2_order = json.load(open(PB2_ORDER))["order"]
    pb2_hashes = [content_hash(t) for t in pb2]
    contacted_idx = set(pb2_alloc["discovery"]) | set(pb2_alloc["promotion"])
    pool = pb2_alloc["operating_pool"]
    for pos in range(171):
        contacted_idx.add(pool[pb2_order[pos]])
    contacted_hashes = {pb2_hashes[i] for i in contacted_idx}
    assert len(contacted_idx) == 186, len(contacted_idx)
    assert not (prior_hashes & contacted_hashes), "pb2 contacted overlapped prior ECON"

    clean_excl = prior_hashes | contacted_hashes   # discovery + promotion
    op_excl = set(contacted_hashes)                # operating

    tasks, seen = [], set()
    k = 0
    while len(tasks) < N_TOTAL:
        batch = corpus.build_corpus(f"{PB3_CORPUS_SEED}:gen{k}", 0, 2000, 0)["eval"]
        for t in batch:
            d = t.to_dict()
            h = content_hash(d)
            excl = clean_excl if len(tasks) < N_CLEAN else op_excl
            if h in excl or h in seen:
                continue
            seen.add(h)
            d["task_id"] = f"pb3-{d['family'][:4]}-{len(tasks):04d}"
            tasks.append(d)
            if len(tasks) == N_TOTAL:
                break
        k += 1
        assert k < 80, "generator space exhausted"
    assert len({content_hash(t) for t in tasks}) == N_TOTAL

    # Mechanical disjointness proof (before writing).
    hashes = [content_hash(t) for t in tasks]
    assert not (set(hashes[:N_CLEAN]) & clean_excl), "clean-set overlap"
    assert not (set(hashes[N_CLEAN:]) & contacted_hashes), "operating overlap with pb2-contacted"

    corpus_path = os.path.join(CORPUS_DIR, "corpus.json")
    with open(corpus_path, "w") as f:
        json.dump({"meta": {"study": "PAYBACK-003", "seeds": [PB3_CORPUS_SEED],
                            "n_tasks": N_TOTAL,
                            "rule": "discovery+promotion disjoint from prior ECON "
                                    "and pb2-contacted; operating disjoint from "
                                    "pb2-contacted (apparatus-limit adaptation, "
                                    "declared pre-contact)",
                            "apparatus_limit": "generator space 815 distinct; "
                                               "17 fully-fresh available"},
                   "tasks": tasks}, f, indent=1, sort_keys=True)
    corpus_sha = sha_file(corpus_path)

    allocation = {"discovery": list(range(0, 3)),
                  "promotion": list(range(3, 15)),
                  "operating_pool": list(range(15, N_TOTAL))}
    alloc_path = os.path.join(CORPUS_DIR, "ALLOCATION.json")
    json.dump(allocation, open(alloc_path, "w"), indent=1, sort_keys=True)

    rng = random.Random(PB3_ORDER_SEED)
    operating_order = list(range(N_OPERATING))
    rng.shuffle(operating_order)
    order_path = os.path.join(CORPUS_DIR, "OPERATING_ORDER.json")
    json.dump({"seed": PB3_ORDER_SEED, "order": operating_order},
              open(order_path, "w"), indent=1)

    rng = random.Random(PB3_ARM_SEED)
    arm_order = ["CT"] * 225 + ["TC"] * 225
    rng.shuffle(arm_order)
    assert arm_order.count("CT") == 225 and arm_order.count("TC") == 225
    arm_path = os.path.join(CORPUS_DIR, "ARM_ORDER.json")
    json.dump({"seed": PB3_ARM_SEED, "order": arm_order,
               "balance": {"CT": 225, "TC": 225}}, open(arm_path, "w"), indent=1)
    arm_sha = sha_file(arm_path)

    rng = random.Random(PB3_PROMO_SEED)
    promo_order = (["PC"] * 6 + ["CP"] * 6)
    rng.shuffle(promo_order)
    promo_path = os.path.join(CORPUS_DIR, "PROMOTION_ORDER.json")
    json.dump({"seed": PB3_PROMO_SEED, "order": promo_order}, open(promo_path, "w"), indent=1)

    manifest = {
        "seeds": {"corpus": PB3_CORPUS_SEED, "operating_order": PB3_ORDER_SEED,
                  "arm_order": PB3_ARM_SEED, "promotion_order": PB3_PROMO_SEED},
        "counts": {"discovery": N_DISCOVERY, "promotion": N_PROMOTION,
                   "operating": N_OPERATING},
        "corpus_sha256": corpus_sha,
        "arm_order_sha256": arm_sha,
        "pb2_contacted_excluded": len(contacted_hashes),
        "prior_econ_excluded_from_clean": len(prior_hashes),
        "operating_disjoint_from_pb2_contacted": True,
        "clean_disjoint_from_prior_and_pb2_contacted": True,
    }
    json.dump(manifest, open(os.path.join(CORPUS_DIR, "MANIFEST.json"), "w"), indent=1)
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
