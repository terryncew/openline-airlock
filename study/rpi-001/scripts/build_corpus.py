"""RPI-001 corpus build: fresh tasks, declared seeds, integrity + disjointness gates.

Generates eval tasks with the FROZEN econ-001 corpus builder (no modifications
to study/econ-001/), re-IDs them deterministically, then gates:
  1. integrity: reference code PASSES hidden tests, buggy target FAILS them
     (local execution, zero provider contact);
  2. disjointness: target_code byte-distinct from every eval instance in the
     four prior frozen corpora (econ-001 corpus, corpus_r2, corpus_r3,
     econ-002 corpus).

Writes study/rpi-001/corpus/corpus.json + corpus_meta.json (seeds, hashes,
gate counts). Fails closed if fewer than NEEDED tasks survive the gates.
"""
import sys, os, json, hashlib, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(os.path.dirname(STUDY), "econ-001", "src"))
from econ import corpus as corpus_mod  # noqa: E402
from econ import evaluate  # noqa: E402
from econ.corpus import TARGET_FILENAME  # noqa: E402

SEEDS = list(range(20261000, 20261017))  # 17 declared seeds; 20260921-23
# exhausted (110/135 duplicates of prior corpora — small task space)
PER_SEED = 45            # 765 generated; need 100 after gates
NEEDED = 100             # must survive gates (89 allocated + 11 spares)

PRIOR_CORPORA = [
    "study/econ-001/corpus/corpus.json",
    "study/econ-001/corpus/corpus_r2.json",
    "study/econ-001/corpus/corpus_r3.json",
    "study/econ-002/corpus/corpus.json",
]


def repo_root():
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True, cwd=HERE)
    return out.stdout.strip()


def prior_target_codes(root):
    codes = set()
    for rel in PRIOR_CORPORA:
        p = os.path.join(root, rel)
        with open(p) as f:
            data = json.load(f)
        for pool, tasks in data.items():
            if not isinstance(tasks, list):
                continue
            for t in tasks:
                tc = t.get("target_code")
                if tc:
                    codes.add(tc)
    return codes


def main():
    root = repo_root()
    prior = prior_target_codes(root)
    print(f"prior target_code instances: {len(prior)}")

    raw = []
    for s in SEEDS:
        pools = corpus_mod.build_corpus(s, 0, PER_SEED, 0)
        for t in pools["eval"]:
            raw.append((s, t))
    # deterministic order: (seed, family, original index)
    raw.sort(key=lambda st: (st[0], st[1].family, st[1].task_id))
    print(f"generated: {len(raw)}")

    kept = []
    n_int_fail = 0
    n_dup = 0
    for s, t in raw:
        v_ref, _ = evaluate.evaluate(TARGET_FILENAME, t.reference_code,
                                     t.support_files, t.hidden_tests)
        v_bug, _ = evaluate.evaluate(TARGET_FILENAME, t.target_code,
                                     t.support_files, t.hidden_tests)
        if not (v_ref == 1 and v_bug == 0):
            n_int_fail += 1
            continue
        if t.target_code in prior:
            n_dup += 1
            continue
        kept.append((s, t))
    print(f"integrity failures: {n_int_fail}, prior-duplicates: {n_dup}, "
          f"kept: {len(kept)}")
    if len(kept) < NEEDED:
        raise SystemExit(
            f"FAIL-CLOSED: only {len(kept)} tasks survived gates, need {NEEDED}")

    tasks = kept[:NEEDED]
    # deterministic fresh IDs
    renamed = []
    for i, (s, t) in enumerate(tasks):
        d = t.to_dict()
        d["task_id"] = f"rpi-eva-{i:04d}"
        renamed.append(corpus_mod.Task(**d))

    out_path = os.path.join(STUDY, "corpus", "corpus.json")
    hashes = corpus_mod.freeze_corpus({"eval": renamed}, out_path)
    h = hashlib.sha256()
    for t in renamed:
        h.update(json.dumps(t.to_dict(), sort_keys=True).encode())
    meta = {
        "seeds": SEEDS,
        "per_seed": PER_SEED,
        "generated": len(raw),
        "integrity_failures": n_int_fail,
        "prior_duplicates": n_dup,
        "kept": len(renamed),
        "eval_sha256": hashes["eval"],
        "task_id_order_sha256": h.hexdigest(),
        "prior_corpora": PRIOR_CORPORA,
        "prior_target_code_count": len(prior),
    }
    with open(os.path.join(STUDY, "corpus", "corpus_meta.json"), "w") as f:
        json.dump(meta, f, indent=1, sort_keys=True)
    print(f"wrote {out_path} ({len(renamed)} tasks)")
    print(json.dumps(meta, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
