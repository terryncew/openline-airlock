"""PAYBACK-001 empirical-null calibration (offline).

Uses ONLY preserved identical-method replicated observations:
ECON-001 rep1, 36 task x method cells x 3 true replicate attempts each.
The same method plays both "control" and "treatment", so any cumulative
terminal advantage over a synthetic H=450 paired horizon is pure
operating noise by construction. Acquisition debt D = 0 in the null.

Procedure (frozen): for each synthetic task, draw a cell uniformly, then
draw an ordered pair of distinct attempts (control, treatment) uniformly;
delta = control_cost - treatment_cost. Sum 450 deltas -> one synthetic
null terminal advantage. Repeat N_SIM times with the declared seed.

Variants (sensitivity): V2 with-replacement pairs; V3 per-cell Gaussian;
V4 pooled (destroys cell structure); V5 half the cells; V1b reseed.

The frozen strong-positive margin is V1 p99. Wording (frozen):
"Under preserved identical-method empirical-null resampling, X of N
simulated 450-task horizons exceeded the frozen terminal margin."
This is NOT a true population false-positive probability.

No provider contact. No ECON-001/002 modification.
"""
from __future__ import annotations

import itertools
import json
import os
import random
import statistics as st
import sys
from collections import defaultdict

sys.path.insert(0, "/home/hatch/workspace/openline-airlock/study/payback-001")
import frozen as F  # noqa: E402

LEDGER = "/home/hatch/workspace/openline-airlock/study/econ-001/runs/study-003/ledger.jsonl"
STUDY = "/home/hatch/workspace/openline-airlock/study/payback-001"
H, N_SIM, SEED = F.H, F.NULL_N_SIM, F.NULL_SEED


def load_cells():
    cells = defaultdict(list)
    for line in open(LEDGER):
        e = json.loads(line)
        if e.get("kind") != "settle":
            continue
        p = e["invocation_id"].split("_")
        if len(p) < 4 or p[0] != "rep1" or p[2] not in ("A", "B", "C"):
            continue
        cells[(p[1], "_".join(p[3:]))].append(e["actual"])
    cells = {k: v for k, v in cells.items() if len(v) == 3}
    assert len(cells) == 36, len(cells)
    return cells


def ordered_deltas(vals, with_replacement=False):
    op = itertools.product(range(len(vals)), repeat=2)
    return [vals[a] - vals[b] for a, b in op
            if with_replacement or a != b]


def summarize(terms):
    terms = sorted(terms)
    n = len(terms)
    q = lambda p: terms[min(int(p * n), n - 1)]
    return {"n_sim": n, "H": H, "mean": st.mean(terms), "sd": st.stdev(terms),
            "min": terms[0], "median": q(0.50), "p90": q(0.90),
            "p95": q(0.95), "p99": q(0.99), "max": terms[-1]}


def run_v1(cells, seed, n_sim=N_SIM):
    """Primary: uniform over cells x uniform over 6 ordered distinct pairs."""
    pool = [d for v in cells.values() for d in ordered_deltas(v)]
    assert len(pool) == len(cells) * 6
    rng = random.Random(seed)
    return summarize(sum(rng.choices(pool, k=H)) for _ in range(n_sim))


def run_v2(cells, seed):
    pool = [d for v in cells.values() for d in ordered_deltas(v, True)]
    rng = random.Random(seed)
    return summarize(sum(rng.choices(pool, k=H)) for _ in range(N_SIM))


def run_v3(cells, seed):
    """Parametric: delta ~ Normal(0, sd_cell*sqrt(2)), cell drawn uniformly."""
    sds = [st.stdev(v) * (2 ** 0.5) for v in cells.values()]
    rng = random.Random(seed)
    terms = []
    for _ in range(N_SIM):
        terms.append(sum(rng.gauss(0.0, rng.choice(sds)) for _ in range(H)))
    return summarize(terms)


def run_v4(cells, seed):
    allv = [x for v in cells.values() for x in v]
    pool = ordered_deltas(allv, True)
    rng = random.Random(seed)
    return summarize(sum(rng.choices(pool, k=H)) for _ in range(N_SIM))


def run_v5(cells, seed):
    half = dict(random.Random(seed).sample(list(cells.items()), 18))
    return run_v1(half, seed + 1)


def load_cells_r2():
    """Independent replicate sample: ECON-001 R2 rep1-form cells (13 cells)."""
    import re
    cells = defaultdict(list)
    for line in open("/home/hatch/workspace/openline-airlock/"
                     "study/econ-001/runs/study-002/ledger.jsonl"):
        e = json.loads(line)
        if e.get("kind") != "settle":
            continue
        m = re.match(r"rep1_g[123]_([ABC])_(.+)$", e["invocation_id"])
        if not m:
            continue
        cells[m.group(2)].append(e["actual"])
    cells = {k: v for k, v in cells.items() if len(v) == 3}
    assert len(cells) >= 10, len(cells)
    return cells


def main():
    cells = load_cells()
    out = {"source": "econ-001 rep1: 36 cells x 3 identical-method replicates",
           "H": H, "n_sim": N_SIM, "seed": SEED, "D": 0,
           "null_composition": "36 config-family identical-method cells; "
           "operating horizon is logic-family. Phase-2 found config the "
           "wider-tailed family, so this margin is conservative for a "
           "logic horizon (harder to earn strong positive)."}
    out["V1_primary"] = run_v1(cells, SEED)
    out["margin"] = {"p99": out["V1_primary"]["p99"]}
    out["V2_with_replacement"] = run_v2(cells, SEED + 1)
    out["V3_parametric"] = run_v3(cells, SEED + 2)
    out["V4_pooled"] = run_v4(cells, SEED + 3)
    out["V5_half_cells"] = run_v5(cells, SEED + 4)
    out["V1b_reseed"] = run_v1(cells, SEED + 100)
    try:
        r2cells = load_cells_r2()
        out["V6_r2_cells"] = run_v1(r2cells, SEED + 200)
    except AssertionError as e:
        out["V6_r2_cells"] = {"skipped": str(e)}
    os.makedirs(STUDY + "/null", exist_ok=True)
    json.dump(out, open(STUDY + "/null/NULL_CALIBRATION.json", "w"), indent=1)
    for k in ("V1_primary", "V2_with_replacement", "V3_parametric",
              "V4_pooled", "V5_half_cells", "V1b_reseed", "V6_r2_cells"):
        r = out[k]
        if "skipped" in r:
            print(k, "SKIPPED:", r["skipped"])
            continue
        print(k, {kk: round(v, 6) for kk, v in r.items()
                  if kk not in ("n_sim", "H")})
    print("FROZEN MARGIN p99 =", round(out["margin"]["p99"], 6))


if __name__ == "__main__":
    main()
