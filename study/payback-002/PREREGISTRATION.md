# PAYBACK-002 — Preregistration

**Study ID:** `payback002`
**Branch:** `study/payback-002`
**Status:** FROZEN — apparatus-only repeat. No paid contact authorized by this document.

---

## 0. Explicit status statement (required)

**This is an apparatus-corrected repeat of PAYBACK-001, not a new scientific design.**

PAYBACK-001 (`payback001`) is closed as **INCOMPLETE_APPARATUS_DEFECT**. It made
**zero provider contact** and obtained **zero scientific provider data**: the
runner instantiated the abstract base `worker.Provider()`, whose `post()`
raises `NotImplementedError` before any request bytes exist, and the preflight
gate was not fail-closed, so four scientific attempts were incorrectly issued
after an unresolved preflight (all failing before dispatch as well).

**Scientific constants are intentionally reused rather than regenerated** to
avoid introducing post-failure researcher degrees of freedom. Regenerating the
corpus, the null calibration, or the task schedule after seeing the failure
would let the failure shape the design. The apparatus failed; the design was
never tested.

The only changes are:

1. **Provider → RealProvider for live dispatch** (`make_live_provider()`).
2. **Preflight becomes a strict fail-closed gate** requiring clean settled
   usage before any scientific reservation or contact.

If implementation requires any other scientific change, the freeze must STOP
and the change must be reported before any contact. No such change was required.

---

## 1. The frozen scientific question

**CAN ONE BOUNDED IMPROVEMENT INVESTMENT REPAY ITS OWN ACQUISITION COST OVER A
FROZEN FUTURE WORK HORIZON WHILE PRESERVING RECEIVER-VERIFIED QUALITY?**

One bounded treatment acquisition (≤ $3.50, K ≤ 1 accepted successor) against
a frozen 450-task operating horizon with receiver-verified quality.

---

## 2. Frozen design (unchanged from PAYBACK-001)

| Element | Value |
|---|---|
| Horizon H | 450 operating tasks |
| K_MAX | 1 accepted successor |
| Corpus | 465 tasks: 3 discovery / 12 promotion / 450 operating (byte-identical to PAYBACK-001) |
| Corpus SHA-256 | `f7879ba68c664600469588caf637e6a048c581f04fd44271a4848f8863e10a69` |
| Arm-order SHA-256 | `97558f018d6138db1ac383ec048ba998acae8f08b0dd243934a0cb1c4724a560` |
| Arm balance | 225 CT / 225 TC (frozen schedule) |
| Discovery allocation | 3 tasks, parent method, frozen indices |
| Promotion allocation | 12 tasks × 2 arms, frozen per-pair order |
| Operating order | frozen 450-task order + frozen arm schedule |
| NULL_MARGIN_99 | $0.26926 (byte-identical PAYBACK-001 calibration, 20,000 sims, seed 20260916) |
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
- horizon incomplete (halt, stop, budget abort) → **INCOMPLETE** (never rescued)
- preflight not clean → **INCOMPLETE_PREFLIGHT** (fail-closed; see §4)

**No-rescue rules (frozen):** after the first scientific provider contact, no
code repair or relaunch under study ID `payback002`; no threshold movement; no
task substitution; no horizon extension; no new null calibration; no new
candidate-generation strategy; no prompt optimization; no router; no recursion;
no cheaper-worker experiment; no extra acquisition round. Preserve what happened.

**Explicitly NOT authorized:** reopening PAYBACK-001, running Q6′, any
ECON-001/ECON-002 repair or rerun.

---

## 3. What changed vs PAYBACK-001 (apparatus only)

| # | PAYBACK-001 | PAYBACK-002 |
|---|---|---|
| 1 | `paid()` constructed `worker.Provider()` (abstract base) | `paid()` constructs `make_live_provider()` → `worker.RealProvider()` (one-shot `/v1/responses`, no retry). The provider implementation itself is unmodified preserved ECON code. |
| 2 | Preflight invoked but not gated: scientific calls proceeded after an unresolved preflight | Preflight is a strict fail-closed gate (`preflight_gate()` / `run_preflight_gate()`). `--preflight` is mandatory in paid mode. Any non-clean preflight → `INCOMPLETE_PREFLIGHT`, zero scientific reservations, zero scientific calls. |
| 3 | Invocation IDs `pb1-*` | Invocation IDs `pb2-*` (fresh namespace; evidence separation) |
| 4 | `_op_index` hardcoded `"pb1"` | Parameterized via `F.INV_PREFIX` (mechanical, not scientific) |
| 5 | Accounting had no `INCOMPLETE_PREFLIGHT` state | Accounting recognizes the runner's `incomplete_preflight` status (required by the gate; not a scientific change) |

No threshold changes. No new tasks. No new null calibration. No new
candidate-generation strategy. No prompt optimization. No router. No recursion.
No cheaper-worker experiment. No extra acquisition round.

---

## 4. Fail-closed preflight gate (exact condition)

The preflight performs **exactly one** provider post. Scientific acquisition
may begin **only if all of the following hold**:

1. exactly one provider post occurred (no retries exist);
2. `result.status == "ok"`;
3. a usage object exists with `input_tokens` and `output_tokens`;
4. a settled actual cost exists (`actual_usd is not None`);
5. the corresponding ledger reservation is **settled**, not unresolved;
6. the provider response was persisted on the worker's normal raw-evidence path.

Any other preflight state — timeout, credential failure, connection failure,
HTTP error, missing usage, unresolved reservation, malformed provider response,
provider exception, provider path not verified — produces
**INCOMPLETE_PREFLIGHT** and STOP: zero scientific reservations, zero
discovery calls, zero proposal calls, zero promotion calls, zero operating
calls. A failed preflight is never reinterpreted as scientific debt.
Preflight remains non-scientific and excluded from D.

---

## 5. Invocation taxonomy (frozen, fresh namespace)

- `pb2-pre-00` — the single non-scientific preflight
- `pb2-d-00` … `pb2-d-02` — discovery (3)
- `pb2-p` — proposal (1)
- `pb2-m-P-00` … `pb2-m-P-11`, `pb2-m-C-00` … `pb2-m-C-11` — promotion (24)
- `pb2-o-C-0000` … `pb2-o-C-0449`, `pb2-o-T-0000` … `pb2-o-T-0449` — operating (900)

Run directory: `study/payback-002/runs/payback002/`. PAYBACK-001 evidence is
never reused or overwritten.

---

## 6. Budget (mechanically recomputed)

- Scientific inventory: 3 + 1 + 24 + 900 = **928 calls** (unchanged).
- Non-scientific preflight: 1 call, reservation $0.01, excluded from D.
- Physical ceiling: **$18.00** (unchanged; ledger-enforced).
- Worst-plausible arithmetic: $3.50 acquisition cap + 900 × $0.013134
  (frozen mean task cost) = **$15.32 < $18.00**. Ceiling remains valid;
  it was not increased.
- Expected settled ≈ $12.2 (acquisition ~$0.37 + operating ~$11.82).

---

## 7. Provenance of reused artifacts

PAYBACK-002 copies the PAYBACK-001 scientific artifacts byte-identical
(self-contained study; no cross-study runtime dependency). Byte identity
verified at build time and re-verified by the offline tests:

| Artifact | SHA-256 (pb1 source = pb2 copy) |
|---|---|
| corpus/corpus.json | `f7879ba68c664600469588caf637e6a048c581f04fd44271a4848f8863e10a69` |
| corpus/ARM_ORDER.json | `97558f018d6138db1ac383ec048ba998acae8f08b0dd243934a0cb1c4724a560` |
| corpus/ALLOCATION.json | `f76f99080d8abed8…` (full hashes in build log) |
| corpus/OPERATING_ORDER.json | `77e5306fb154174…` |
| corpus/PROMOTION_ORDER.json | `ef5865c37d007558…` |
| corpus/MANIFEST.json | `ce186c86fb1b1150…` |
| null/NULL_CALIBRATION.json | `b057921bc50b82ce…` |

PAYBACK-001 source: branch `study/payback-001`, preregistration commit
`225f64bd320a57bc0452281718224e42193154d7`, run evidence commit
`acdc0b4ccb637aaa2782996018c370628b6b44a0` (this branch's base).
**PAYBACK-001 artifacts and standing are untouched by this study.**

---

## 8. Maximum earned claims

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

## 9. Authorization boundary

This preregistration authorizes: new study identity, apparatus-only repair,
offline tests, and this freeze. **It does NOT authorize paid contact.**
Execution requires a fresh explicit authorization after remote verification
of the frozen commit, exactly as PAYBACK-001 did.
