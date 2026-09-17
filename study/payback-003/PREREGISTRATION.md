# PAYBACK-003 — Preregistration

**Study ID:** `payback003`
**Branch:** `study/payback-003`
**Status:** FROZEN — apparatus-corrected repeat. No paid contact authorized by this document.

---

## 0. Explicit status statement (required)

**This is a NEW study, not a continuation. It is an apparatus-corrected
repeat of PAYBACK-002, not a new scientific design.**

PAYBACK-002 (`payback002`) is closed as **INCOMPLETE** (terminal evidence
commit `b295e12ad3cbf3ffc89d128c5f7fa2285fcffbc4`). It made **real provider
contact** and fixed the central PAYBACK-001 problem: clean preflight,
completed acquisition (D = $0.372212), an accepted successor (promotion 12/12
vs 12/12, ratio 1.0175), and 171/450 operating tasks with zero regressions —
then two transport failures and runner death with no `RUN_STATUS.json` before
the frozen horizon completed. No verdict was earned on the payback question.
This is NOT a negative payback result.

PAYBACK-001 (`payback001`) remains **INCOMPLETE_APPARATUS_DEFECT**, untouched.
PAYBACK-002 remains **INCOMPLETE**, untouched: no rescue, no run-directory
modification, no `RUN_STATUS.json` regeneration, no stdout/stderr
reconstruction, no in-place accounting repair, no continuation at task 171,
no horizon extension, no threshold movement from the partial curve, no
retroactive completion from the accepted successor.

**Why the repeat is earned:** PAYBACK-002 made real scientific contact and
fixed the central PAYBACK-001 problem, but the payback question remained
unresolved because the apparatus died before the frozen horizon. A fresh
apparatus-corrected repeat is therefore scientifically legitimate. The
171-task partial curve stays visible as evidence; it is not a terminal answer
and does not justify modifying this study.

**Scientific constants are intentionally carried forward rather than
re-derived** to avoid introducing post-failure researcher degrees of freedom.
The horizon is NOT shortened because A(171) was negative. The method is NOT
tuned on the PAYBACK-002 partial result.

PAYBACK-003 independently earns its own acquisition, candidate, promotion
result, acquisition debt D, operating curve, and terminal verdict. The
PAYBACK-002 accepted successor and its $0.372212 debt are NOT imported.

If implementation requires any scientific change beyond what is declared
here, the freeze must STOP and the change must be reported before any
contact. No such change was required.

---

## 1. The frozen scientific question

**CAN ONE BOUNDED IMPROVEMENT INVESTMENT REPAY ITS OWN ACQUISITION COST OVER A
FROZEN FUTURE WORK HORIZON WHILE PRESERVING RECEIVER-VERIFIED QUALITY?**

One bounded treatment acquisition (≤ $3.50, K ≤ 1 accepted successor) against
a frozen 450-task operating horizon with receiver-verified quality.

---

## 2. Frozen design (carried forward from PAYBACK-002)

| Element | Value |
|---|---|
| Horizon H | 450 operating tasks |
| K_MAX | 1 accepted successor |
| Corpus | 465 FRESH tasks: 3 discovery / 12 promotion / 450 operating (new declared seeds; see §7) |
| Corpus SHA-256 | `211c1416caf635fe7dba311aae62ee20833b69dd52f2df636ed982cd1653c158` |
| Arm-order SHA-256 | `917bf8d9da0ad8ec9667b307c2e7e667208247f6b73d1f481c44e18901a64eab` |
| Arm balance | 225 CT / 225 TC (frozen schedule) |
| Discovery allocation | 3 tasks, parent method, frozen indices |
| Promotion allocation | 12 tasks × 2 arms, frozen per-pair order |
| Operating order | frozen 450-task order + frozen arm schedule |
| NULL_MARGIN_99 | $0.26926 (byte-identical PAYBACK-002 calibration, 20,000 sims, seed 20260916) |
| Acquisition acceptance | parent 12/12, candidate 12/12, zero regressions, candidate promo cost ≤ 1.5× parent (operational safety cap, NOT the economic criterion) |
| Accounting | D = settled + retained acquisition cost (preflight EXCLUDED); d_i = control_i − treatment_i; A(t) = Σ_{i≤t} d_i − D; break-even = first t with A(t) > 0 |
| Physical ceiling | $18.00, ledger-enforced, never raised post-contact |
| Per-call reservation | $0.11 |
| Call inventory | 928 scientific (3 discovery + 1 proposal + 24 promotion + 900 operating) + 1 non-scientific preflight |

**Terminal states (frozen):**

- `A(450) ≤ 0` → **NO_PAYBACK** (negative)
- `0 < A(450) ≤ $0.26926` → **NOMINAL_NOT_BEYOND_NULL** (not strong)
- `A(450) > $0.26926` → **STRONG_POSITIVE** (iff quality preserved)
- treatment fails a task the control passes → strong positive **VOID**
- no accepted successor → operating skipped; debt-only negative
- horizon incomplete (halt, stop, budget abort, circuit-breaker trip) → **INCOMPLETE** (never rescued)
- preflight not clean → **INCOMPLETE_PREFLIGHT** (fail-closed; see §4)

**No-rescue rules (frozen):** after the first PAYBACK-003 scientific provider
contact (the first acquisition dispatch after a clean preflight), no code
repair; no relaunch; no task replacement; no seed swap; no candidate
substitution; no threshold movement; no horizon extension; no
accounting-formula change; no transport-policy change; no rescue. Preserve
what happened.

**Explicitly NOT authorized:** reopening or rescuing PAYBACK-001 or
PAYBACK-002, running Q6′, any ECON-001/ECON-002 repair or rerun, or creating
PAYBACK-004 automatically if this study ends INCOMPLETE on infrastructure
(see §9).

---

## 3. What changed vs PAYBACK-002 (apparatus only — earned by PAYBACK-002)

| # | PAYBACK-002 | PAYBACK-003 |
|---|---|---|
| 1 | `payback_acct.compute` read `e["retained"]` for unresolved entries; the real ledger writes `"reservation"` → `KeyError` on any real ledger with unresolved entries (found after contact, never repaired per no-rescue) | Reader accepts either key (`e["retained"]` if present else `e["reservation"]`). Frozen economic formulas unchanged. Regression fixture uses a real-format unresolved entry. |
| 2 | The runner was the sole authority for reporting its own death; when it died, no `RUN_STATUS.json`, no stdout/stderr, no exit record survived | External launch/supervision layer (`scripts/supervise.py`): durable stdout/stderr capture from process start, PID/start metadata, exit code/signal, heartbeat/progress marker, and an infrastructure terminal record (`INFRA_TERMINAL.json`) on unexpected exit. The supervisor classifies the termination; it never invents scientific observations and never rewrites scientific artifacts. The paid path runs under the supervisor. |
| 3 | Two transport failures then silent runner death; nothing stopped the study deterministically | Deterministic transport circuit breaker (`F.INFRA_BREAKER_N = 3`): 3 consecutive provider posts failing before any usable HTTP response (timeouts, connection refused/reset, remote-closed) halt the study as infrastructure-INCOMPLETE via `InfraCircuitBreaker`. HTTP error statuses are not counted (the provider responded); a completed post resets the streak; the trip is one-way; unresolved reservations stay retained. |
| 4 | Invocation IDs `pb2-*`; study `payback002`; runs under `runs/payback002/` | Invocation IDs `pb3-*`; study `payback003`; runs under `runs/payback003/` (fresh namespace; evidence separation) |
| 5 | Corpus reused byte-identical from PAYBACK-001 | Fresh 465-task corpus, new declared seeds (see §7) |

No economic-equation change. No acquisition-debt-definition change. No
promotion-rule change. No 12/12 change. No regression-rule change. No
cost-ratio-cap change. No horizon change. No break-even-definition change. No
null-margin change. No model/provider-configuration change. No arm-semantics
change. No CT/TC-balancing change. No one-attempt-per-arm change. No
accounting-formula change. No unresolved-reservation-treatment change. No
result-vocabulary change. No no-rescue-rule change.

**Capability-economics guard:** the three repairs total ~206 new/changed
non-test lines (supervisor ~144, breaker ~55, accounting ~7), within the
250-line guard. No daemon/service architecture, no cross-repo infrastructure,
no workflow engine, no new accounting system, no provider-abstraction
redesign.

---

## 4. Fail-closed preflight gate (exact condition, unchanged)

The preflight performs **exactly one** provider post. Scientific acquisition
may begin **only if all of the following hold**:

1. exactly one provider post occurred (no retries exist);
2. `result.status == "ok"`;
3. a usage object exists with `input_tokens` and `output_tokens`;
4. a settled actual cost exists (`actual_usd is not None`);
5. the corresponding ledger reservation is **settled**, not unresolved;
6. the provider response was persisted on the worker's normal raw-evidence path;
7. the accounting layer can read the resulting ledger;
8. supervision/log capture is live (preflight runs under the supervisor).

Any other preflight state produces **INCOMPLETE_PREFLIGHT** and STOP: zero
scientific reservations, zero scientific calls. A failed preflight is never
reinterpreted as scientific debt. Preflight remains non-scientific and
excluded from D. Repair before scientific contact is permitted only if the
frozen scientific contract is unchanged.

---

## 5. Invocation taxonomy (frozen, fresh namespace)

- `pb3-pre-00` — the single non-scientific preflight
- `pb3-d-00` … `pb3-d-02` — discovery (3)
- `pb3-p` — proposal (1)
- `pb3-m-P-00` … `pb3-m-P-11`, `pb3-m-C-00` … `pb3-m-C-11` — promotion (24)
- `pb3-o-C-0000` … `pb3-o-C-0449`, `pb3-o-T-0000` … `pb3-o-T-0449` — operating (900)

Run directory: `study/payback-003/runs/payback003/`. PAYBACK-001 and
PAYBACK-002 evidence is never reused or overwritten. The supervisor adds
`console.out`, `console.err`, `SUPERVISION.json`, `HEARTBEAT.json`, and (only
on unexpected termination) `INFRA_TERMINAL.json` to the run directory.

---

## 6. Budget (mechanically recomputed, unchanged)

- Scientific inventory: 3 + 1 + 24 + 900 = **928 calls** (unchanged).
- Non-scientific preflight: 1 call, reservation $0.01, excluded from D.
- Physical ceiling: **$18.00** (unchanged; ledger-enforced, fresh ledger).
- Worst-plausible arithmetic: $3.50 acquisition cap + 900 × $0.013134
  (frozen mean task cost) = **$15.32 < $18.00**. Ceiling remains valid;
  it was not increased.
- Expected settled ≈ $12.2 (acquisition ~$0.37 + operating ~$11.82).
- Outstanding retained exposure honored separately: PAYBACK-002's $0.22
  (2 × $0.11 unresolved operating reservations) remains reserved and is not
  released by this study. PAYBACK-003 does not launch unless the full new
  $18.00 ceiling is available after honoring all outstanding retained
  exposure.

---

## 7. Fresh corpus: procedure, seeds, and the declared apparatus-limit adaptation

**Procedure (same frozen population/sampling procedure):** over-generate with
derived seeds (`{seed}:gen{k}`, 2000 draws per batch via the preserved ECON
`corpus.build_corpus`), keep the first 465 draws whose content hash
(statement + target_code + hidden_tests, canonical JSON, SHA-256) is new
under the applicable exclusion set. Declared seeds:

| Stream | Seed |
|---|---|
| Corpus generation | 20260926 |
| Operating permutation | 20260927 |
| Arm-order schedule | 20260928 |
| Promotion order | 20260929 |

**Apparatus limit (frozen finding, declared pre-contact):** the preserved
ECON generator's reachable task space is 815 distinct tasks (verified by
saturation: 80,000 draws → 815 unique). PAYBACK-002 consumed 465 of the 482
instances disjoint from prior ECON scientific instances, leaving 17. A fully
fresh-from-everything 465-task corpus is therefore an apparatus
impossibility — not a design choice.

**Declared exclusion-set adaptation (pre-contact, mechanical):**

- Discovery (3) + promotion (12): drawn disjoint from prior ECON scientific
  instances (333) AND from PAYBACK-002's provider-contacted instances (186).
  The method is developed and promoted on fully clean tasks.
- Operating (450): drawn disjoint from PAYBACK-002's provider-contacted
  instances (186: 3 discovery + 12 promotion + 171 operating attempts;
  content-hash verified, zero overlap). These tasks are unseen by the
  PAYBACK-003 successor (developed only on PAYBACK-003 discovery tasks);
  reuse of prior ECON instances is permitted here by the apparatus limit.

Disjointness was verified mechanically at generation time and re-verified by
the offline tests (§8). This adaptation is declared before any PAYBACK-003
contact and is not tuned on any result.

---

## 8. Offline qualification (all green before contact)

93 offline checks pass with zero provider contact
(`tests/test_offline.py`, `ALL OFFLINE TESTS PASSED (A + B)`):

- **Part A — frozen contract:** RealProvider construction; clean preflight
  passes; all six dirty-preflight states → INCOMPLETE_PREFLIGHT with zero
  scientific calls; exactly-one-post; no retries; preflight excluded from D;
  fresh corpus (new SHA, 465 tasks, pb3 namespace, 465 content-distinct,
  allocation 3/12/450, 225/225 arm balance, declared disjointness
  re-verified); 928-call inventory; H=450; NULL_MARGIN_99=$0.26926 with the
  null calibration byte-identical to PAYBACK-002's; K_MAX=1; $18.00 ceiling;
  1.5× promo cap; INFRA_BREAKER_N=3; payback003/pb3-* identity; all
  terminal-state/accounting tests (STRONG_POSITIVE, NO_PAYBACK,
  NOMINAL_NOT_BEYOND_NULL, VOID_QUALITY_REGRESSION, INCOMPLETE,
  INCOMPLETE_PREFLIGHT, break-even).
- **Part B — fault qualification (no paid calls needed):**
  - B1: real-format unresolved ledger entry → correct settled + retained
    totals, no KeyError; legacy key accepted; formulas unchanged;
    compute() deterministic under exact replay.
  - B2: 3 consecutive transport failures trip the breaker; success resets
    the streak; HTTP 500s and credential failures don't count; trip is
    one-way; `_attempt` raises `InfraCircuitBreaker` once tripped;
    unresolved reservations stay retained; a breaker-halted run reads
    INCOMPLETE in accounting (never rescued).
  - B3/B4/B5: supervisor — runner death (exit 3, no RUN_STATUS.json) and
    SIGKILL produce `INFRA_TERMINAL.json` classifying unexpected
    termination; exit 0 without RUN_STATUS.json → unexpected; clean
    completion (exit 0 with RUN_STATUS.json) → expected with no infra
    record; stdout/stderr durably captured from process start; PID, exit
    code/signal, heartbeat persisted; infra record is infrastructure
    evidence only (fixed schema, no scientific observation invented, no
    scientific artifact rewritten); finalize idempotent (byte-identical
    on replay).

---

## 9. What happens after contact

Scientific contact begins with the first PAYBACK-003 acquisition provider
dispatch after a clean preflight. After that: **no repair, no relaunch, no
task replacement, no seed swap, no candidate substitution, no threshold
movement, no horizon extension, no accounting-formula change, no
transport-policy change, no rescue.** If infrastructure prevents completion
after contact: **INCOMPLETE** again.

PAYBACK-003 is the final automatically earned apparatus-corrected repeat. If
PAYBACK-003 also ends INCOMPLETE because of infrastructure, PAYBACK-004 is
NOT created automatically: the second infrastructure failure is frozen and
an apparatus reliability qualification is opened instead.

---

## 10. Maximum earned claims

**Maximum positive claim (only if the frozen run earns it):**
"A single bounded treatment acquisition (≤ $3.50, K ≤ 1) repaid its own
acquisition cost over the frozen 450-task operating horizon: A(450) exceeded
the frozen empirical-null margin of $0.26926 while preserving
receiver-verified quality (12/12 promotion quality gate, zero operating
regressions)."

**Maximum negative claim (only if the frozen run earns it):**
"The frozen acquisition produced no accepted successor, or the accepted
successor did not repay its acquisition cost over the frozen 450-task horizon
(A(450) ≤ 0, or ≤ $0.26926 for the not-strong variant), under the frozen
acceptance rule and accounting."

**What this study cannot establish even on success:** that cheaper methods
don't exist elsewhere, that the saving generalizes beyond the frozen corpus,
that recursive improvement is possible or impossible, or anything about
regimes with quality headroom. One bounded investment, one frozen horizon.

---

## 11. Authorization boundary

This preregistration authorizes: new study identity, the three declared
apparatus repairs, offline tests, fault qualification, and this freeze.
**It does NOT authorize paid contact.** Execution requires a fresh explicit
authorization after remote verification of the frozen commit, exactly as
PAYBACK-001 and PAYBACK-002 did.
