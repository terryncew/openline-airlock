"""PAYBACK-003 frozen study constants.

Apparatus-corrected repeat of PAYBACK-002 (study ID payback002, closed
INCOMPLETE after infrastructure failure mid-operating-phase: real provider
contact, clean preflight, acquisition complete, successor accepted, 171/450
operating tasks, then two transport failures and runner death with no
RUN_STATUS.json). NOT a new scientific design: every scientific constant
below is intentionally carried forward from the frozen PAYBACK-002 contract
rather than re-derived, to avoid introducing post-failure researcher degrees
of freedom.

PAYBACK-003 independently earns its own acquisition, candidate, promotion
result, acquisition debt D, operating curve, and terminal verdict. Nothing
is imported from PAYBACK-002's run: not the accepted successor, not D.

Apparatus repairs vs PAYBACK-002 (earned by PAYBACK-002, see
PREREGISTRATION.md; all frozen before PAYBACK-003 scientific contact):
  1. accounting schema: the real ledger records unresolved reservations
     under "reservation", not "retained"; the reader accepts either key.
     Frozen economic formulas unchanged.
  2. external launch/supervision layer (scripts/supervise.py): durable
     stdout/stderr capture from process start, PID/start metadata, exit
     code/signal, heartbeat, and an infrastructure terminal record when the
     runner exits unexpectedly without RUN_STATUS.json. It classifies the
     termination; it never invents scientific observations.
  3. deterministic transport circuit breaker: F.INFRA_BREAKER_N consecutive
     transport failures halt the study as infrastructure-INCOMPLETE.

Every value here is fixed BEFORE scientific contact. The offline() path of
payback_run.py re-derives each checkable value from the frozen artifacts and
refuses to proceed on any mismatch. Edit nothing after contact.
"""
from __future__ import annotations

STUDY_ID = "payback003"

# New study from the preserved PAYBACK-002 terminal evidence commit.
BASE_SHA = "b295e12ad3cbf3ffc89d128c5f7fa2285fcffbc4"
# PAYBACK-002 preregistration base (scientific design source, untouched).
PB2_BASE_SHA = "1e5c5a1fd698b0f9eb94d3adfcb25ea53e766173"
PB2_RUN_SHA = "b295e12ad3cbf3ffc89d128c5f7fa2285fcffbc4"

# --- Corpus / horizon (fresh instances, same frozen population/sampling
# procedure as PAYBACK-001/PAYBACK-002) ---
# H=450 (NOT 700): the preserved ECON task generator's reachable space is
# ~815 distinct tasks. PAYBACK-002 consumed 465 of the 482 instances disjoint
# from prior ECON work, leaving 17 — so a fully fresh-from-everything corpus
# is an apparatus impossibility. Declared pre-contact procedure adaptation:
# discovery (3) + promotion (12) are drawn disjoint from prior ECON instances
# AND from PAYBACK-002's provider-contacted instances; the 450-task operating
# corpus is drawn disjoint from PAYBACK-002's provider-contacted instances
# (186: 3 discovery + 12 promotion + 171 operating attempts) and may reuse
# prior ECON instances. The operating tasks are unseen by the PAYBACK-003
# successor (developed only on PAYBACK-003 discovery tasks). Disjointness is
# verified mechanically before the freeze. Power and null margin carried
# forward unchanged from the frozen contract.
PB3_CORPUS_SEED = 20260926
PB3_ORDER_SEED = 20260927
PB3_ARM_SEED = 20260928
PB3_PROMO_SEED = 20260929
N_DISCOVERY, N_PROMOTION, N_OPERATING = 3, 12, 450
H = 450
K_MAX = 1  # at most one accepted successor

# Fresh PAYBACK-003 corpus (frozen at the pre-contact freeze; verified by
# the offline tests against the frozen artifacts).
CORPUS_SHA256 = "211c1416caf635fe7dba311aae62ee20833b69dd52f2df636ed982cd1653c158"
ARM_ORDER_SHA256 = "917bf8d9da0ad8ec9667b307c2e7e667208247f6b73d1f481c44e18901a64eab"

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

# --- Infrastructure halt policy (apparatus, preregistered) ---
# Earned by PAYBACK-002: two transport failures then silent runner death.
# INFRA_BREAKER_N consecutive provider posts that fail before any usable
# HTTP response exists (timeouts, connection refused/reset, remote-closed)
# indicate provider/egress instability and halt the study as
# infrastructure-INCOMPLETE via InfraCircuitBreaker. HTTP error statuses
# are not counted (the provider responded); a completed post resets the
# streak; the trip is one-way. Unresolved reservations stay retained.
INFRA_BREAKER_N = 3

# Invocation-ID taxonomy (frozen prefixes; fresh pb3-* namespace).
INV_PREFIX = "pb3"
P_PRE, P_DISC, P_PROP = "pb3-pre", "pb3-d", "pb3-p"
P_PROMO_P, P_PROMO_C = "pb3-m-P", "pb3-m-C"
P_OP_C, P_OP_T = "pb3-o-C", "pb3-o-T"

# Maximum paid-call inventory (mechanically recomputed in offline()).
CALL_INVENTORY = {
    "preflight": 1,        # non-scientific; separate accounting
    "discovery": 3,
    "proposal": 1,
    "promotion": 24,       # 12 tasks x 2 arms
    "operating": 900,      # 450 tasks x 2 arms
}
