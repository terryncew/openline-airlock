"""ECON-001-R3 corpus generation.

Fresh corpus for the repaired-protocol confirmatory run (R3), disjoint by
content-hash from every task the model could have seen in launches 1/2
(corpus.json, all pools) and R2 (corpus_r2.json, all pools). Collisions are
regenerated with deterministic sub-seeds, preserving family mix.

Frozen generator (src/econ/corpus.py, unchanged). Master seed declared
before generation: 20260917. Zero network, zero spend.
"""
import hashlib
import json
import random
import sys

sys.path.insert(0, "src")

from econ import corpus, evaluate, tokens

MASTER_SEED = 20260917
OUT_PATH = "corpus/corpus_r3.json"


def content_hash(t):
    h = hashlib.sha256()
    h.update(json.dumps({
        "family": t.family, "statement": t.statement,
        "target_code": t.target_code, "template": t.template,
    }, sort_keys=True).encode())
    return h.hexdigest()


def main():
    excluded = set()
    for path in ("corpus/corpus.json", "corpus/corpus_r2.json"):
        for tasks in corpus.load_corpus(path).values():
            for t in tasks:
                excluded.add(content_hash(t))
    print(f"exclusion set: {len(excluded)} prior task contents")

    families = ["logic", "interface", "config"]
    pools = {}
    regen_counts = {"eval": 0, "calib": 0}
    for pool, n in (("eval", 162), ("calib", 3)):
        rng = random.Random(f"{MASTER_SEED}:{pool}")
        tasks = []
        for i in range(n):
            fam = families[i % 3]
            tid = f"r3-{pool[:3]}-{fam[:4]}-{i:04d}"
            t = corpus.generate_task(fam, rng, tid)
            k = 0
            while content_hash(t) in excluded:
                k += 1
                r2 = random.Random(f"{MASTER_SEED}:regen:{pool}:{i}:{k}")
                t = corpus.generate_task(fam, r2, tid)
            if k:
                regen_counts[pool] += 1
                print(f"  regen {pool}[{i}] after {k} collision(s)")
            excluded.add(content_hash(t))  # within-run dedup
            tasks.append(t)
        pools[pool] = tasks
    pools["dev"] = []

    # Integrity: reference passes hidden tests, buggy fails, packet in cap.
    n_ref = n_bug = n_cap = 0
    for pool in ("eval", "calib"):
        for t in pools[pool]:
            v, _ = evaluate.evaluate(
                corpus.TARGET_FILENAME, t.reference_code,
                t.support_files, t.hidden_tests)
            n_ref += (v == 1)
            v2, _ = evaluate.evaluate(
                corpus.TARGET_FILENAME, t.target_code,
                t.support_files, t.hidden_tests)
            n_bug += (v2 == 0)
            n_cap += (tokens.count(t.packet()) <= 3000)
    total = 162 + 3
    print(f"reference_passes={n_ref}/{total} buggy_fails={n_bug}/{total} "
          f"packet_in_cap={n_cap}/{total}")
    assert n_ref == total and n_bug == total and n_cap == total

    pool_hashes = corpus.freeze_corpus(pools, OUT_PATH)
    for p, h in pool_hashes.items():
        print(f"pool {p}: {h}")
    file_sha = hashlib.sha256(open(OUT_PATH, "rb").read()).hexdigest()
    print(f"file sha256: {file_sha}")
    print(f"regenerations: {regen_counts}")


if __name__ == "__main__":
    main()
