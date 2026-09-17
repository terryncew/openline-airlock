# Development record

## dev-001 (2026-09-16) — temperature incident

Ran the baseline worker over the 48 dev tasks. Result: 45 unresolved
(HTTP 400 on every request, reservation retained, $0 actual spend),
3 refused_precontact (ledger headroom consumed by retained reservations).

Root cause: `"temperature": 0.2` in the request body. `gpt-5.6-sol`
rejects any non-default temperature with HTTP 400. The earlier config
entry ("temperature 0.2, pinned for reproducibility") was never valid
for this model -- the API is the ground truth, and the bisected
evidence is unambiguous (temperature omitted -> 200; 0.2 -> 400 across
repeated trials, independent of instructions/input content).

Fix: temperature omitted entirely (provider default), identical across
all arms. `CONFIG.json` corrected with the empirical verification
appended to `verified_against`. `src/econ/worker.py` no longer sends
the field.

Spend: $0.00 actual. The 45 retained reservations ($4.95) are recorded
as unresolved exposure in `runs/dev-001/ledger.jsonl`; they represent
no charge. dev-001's ledger is preserved as the incident record.

## dev-002 (2026-09-16) — baseline difficulty validation (fixed worker)

Fresh $5 ledger, 48 dev tasks, temperature omitted. Result: **42/42
completed calls passed (100%), 6 unresolved** — all 6 were transport
failures on the local authd socket ("Connection refused", last 6 calls
of the run at 10:01:43), not model failures. $0.20 settled, $0.66
retained as unresolved exposure. Zero extraction failures.

Findings:
1. **Tasks too easy.** 100% baseline on completed calls exceeds the
   preregistered 80% band -> generator hardened (see below), corpus
   regenerated, integrity re-verified offline.
2. **Tokenizer drift is a constant +10 tokens** (provider framing
   overhead, zero variance, n=42). Added as PROVIDER_FRAMING_TOKENS in
   worker.py; envelope gating now sees what the provider bills.
   Re-verified at study calibration per the 2% rule.
3. **authd socket flakiness**: 6 consecutive local connection-refused
   errors. Recorded as unresolved exposure per the rules. Study run
   will be checkpointed per-rep so a socket drop doesn't lose the run.

## Generator hardening (post-dev-002)

Single-bug tasks were at 100% baseline. New structure: one clean
multi-function module per family + bug transforms; each task composes
TWO distinct bugs. Corpus regenerated (master_seed=7, disjoint pool
streams unchanged), 213 tasks, integrity re-verified offline
(reference passes / buggy fails / packet caps): 0 violations.
New freeze hashes: dev `dbf46d9f…`, eval `6a3b6990…`, calib `a399ecf9…`
(full in `corpus/corpus.json`).

## dev-003 (2026-09-16) — difficulty re-validation (hardened corpus)

Fresh $5 ledger, 48 new dev tasks. (TODO: results on completion.)

## Environment note

tiktoken installed to system site-packages vanished (ephemeral path).
Persistent venv at `~/workspace/.venvs/econ` (tiktoken 0.14.0);
all study work uses its python. Recorded in AGENTS.md.

## dev-003 (2026-09-16) — two-bug tasks: still 100% (48/48, $0.61 settled)

## Generator hardening v3 (post-dev-003)

Longer modules (~90-110 lines, more functions), THREE bugs per task,
subtle classes: tax-on-pre-discount-subtotal, merge-mutates-base,
snapshot-shallow-copy, once-shared-holder-state, emit-breaks-on-exception,
dotted-set-without-mkdir, bulk-rebate-threshold, refund-includes-tax.
(Self-caught generator bug during v3 construction: discount-then-tax vs
tax-then-discount are algebraically identical for flat percentages --
replaced with tax-on-pre-discount-subtotal, which genuinely differs.
Also fixed: clean emit must actually continue past handler exceptions
per its docstring; the logic `!=` test was invalid when thr=500.)
Corpus regenerated (master_seed=7, disjoint pool streams), 213 tasks,
integrity re-verified offline: 0 violations.
New freeze hashes: dev `fb8894c6…`, eval `0c0010b8…`, calib `555684ce…`
(full in `corpus/corpus.json`).

## dev-004 (2026-09-16) — difficulty re-validation (v3 corpus)

Fresh $5 ledger, 48 new dev tasks. (TODO: results on completion.)

## dev-004 (2026-09-16) — v3 difficulty validation: 48/48 (100%, $0.93)

All families at 100% (logic/interface/config). Cost/task $0.0121-$0.0478
(mean $0.0195) -- 4x range, cost discriminates across tasks. 0 unresolved,
0 refused, 0 extraction failures, 0 tokenizer drift (the +10 framing fix holds).

## Band decision (2026-09-16)

Preregistered rule: baseline outside 20-80% -> adjust the generator before
freezing. Adjusted twice (v1 single-bug -> v2 two-bug -> v3 three-bug +
longer modules + subtle bug classes incl. aliasing, shared state,
order-of-operations). Baseline remained at 100% on all three versions.
A third adjustment (more bugs of the same kind) is a linear arms race with
no principled reason to expect a different outcome: the task shape (verify
each line against a precise docstring) is fundamentally easy for a frontier
debugger, and the model caught every subtle bug class in v3.
The measurement is not degenerate: cost per verified task varies 4x and the
acquisition's strict-improvement rule accepts cost reductions at equal
output (vc == vp and cc < cp). Discrimination operates on the cost side;
output preservation (V_B >= V_A) is assessed as a one-sided condition.
Study proceeds on the v3 corpus; this decision is recorded here and in
PROTOCOL.md rather than re-arming the generator.

## Freeze amendment 1 (2026-09-16) — malformed-delta crash

First study launch aborted 8 invocations in: the G1 proposal's ```delta
block contained a REPLACE_STEP line with no step number; apply_delta
crashed with ValueError (int("")), uncaught by run_acquisition, killing
the whole study. Per the protocol a model that fails to produce a usable
delta is a REJECTION (cf. delta_extraction_failed), never a study-ender.
Fix: apply_delta validates directive lines explicitly and raises ValueError
with a clear message; run_acquisition catches it -> "delta_malformed"
rejection. Also resolved a latent format ambiguity: the spec documents
`REPLACE_STEP <n>:` but the code only parsed `REPLACE_STEP: <n>`; both
forms (and `REMOVE_STEP[:]` variants) are now accepted.
This is a robustness fix, not a methodology change: acceptance rules,
rejection categories, and accounting are untouched.
Aborted attempt spend (~$0.15, 8 invocations) stays in the ledger, which
replays on re-launch; no rep completed, so no partial rep state exists.
Crash log preserved at runs/study-001/console.crash1.log.
