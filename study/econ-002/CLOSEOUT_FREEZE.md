# ECON-002 — Canonical closeout / freeze note

Study closed 2026-09-16. No further paid contact. No rerun. No rescue.

## Identity

- Study: ECON-002
- Study ID: `econ002_c72e6357`
- Authorized code SHA: `8d1d2131f75be12fe02b664b12875b1225998d00`
  (branch `study/econ-002`; preregistration + amendments A1/A2 frozen)
- Results SHA: `916895b6567a0645f722b78427665e9d18c5f48c`
- Operator authorization: single explicit `--authorize-paid-contact`
  for the remotely frozen amended study. Zero paid calls before it.
- Standing: `ECON-002_CLOSED_NO_LARGE_SUCCESSOR`

## Preregistered question

"Can any frozen candidate-generation strategy produce one successor
method that is at least 20% cheaper than the baseline while preserving
12/12 verified success on fresh paired tasks?"

## Receiver rule (frozen)

Same 12 fresh task IDs parent and candidate; one attempt each per task;
12/12 verified success required in both arms; zero per-task regressions;
candidate settled total ≤ 80% of parent settled total (IEEE-754, no
epsilon); unsettled calls contribute the full reservation (fail-closed).

## Candidate results (frozen order; verified from preserved artifacts)

| candidate | parent $ | candidate $ | ratio | 12/12 | regr. | decision |
|---|---|---|---|---|---|---|
| D1 delete CHECK | 0.154312 | 0.160444 | 1.0397 | yes/yes | 0 | reject |
| D2 delete REPRODUCE | 0.164808 | 0.156668 | 0.9506 | yes/yes | 0 | reject |
| D3 merge REPRODUCE+DIAGNOSE | 0.170264 | 0.160260 | 0.9412 | yes/yes | 0 | reject |
| D4 wording compression | 0.157404 | 0.153000 | 0.9720 | yes/yes | 0 | reject |
| S1 cost-aware model proposal | 0.160080 | 0.146232 | 0.9135 | yes/yes | 0 | reject |
| S2 cost-aware model proposal | 0.154904 | 0.152924 | 0.9872 | yes/yes | 0 | reject |

Accepted successor: NONE.

## Money (verified from preserved ledgers)

- Preflight: PASS — exactly 1 provider request, usage present, settled
  $0.000184 (own ledger, reservation $0.11).
- Scientific: 152/152 calls settled, zero unresolved, zero retained,
  settled $1.990608 of the $20.00 physical ceiling.
- Combined paid contact: $1.990792.

## Frozen earned negative claim

"None of the frozen candidate-generation strategies produced a
successor at least 20% cheaper than the paired baseline while
preserving 12/12 verified success on the frozen fresh-task evaluation."

Do not broaden this claim.

## Interpretation boundary

ECON-001 established that the original proposer was never instructed
to optimize the economic objective. ECON-002 corrected that defect
(verbatim cost objective in the Stage-2 prompt) and additionally
tested four deterministic subtraction/compression strategies. The
previous explanation — "the search failed merely because the proposer
had the wrong objective" — is therefore no longer sufficient.

Updated standing, narrower: on this saturated task regime, four frozen
deterministic compression strategies and two cost-aware model-proposed
strategies all preserved verified correctness, but none produced a
large (≥20%) execution-cost reduction. This weakens the simple
"complexity rises first, then obvious compression produces a large
cost drop" hypothesis.

This does NOT establish: that no cheaper method exists; that S1's
observed 8.6% saving is a real generalizable effect; that improvements
smaller than 20% do not exist; that the baseline is globally optimal;
that recursive economic improvement is impossible; or that harder or
different task regimes would behave the same way.

S1's 8.6% observed saving is descriptive only. The experiment was
deliberately calibrated not to accept an effect of that size. The
20% threshold is not moved after seeing the result.

## Capture limitation (recorded, not repaired)

The runner reused the literal `S2d`/`S2p` invocation-ID tags for both
Stage-2 candidates, so S2's discovery and proposal raw files overwrote
S1's. The S1 discovery/proposal raw response bytes are lost and are
not reconstructed.

The limitation does not invalidate the frozen promotion verdicts:
all 144 promotion raw files are preserved; all promotion request
bodies carrying the candidate methods are preserved; all 152
scientific ledger settlements are preserved; and the paired receiver
decisions depend on the promotion attempts, not on the missing
acquisition raw bytes.

Do not make detailed later claims about how S1's proposal was
generated from its missing discovery/proposal responses.

## No-rerun / no-rescue boundary

ECON-002 is closed. No repair of the runner. No rerun. No replacement
candidates. No threshold movement. No relaunch under the same study ID.
No ECON-003, no recursive compounding, no router, no multi-model
tournament, no further compression sweep, no lower-threshold rescue
study. The next experiment must be earned by a genuinely new
discriminating question, not by trying harder to obtain the desired
successor.

## Practical lesson

- ECON-001: wrong optimization objective → no accepted successor.
- ECON-002: correct objective + deterministic compression → still no
  large accepted successor.

The bottleneck has moved from an obvious prompt-specification defect
to a substantive empirical question about where meaningful efficiency
gains actually come from.

## Unresolved future hypotheses (hypotheses, not results)

- The baseline may already be near a local efficiency frontier for
  this saturated regime.
- Method text may not be the dominant driver of execution cost.
- Real attainable improvements may be smaller than the deliberately
  conservative 20% acceptance margin.
- A regime with quality headroom may expose different improvement
  opportunities.
