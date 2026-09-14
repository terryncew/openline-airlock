# RIL-ANOMALY-003 — matched anomaly-first research on the qualified API substrate

`RIL-ANOMALY-001` did not answer the matched question. Its anomaly arm produced two receiver-confirmed promotions, but the control arm was contaminated before round 1 when the Muse/Prince substrate surfaced treatment-arm memory. That run is frozen as inconclusive, and its lessons are not inherited here.

`RIL-ANOMALY-002` was built for the same question on a Gemini Temporary Chat substrate, but it never ran: the browser-automation transport failed before primary contact, and `RIL-RELAY-002` froze terminal on the unauthenticated host. The Gemini consumer route is abandoned for this program. `-002`'s lessons are not inherited here.

`RIL-API-ISOLATION-002` then qualified the replacement substrate at the API level: two paired canary trials over fresh independent Chat Completions requests showed exact exposure recall while independent blind requests returned `UNKNOWN`, with request/response SHA-256s, model identity, and usage recorded per call. That earns this successor, and only at the observable API-request boundary — provider-internal statelessness is not claimed.

RIL-ANOMALY-003 reruns the original causal question on the qualified API substrate, again without inheriting either arm's lessons from ANOMALY-001.

Two arms start from the same frozen RIL-RANK-LIVE-002 failure and the same empty accepted-lesson state. One receiver-private arm uses anomaly-first investigation; the other uses ordinary search. Both arms use the identical model (`gpt-6-astra`, bound from the frozen `-002` receipt — not renamed, not upgraded), the identical receiver evaluator, the identical 16-task frozen pool, four rounds each, and an identical $4-per-arm API ceiling ($8 total, inside the operator's $104.98 hard balance ceiling; no auto-reload, no credit purchase).

The substrate change from `-002` is deliberate: each round is ONE fresh independent Chat Completions request. There is no within-arm conversation retention at all — no thread, no previous-response ID, no model-native history. The receiver owns memory: every request carries only that arm's explicitly serialized accepted history (accepted head, that arm's accepted lessons, that arm's observed outcomes). The driver enforces arm separation by construction and fails closed on cross-arm contamination.

The researcher is told the truthful public task structure — 16 tasks, 12 opaque candidate IDs per task, choose 4 per task — and any proposal that selects candidates must specify an executable subset-selection rule over the actual frozen IDs. Invented labels or an unspecified "top four" quarantines the round.

The evaluator is a sealed receiver-side acceptance truth table, not a proxy: before any GPT contact, the receiver locally executed all 12 candidates of all 16 tasks (192 evaluations, done once) through the frozen RIL-RANK-EXEC-001 engine and sealed the complete acceptance truth. Scoring uses the original LIVE-002 acceptance semantics — a task succeeds iff an acceptable candidate appears in the proposed ordered four, with evaluations-to-first-success as its ordered position. GPT never sees the hidden truth or candidate implementations; packets carry only opaque IDs, public descriptions, and public features. No proxy coverage metric may trigger promotion — that was the rejected draft's flaw, and this package exists to replace it.

The receiver executes the rule against the sealed truth with the frozen deterministic scorer and independently decides PROMOTE / REJECT / QUARANTINE.

Primary outcome: receiver-confirmed `PROMOTE` count per arm. A difference of at least two promotions earns the corresponding arm advantage; anything smaller is no observed advantage; protocol, budget, or contamination failure is inconclusive. The receiver also records total evaluator work and actual API dollars per call and per arm, so verified improvement per dollar is computable.

## Claim boundary

If anomaly-first wins, the earned claim is exactly this:

"In one preregistered matched run, anomaly-first research produced at least two more receiver-confirmed promotions than ordinary search under the same starting evidence, researcher, evaluator, round budget, and API-cost ceiling."

Do not call that recursive self-improvement, Level 4, general superiority, or the final OpenLine RSI result.

## What this is not: the OpenLine RSI bar

The implemented mechanism here is a receiver-owned promotion ratchet over researcher proposals — the researcher proposes, the receiver independently executes and decides what survives. Whatever advantage the evidence demonstrates is an advantage of a research *method* (anomaly-first investigation) at producing receiver-confirmed improvements under this frozen protocol. It is not a system improving itself.

The eventual OpenLine RSI — Verifiable Recursive Self-Improvement release has a higher bar: the system must change its own improvement-generating method, independently earn promotion of that change, inherit it into fresh work, and beat a matched control on verified results per dollar. Nothing in this package implements that loop. Do not create or publish the `openline-rsi` repo until that full claim is earned.
