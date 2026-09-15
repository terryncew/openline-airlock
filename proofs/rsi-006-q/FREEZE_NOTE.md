# RSI-006-Q result freeze

Experiment: RSI-006-Q substrate qualification (non-scientific stage).
Question: can the external discovery substrate — generic, receiver-owned
perturbations of untouched real repositories — yield stable, reproducible,
signal-bearing observations, without looking at arm performance?

## Verdict

`NOT_QUALIFIED_RSI_006_SUBSTRATE`

The single full `--qualify` run completed all five causal-order steps
(SHA verification, green deterministic baselines, discovery from frozen
seeds, archive seal, fresh-nonce confirmation, determinism rerun) and the
substrate failed qualification on the frozen thresholds. 600 observations
in 2416 s (14.9 obs/min), zero API spend, no researcher arms involved.
(Capture limits — uncaptured stdout/stderr/exit status — are stated in
`CAPTURE_LIMITS.md`.)

## Failed criteria (exact, from the report)

- more-itertools: Q-SIG kill rate **0.000** outside [0.05, 0.95];
  Q-STAB **0** qualifying operators (< 3).
- cachetools: Q-DET rerun agreement **0.95** < 1.0 exact;
  Q-STAB **2** qualifying operators (< 3).
- boltons: Q-SIG kill rate **0.008** outside [0.05, 0.95];
  Q-STAB **2** qualifying operators (< 3).
- pluggy: Q-STAB spearman **0.500** < 0.7;
  collection-error rate **0.300** >= 0.10.

All four repos: baselines green and deterministic (754 / 333 / 519 / 169
tests), SHAs verified, tree hashes identical before and after (Q-INTACT
held everywhere).

## The pre-identified design bug

Before the run finished, review found that Q-STAB is arithmetically
impossible for more-itertools under the frozen budget: 20 mutants per
discovery half cannot supply 3 operators × 10 observations per half
(minimum 30). Per the standing instruction, the spec was not repaired
under this ID; the run completed untouched and the failure is frozen
exactly as observed. This bug is a property of the qualification design,
not of the substrate: it says nothing about more-itertools' behavior.

## What the run additionally revealed (observations, not diagnoses)

- The near-zero kill rates on more-itertools (0/40) and boltons (1/120)
  were verified not to be a shadowing failure: overlay imports resolve
  correctly (spot-checked `boltons.__file__` under the overlay), and the
  same harness yields kill rates of 0.88 (cachetools) and 0.85 (pluggy).
  Mutants land; the two suites genuinely do not change behavior under
  the sampled generic mutations. Why is a question for the substrate,
  not for this freeze.
- cachetools: one of 20 determinism-rerun pairs disagreed (agreement
  0.95 < 1.0 exact). The runner did not persist per-mutant observation
  records, so the specific mutant and the nature of the disagreement
  cannot be identified from the receipt. The cause is unobserved; this
  is recorded as a measured criterion failure, not as a finding of
  nondeterminism in the repository.
- pluggy: collection-error rate 0.30 >= 0.10. The harness suppresses
  test stdout/stderr and marks a collection error from missing or
  unparseable JUnit output, so the underlying cause is unobserved; this
  is recorded as a measured sanity-bound failure, not as a finding
  about import-time behavior.

No diagnosis, tuning, or re-observation was performed under this ID
after the report was produced.

## Provenance

- Stage code: branch `experiment/rsi-006-substrate-qualification`,
  commit `538b055f94bdaaa7a5406c582fa827875b2e76a7` (spec frozen before
  the first observation, per the causal order).
- Code hashes as executed are recorded in the report:
  spec / perturb.py / observe.py / run_rsi_006_q.py.
- Discovery seeds: `RSI-006-Q-discovery-A` / `RSI-006-Q-discovery-B`
  (frozen). Confirmation nonce: fresh OS entropy, created only after the
  four discovery seals were written (recorded in the report).

## Standing instruction for the successor

RSI-006-Q2 makes the smallest repair only: per-half budgets large enough
that the frozen "3 operators × 10 observations" requirement is
arithmetically possible on every repo, plus a deterministic
pre-observation feasibility guard (from mutation-site enumeration, not
from kill outcomes) that stops the run before any test execution if
Q-STAB is unreachable. Same repos, operator set, seeds, thresholds,
fresh-nonce semantics, and observation harness. No tuning under this ID.
