# BOUNDED-CALL-001 — FIRST-FAILURE FREEZE

**BOUNDED-CALL-001 DID NOT PASS QUALIFICATION.**

The qualification stopped at the first frozen assertion failure.
No qualification verdict was earned. No rerun or rescue occurred.
Q6 was never executed. No production/live-provider standing was earned.
No PAYBACK-004 or COMPOUND continuation is authorized by this result.

## Terminal standing

- STOPPED_AT_FIRST_FAILURE
- NO QUALIFICATION VERDICT EARNED
- NOT A PASS

No stronger label is applied; the frozen preregistration defines no
terminal failure/verdict label for this state.

## Candidate

- HEAD: `a7aaf61b94285a3f99baf2d262bd0806758a938f`
- Branch: `research/bounded-call-001-repair`
- Pinned base: `13791a9ecb5370377ee50ec54530d6ffc0a9dce8`
- Hermes pin: `29112bef099274229cadff79cdff7bf7b99c4b77`

## Scientific contact

- Timestamp: 2026-09-16T22:28:55.758488-07:00
- Invocation:
  `env -u HERMES_ENABLE_PROJECT_PLUGINS -u HERMES_KANBAN_TASK HERMES_HOME=/tmp/bc001-qual-home-ZHt996 python3 /tmp/bc001_run_qual.py`
- One fresh Python process; fresh empty qualification-only HERMES_HOME;
  `HERMES_ENABLE_PROJECT_PLUGINS` and `HERMES_KANBAN_TASK` removed;
  no provider credentials supplied; fake-provider/offline paths only.

## First failure

Case 11 of 12 registered: `case_q5_accounting_and_over_envelope`
(`experiments/bounded-call-001/qualification/cases.py`, line 509).

Preserved traceback (verbatim):

```
File "/tmp/bc001_run_qual.py", line 34, in main
  fn()
File "/home/hatch/workspace/openline-airlock/experiments/bounded-call-001/qualification/cases.py", line 509, in case_q5_accounting_and_over_envelope
  assert Decimal(payload["observed_charge"]) == Decimal("30000")
AssertionError
```

Exit code: 1. Runner terminal marker: STOPPED_AT_FIRST_FAILURE.

## Cause

A frozen qualification-fixture inconsistency. The frozen implementation
prices long-context output at 1.5x only when whole-request prompt
exposure (input + cache_read + cache_write) exceeds 272000 tokens
(amendment §12: "Long-context pricing is based on whole-request prompt
exposure according to the frozen rule").

Q5's blowout fixture:

- input_tokens = 0, cache_read_tokens = 0, cache_write_tokens = 0,
  output_tokens = 1000000000
- prompt exposure = 0 → no long-context multiplier

The frozen implementation correctly computed:

- observed_charge = 20000.00

The fixture nevertheless asserted `observed_charge == 30000`, which
requires the 1.5x long-context output multiplier despite prompt exposure
being 0, contradicting the frozen pricing rule.

The hard-coded 30000 expectation already existed in candidate
`0388ffd76c6184a67c7fb98f67108ba0ec4d3cd0`, before the later
tool-surface and runtime-home repair rounds. Provenance only; it does
not excuse or erase the scientific failure.

Nothing was repaired: the expectation was not changed to 20000,
`price_usage` was not altered, the run was not repeated.

## Observed result prefix (ordered)

1. case_q1_gate_and_r_i — PASS
2. case_q1_concurrent_one_shot — PASS
3. case_q1_tool_surface_resolves_empty — PASS
4. case_q1_tool_surface_refusals — PASS
5. case_q1_tool_surface_binding_reverified — PASS
6. case_q1_runtime_home_scoped — PASS
7. case_q1_runtime_home_negative — PASS
8. case_q2_pre_arm_death_proven_not_entered — PASS
9. case_q3_post_arm_death_indeterminate — PASS
10. case_q4_signed_reconciliation — PASS
11. case_q5_accounting_and_over_envelope — FAIL
12. case_q6_no_self_release — NOT EXECUTED

Narrower Q5 observations recorded before the failing assertion
(observations only, not independent verdicts):

- payload outcome == EXECUTED passed;
- envelope_violation == True passed;
- the actual observed charge was preserved rather than clamped to R_i;
- R_i remained separately recorded (160.76256);
- the failure occurred only at the frozen exact-dollar assertion.

## Zero paid contact (frozen)

- no OpenAI request;
- no OpenRouter request;
- no Nous request;
- no image-model request;
- no live Hermes conversation;
- no provider credentials supplied to the qualification process;
- qualification used fake-provider/offline paths only.

## Frozen seals (pre- and post-contact, byte-identical)

- preregistration: `4d55ea067ee37d979798f13a4e0ec8506866db278b6bdd49604a057f23f610a7`
- PRECONTACT-AMENDMENT-001: `d18e214be19c9923fbb5d80609087cdb1fdc7bb22469cdb564e48837658a386d`
- src/airlock/bounded_call.py: `52f77c6be220e2f995bb760338ec199597b2435f378931639c63cf3dc2f2b8a6`
- experiments/bounded-call-001/qualification/cases.py: `aa799fbf93e6cc039dd2000f3105613af3041806f4ab6968267d3c2871ddd9af`
- LOC (frozen AST counter): 300/300
- Hermes pin: `29112bef099274229cadff79cdff7bf7b99c4b77`

The scientific candidate bytes remain unchanged; post-contact hashes
recomputed and matched exactly.

## Preserved evidence

`~/workspace/bounded-call-001/qualification/CONTACT-001/` (unaltered;
see MANIFEST.sha256 for inventory and hashes).
