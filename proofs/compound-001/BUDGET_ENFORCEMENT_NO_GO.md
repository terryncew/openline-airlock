# COMPOUND-001 — Budget-Enforcement NO-GO (freeze record)

- experiment: `COMPOUND-001`
- terminal stage: precontact budget-enforcement feasibility
- frozen outcome: `NO_GO_BUDGET_ENFORCEMENT`
- determination: preregistered precontact budget-enforcement gate; independently reviewed
- date: 2026-09-16

## Standing

- COMPOUND-001 is a new study. It is not RSI-006-Q7, does not reopen
  RSI-006, and does not reinterpret the RSI-006-Q6 NO-GO.
- RSI-006 standing is unchanged: `Q6_MECHANISM_HOLDS`,
  `NO_GO_Q6_QUALIFICATION_BINDING_COMPLEXITY`, productivity experiment
  never authorized/run, no productivity advantage/disadvantage
  established, no Q7.
- COMPOUND-001 stops BEFORE calibration and BEFORE scientific contact.

## Refs

- clean accepted main at freeze time:
  `d3b29da9a83c8ee65ee095fae1b052460e08ece3`
  (merge commit for PR #169; re-read before freezing; main had not moved)
- rejected construction branch: `experiment/compound-001`
- rejected construction head:
  `131a4440a7c29ea406a99664fdf68bb0961f303c`
  (one construction commit, "COMPOUND-001: frozen-contract
  implementation (precontact only)")
- the rejected construction remains unmerged; the branch is preserved
  as evidence and must not be deleted, rewritten, squashed, or merged.
- construction PR: #170 (`experiment/compound-001` → `main`), state
  OPEN at freeze time, preserved unmerged as evidence. Its 450-line
  runtime harness must not be merged into main: this branch is evidence
  of a precontact stop, not software that belongs on main.
- pinned Hermes: `NousResearch/hermes-agent`
  commit `29112bef099274229cadff79cdff7bf7b99c4b77`
  (the same pin used by the repository's search workflows, e.g.
  `.github/workflows/airlock-search-004.yml`, `HERMES_COMMIT`)

## Pinned-source evidence

Inspected from the pinned commit `29112bef` tarball
(`NousResearch/hermes-agent`):

1. `run_agent.py:456` — `AIAgent.__init__` signature:
   `max_iterations: int = sys.maxsize,  # Default: unlimited tool-calling iterations (shared with subagents)`
2. `hermes_cli/oneshot.py:492` — the one-shot path constructs
   `AIAgent(...)` directly and passes no `max_iterations` and no
   `max_tokens`; the call inherits the default above, which is effectively
   unlimited for this experiment's budget.
3. `hermes_cli/_parser.py` — the top-level CLI surface for one-shot is
   `-z`/`--oneshot PROMPT`, `--usage-file PATH` (post-hoc), plus
   toolsets/resume/in-dir/worktree flags. There is no
   `--max-iterations` / `--max-tokens` control anywhere on the
   one-shot path.
4. `--usage-file` help text: "after the run, write a JSON usage report
   (estimated cost, token counts, model, api_calls) to PATH ... so
   pipelines can always account for spend." It is post-hoc metering; it
   does not create a pre-invocation spending bound.

The repository's COMPOUND-001 paid provider invocation was the existing
Airlock worker path (see `.airlock/search-004/worker.py` and
`docs/AIRLOCK_HERMES_WORKER_001.md`):

`hermes -z <prompt> --usage-file <path>`

## Why no budget-admissible R_i can be established at that interface

The frozen contract requires, before EVERY paid invocation, a
conservative maximum possible charge `R_i` derived from an ENFORCED
maximum billable resource envelope (frozen price table, maximum output,
maximum context/input exposure, permitted retries, all billable token
classes). Observed average price is not a reservation.

At the pinned interface:

- the one-shot CLI exposes no max output tokens and no bounded
  retry/API-call count;
- the agent's iteration bound defaults to `sys.maxsize` and the
  one-shot path does not override it;
- a wall-clock timeout alone does not bound billable tokens: the
  provider can bill the maximum token volume before the timeout fires;
- `--usage-file` reports spend after the fact and cannot reserve or
  cap anything before contact.

The existing pinned `hermes -z` interface exposes no configurable
per-invocation iteration/token/resource ceiling from which COMPOUND-001
can establish and enforce a conservative budget-admissible `R_i`.
`AIAgent` defaults `max_iterations` to `sys.maxsize`; while that value
is mathematically finite, its worst-case exposure is not compatible with
the experiment's hard spending limits ($5 calibration / $50
whole-study), and the one-shot CLI provides no permitted control for
lowering that exposure. `--usage-file` is post-hoc accounting rather
than a pre-invocation cap. Therefore the first paid invocation cannot
satisfy the preregistered reservation rule without introducing a new
provider/resource-governor boundary, which the contract forbids. The
correct precontact result is `NO_GO_BUDGET_ENFORCEMENT`.

## Why no rescue path was introduced

Making this safe would require changing or replacing the
paid-provider execution boundary (a resource governor / provider
gateway that enforces a finite billable envelope per invocation). The
frozen COMPOUND-001 contract expressly forbids that rescue:

- complexity gate: no new runtime dependency, no DB, no daemon, no
  distributed reservation service, no new subsystem;
- "Do not build a new provider gateway to save the study."

No such gateway was built. No relaxation of `R_i`, no budget increase,
no horizon expansion, no contract reinterpretation occurred.

Note for contrast only (not used): the RIL-001D live driver
(`experiments/ril-001d/substrate/protected/live_agent_driver.py`)
constructs `AIAgent` directly with receiver-set `max_iterations` and
`max_tokens`. That is exactly the kind of custom provider boundary the
COMPOUND-001 contract forbids as a rescue subsystem.

## Complexity gate status

From the attempted construction (PR #170): 1 COMPOUND runtime module,
450 effective nonblank/noncomment LOC (limit 500), zero changes to
`src/airlock/**`, no new dependency/DB/daemon. Complexity gate: PASS.

The complexity gate did NOT cause this stop. The stop is the
budget-enforcement feasibility gate, which fires earlier in the
precontact sequence.

## Construction defect recorded separately (not the stop reason)

Review of the unmerged construction found one contract mismatch in
PR #170: `.airlock/compound-001/task-schedule.json` places a
`calibration` task set inside each of the three repetitions
(`C001-R1-CAL-*`, `C001-R2-CAL-*`, `C001-R3-CAL-*`). The approved
contract has ONE pre-experiment calibration set total (namespace CAL,
disposable worker state, never reused).

This defect is in the unmerged construction only. It is recorded here
as a defect and is NOT the reason for the scientific stop: no
calibration will occur because the earlier budget-enforcement gate
already terminates the experiment. Do not repair the construction now.

## CI evidence from the construction (PR #170)

Run `35118589318` (all pass):

- test (3.11): pass
- test (3.12): pass
- test (3.13): pass
- wheel: pass
- Actions runtime integration: pass

Run `35118589339`: far-003: pass.

Run `35118589367`:

- Compile GitHub Agentic Workflow: pass
- Airlock arm: FAIL — root-caused, unrelated to COMPOUND-001.

The Airlock-arm failure: `proofs/airlock-github-aw-001/run.py` does
`git clone --shared` of a partial clone of the third-party repo
`mrphrazer/binary-ninja-headless-mcp`, and GitHub's promisor
persistently failed to serve object
`65b13985762d19abbd46500340d1bb9404bb0957`
("could not fetch ... from promisor remote", "possible repository
corruption on the remote side"). Failed identically across reruns; the
same workflow passed on main at this exact base SHA. The construction
branch touches zero files in `proofs/`, `src/`, or workflows. This
freeze does not touch that machinery to obtain green.

## Negative confirmations

Explicitly: no live calibration; no calibration task executed; no paid
COMPOUND model invocation; no discovery contact; no proposal contact;
no promotion contact; no measurement contact; no scientific contact; no
A/B/C repetition began; no compounding result; no amortization result;
no rapid-payback result; no longer-horizon economic result; no rescue
provider gateway; no relaxation of `R_i`; no increase in budget; no
expansion of task horizon; no reinterpretation of the contract;
RSI-006 standing unchanged.

## Interpretation boundary

COMPOUND-001 did NOT find that process improvement fails to pay back.

COMPOUND-001 did NOT test the economics.

It found that the preregistered experiment could not safely authorize
its first paid contact because the existing pinned provider path could
not prove and enforce the required maximum pre-invocation financial
exposure.

That is an experimental infrastructure NO-GO before scientific
contact — not a verdict on amortization, compounding, or the
research method.
