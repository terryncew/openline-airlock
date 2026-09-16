"""PAYBACK-002 frozen study constants.

Apparatus-corrected repeat of PAYBACK-001 (study ID payback001, closed
INCOMPLETE_APPARATUS_DEFECT after zero provider contact). NOT a new
scientific design: every scientific constant below is intentionally reused
from PAYBACK-001 rather than regenerated, to avoid introducing post-failure
researcher degrees of freedom.

The only apparatus changes vs PAYBACK-001 (see PREREGISTRATION.md):
  1. live runner constructs worker.RealProvider() via make_live_provider()
     (PAYBACK-001 constructed the abstract base worker.Provider(); every
     invocation raised NotImplementedError before dispatch).
  2. the preflight is a strict fail-closed gate: scientific acquisition may
     begin ONLY after one clean settled preflight with provider usage;
     any other preflight state -> INCOMPLETE_PREFLIGHT, zero scientific calls.

Every value here is fixed BEFORE scientific contact. The offline() path of
payback_run.py re-derives each checkable value from the frozen artifacts and
refuses to proceed on any mismatch. Edit nothing after contact.
"""
from __future__ import annotations

STUDY_ID = "payback002"

# New branch from the preserved PAYBACK-001 failure evidence commit.
BASE_SHA = "acdc0b4ccb637aaa2782996018c370628b6b44a0"
# PAYBACK-001 preregistration base (scientific design source, untouched).
PB1_BASE_SHA = "9ccd19d853083b97f8aed4d30d8ff00c553a1f12"
PB1_RUN_SHA = "acdc0b4ccb637aaa2782996018c370628b6b44a0"

# --- Corpus / horizon (byte-identical copies of PAYBACK-001 artifacts) ---
# H=450 (NOT 700): the preserved ECON task generator's reachable space is
# ~815 distinct tasks, of which 482 are disjoint from prior scientific
# instances. 715 fresh tasks do not exist. H=450 (465 tasks total) is the
# largest clean horizon the apparatus supports. Power re-derived in
# PAYBACK-001 PREREGISTRATION.md; null recalibrated at H=450.
PB1_CORPUS_SEED = 20260921
PB1_ORDER_SEED = 20260924
PB1_ARM_SEED = 20260916
PB1_PROMO_SEED = 20260925
N_DISCOVERY, N_PROMOTION, N_OPERATING = 3, 12, 450
H = 450
K_MAX = 1  # at most one accepted successor

# Byte-identical to PAYBACK-001 (verified in offline tests; see PROVENANCE).
CORPUS_SHA256 = "f7879ba68c664600469588caf637e6a048c581f04fd44271a4848f8863e10a69"
ARM_ORDER_SHA256 = "97558f018d6138db1ac383ec048ba998acae8f08b0dd243934a0cb1c4724a560"

# --- Empirical-null terminal margin (byte-identical PAYBACK-001 calibration) ---
# Strong positive requires A(H) > NULL_MARGIN_99. Wording (frozen):
# "Under preserved identical-method empirical-null resampling, X of N
#  simulated 450-task horizons exceeded the frozen terminal margin."
# This is NOT a true population false-positive probability.
# Calibrated at H=450: V1 p99=0.26926; V1b 0.27434; V3 0.27091; V5 0.26376;
# V4 0.28671; V2 0.22056; V6 (independent R2 cells) 0.23100.
# Null composition: 36 config-family identical-method cells; horizon is
# logic-family. Config showed the wider tails (Phase-2), so the margin is
# conservative for a logic horizon.
NULL_MARGIN_99 = 0.26926
NULL_N_SIM = 20000
NULL_SEED = 20260916

# --- Acquisition acceptance (quality/sanity gate, NOT economic) ---
PROMO_TASKS = 12
PROMO_PASS = 12          # parent 12/12 and candidate 12/12 required
PROMO_COST_CAP = 1.5     # candidate paired promo cost <= 1.5 x parent.
# 1.5x is an operational safety bound: it keeps one explosive successor
# from making the 450-task horizon and the $18 budget meaningless.
# It is NOT the economic criterion; the frozen horizon decides.

# --- Money ---
BUDGET_TOTAL = 18.00     # physical ceiling; ledger-enforced.
# Covers acquisition cap ($3.50) + 900 operating tasks at the frozen mean
# task cost ($0.013134 -> $11.82) = $15.32 < $18. Expected settled ~$12.2
# (acquisition ~$0.37 + operating ~$11.82): 48% headroom. Breach of the
# ceiling aborts to INCOMPLETE (frozen rule); it is never raised post-contact.
PER_CALL_RESERVATION = 0.11
ACQUISITION_CAP = 3.50   # treatment acquisition spend hard cap

# Invocation-ID taxonomy (frozen prefixes; fresh pb2-* namespace).
INV_PREFIX = "pb2"
P_PRE, P_DISC, P_PROP = "pb2-pre", "pb2-d", "pb2-p"
P_PROMO_P, P_PROMO_C = "pb2-m-P", "pb2-m-C"
P_OP_C, P_OP_T = "pb2-o-C", "pb2-o-T"

# Maximum paid-call inventory (mechanically recomputed in offline()).
CALL_INVENTORY = {
    "preflight": 1,        # non-scientific; separate accounting
    "discovery": 3,
    "proposal": 1,
    "promotion": 24,       # 12 tasks x 2 arms
    "operating": 900,      # 450 tasks x 2 arms
}
