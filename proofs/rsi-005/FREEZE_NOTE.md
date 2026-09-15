# RSI-005 result freeze

Experiment: RSI-005 lineage-aware inheritance.
Scientific question: when gen1's receiver evidence is reopened, does
questioned standing propagate to gen2 which inherited from it.

## First and only outcome

Exactly one authorized top-level primary invocation was launched from the
verified main commit `997931115587cafa355802d219e46ab1c69186dc`:

```
python experiments/rsi-005-lineage-aware-inheritance/run_rsi_005_scientific.py \
  --execute-primary \
  --output experiments/rsi-005-lineage-aware-inheritance/result.json
```

- exit code: 0 (see `primary-exit-code.txt`)
- formal verdict: `PASS_RSI_005_LINEAGE_AWARE_INHERITANCE`
- cause_code: `NONE`
- result.json SHA-256:
  `76fa61f785158b729eb59d1524d98abbee94f5857805ac0c008e475c3ad14855`

The classification is reported exactly as written. It is neither upgraded
nor downgraded.

## What the result shows

- Pre-REOPEN established set: `rsi-005-gen1-earned-policy`,
  `rsi-005-gen2-inherited-policy`, `rsi-005-gen3-inherited-policy`,
  `rsi-005-rootU-unrelated-policy` — all four inherited.
- Post-REOPEN standings: gen1 = questioned, gen2 = questioned,
  gen3 = questioned, rootU = inherited. Questioned standing propagated down
  the lineage-aware chain; the unrelated rootU line was unaffected.
- Lineage witness paths: gen2 -> gen1; gen3 -> gen2 -> gen1.
- gen4 probe: DENIED, not executed, status questioned,
  witness `airlock-lineage-questioned`.
- Historical canonical receipt identity: unchanged (`unchanged = true`).
- Raw historical receipt byte identity: byte-identical (`true`).
- Installed refs: unchanged across at_install / checkpoint / final for all
  four generations.
- Installed policy: checkpoint hash equals final hash for all four
  generations.
- Lineage record-set: checkpoint and reprojection both
  `a0a375f648d4bb9d00d0641982349df9aebdfba4ec6eb47f27e1176090c5fbd6`
  (unchanged).
- 12 phase PIDs all distinct (`phase_pids_distinct = true`).
- Reprojection deterministic (`reprojection_deterministic = true`).

## Execution provenance

- execution_head_sha: `997931115587cafa355802d219e46ab1c69186dc`
- preregistration SHA-256:
  `256b41d726f5f8597b4e23ed2169f10974a034d9433f5fd0d5ba861ead8f2ac5`
- scientific runner file SHA-256:
  `afd9bd51ffc60459c3a38f01990429d24e329235ae8fe4a2e1efa849dca19789`
- scientific runner normalized SHA-256:
  `b4aa5e5d3f425761ac5ec5de7512e3ff5b3d0859adc500a9c7d986625425acb5`
- qualified harness SHA-256:
  `1fa894bd623eb4aacc39645ad546c0d31889dec391b1a65d65a27842937665e3`
- Verified Memory commit: `36e3d0e0dab6a121abc1c14accbaa7310b5c2186`
- Verified Memory evidence.py SHA-256:
  `ba02bc78c999120b31ea68fcb4f4fd2d12967c705e380204d0ee093b1d874ec9`

## Anti-rescue

The one-run authorization was consumed by launching the authorized
top-level command. Scientific anti-rescue contact began when execution
first entered the qualified `nightshift_entry()` choke point and the
RSI-005 primary-contact marker was written immediately before
`run_nightshift` (marker evidence in `primary-contact-marker.txt`).

Under RSI-005 there is now: no rerun, no repair, no tuning, no threshold
change, no manual phase invocation, no reinterpretation of this outcome.

RSI-004 stays permanently closed (harness crash, no verdict) and RSI-003
stays permanently closed (`FAIL_RSI_003_QUESTIONED_ANCESTRY_NOT_PROPAGATED`);
this PASS under RSI-005 does not re-litigate either.

## Claim boundary (from the frozen result)

Four installed generations plus one unexecuted admission probe. Single-
required-parent lineage only. Does not earn the final RSI claim: a later
test still needs an inherited method mutation to beat its unchanged parent
on fresh verified results per dollar. Deterministic fake Hermes through the
real Nightshift path; no paid live-Hermes claim. Does not claim hostile-
process isolation. PASS under this ID validates the repaired projector's
lineage semantics.
