# RSI-006-Q2 — Substrate Qualification Spec

**Status: FROZEN.** This file is the authority for RSI-006-Q2. Thresholds and
budgets below were set before any RSI-006-Q2 mutant was generated or observed.
If the substrate fails qualification, it is not tuned under this ID.

## Lineage

RSI-006-Q (frozen receipt: `NOT_QUALIFIED_RSI_006_SUBSTRATE`, proof-only PR
#156) failed on the frozen thresholds. Review found three defects in the
qualification design, none of them in the substrate:

1. **Arithmetic impossibility.** Q-STAB requires, per repo, at least 3
   operators with ≥10 observations in each discovery half (minimum 30
   mutants per half). more-itertools was budgeted 20 per half, so
   `QUALIFIED_RSI_006_SUBSTRATE` was unreachable by construction.
2. **No reachability check.** Nothing verified before test execution that
   the frozen generator + frozen seeds + budget could actually produce the
   required operator counts.
3. **No per-mutant records.** The runner kept only aggregates, so the exact
   cachetools determinism mismatch and the pluggy collection-error sites
   cannot be identified from the receipt.

RSI-006-Q2 is the minimal repair. **Everything else is unchanged**: the
same four pinned repositories, the same operator set, the same discovery
seeds, the same thresholds, the same fresh-nonce semantics, the same
scoring semantics, the same causal order (with the guard inserted before
any test execution). No researcher arms, no hypotheses, no LLM imports,
zero API spend — asserted by contract test, as in Q1.

## What RSI-006-Q2 changes (and only this)

1. **Budgets.** Per-half discovery budgets raised to the exact minima at
   which the frozen "3 operators × 10 observations" requirement is
   deterministically reachable under the frozen generator + frozen seeds:

   | repo | discovery A | discovery B | determinism | confirmation |
   |---|---|---|---|---|
   | more-itertools | 72 | 72 | 10 | 72 |
   | cachetools | 102 | 102 | 10 | 102 |
   | boltons | 70 | 70 | 10 | 70 |
   | pluggy | 51 | 51 | 10 | 51 |

   These minima were found by static site enumeration only (frozen
   generator, frozen seeds, candidate budgets) — no kill outcomes, no
   stability results, no test execution were used. The two discovery
   halves of each repo share one budget.

   Frozen budget tuples (discovery_A, discovery_B, determinism,
   confirmation): more-itertools (72, 72, 10, 72), cachetools
   (102, 102, 10, 102), boltons (70, 70, 10, 70), pluggy (51, 51, 10, 51).

2. **Feasibility guard.** After SHA verification and before any test
   execution, for each repo and each discovery half, the runner enumerates
   mutation sites (static repository structure), shuffles with the frozen
   seed, takes the first `budget` sites, and counts selected mutants per
   operator. The guard passes iff both halves yield at least 3 operators
   with ≥10 selected mutants — exactly the population Q-STAB's
   "qualifying operators" count is computed from. If the guard fails for
   any repo, the run stops before any test execution with verdict
   `INCONCLUSIVE_RSI_006_Q2_PRECONDITION_FAILURE`. The guard uses no
   outcome data and cannot adapt the design to results.

3. **Record persistence.** The runner persists canonical per-mutant
   records as JSONL (one canonical-JSON object per line, sorted by
   mutant_id; canonical form is `json.dumps(sort_keys=True,
   separators=(",", ":"))`, the same bytes the discovery seal covers):
   - `{repo}-discovery.jsonl` — every discovery observation
     (mutant_id, operator, site_key, outcome signature, kill flag,
     collection_error flag, duration)
   - `{repo}-confirmation.jsonl` — every confirmation observation
   - `{repo}-det-reruns.jsonl` — determinism rerun pairs
     (mutant_id, original record, rerun record, agree flag)
   
   The report binds each record file by SHA-256 (`record_digests`).
   Acceptance logic is unchanged: records are observability, not a new
   criterion.

## Known generator issue (out of scope for Q2)

`perturb.py` is byte-identical to the RSI-006-Q frozen generator.
`_is_bool_candidate` uses `node.value in (True, False)`, which matches by
`==`: integer literals `0` and `1` are also enumerated as BOOL_FLIP sites
(`0 == False`, `1 == True`). Application computes `not node.value`, so a
BOOL_FLIP site on `0` becomes `True` and on `1` becomes `False` —
int-to-bool conversions, not boolean flips. The operator label `BOOL_FLIP`
therefore covers two different mutation kinds: genuine boolean flips and
int-literal-to-bool conversions. The operator set is unchanged and the
generator is deterministic, so the guard (computed with the same generator)
remains self-consistent. Fixing the predicate would change the mutant
population and is explicitly out of scope for Q2; it is recorded here so
the science layer can decide.

## Causal order

1. This spec and its code are frozen; their hashes are recorded in the report.
2. Verify repository SHAs against the pinned pool. Run the feasibility
   guard. **No test execution occurs before the guard passes.**
3. Verify baselines: every repo's unmutated suite must be fully green and
   deterministic across two runs.
4. Generate the discovery mutant set from the frozen perturbation generator
   with the frozen discovery seeds. Observe. Persist canonical records.
   Seal the discovery archive (SHA-256 of the canonical observation bytes).
5. **Only after the seal is written**, the receiver creates a fresh 256-bit
   nonce from OS entropy and generates the confirmation mutant set from the
   same site pool (discovery sites are not excluded; only the seed is
   fresh). Observe. Persist canonical records.
6. Determinism rerun on the frozen subset. Persist rerun pairs. Check
   byte-identity of observation records.
7. Compute the qualification metrics. Emit the report. No researcher ever
   sees the archive.

## Repository pool (untouched, read-only) — unchanged from Q1

| repo | pinned commit | package dir | tests dir | suite time |
|---|---|---|---|---|
| more-itertools | `b2f3aff7633057d234ec9186c18a53f4df306d08` | `more_itertools/` | `tests/` | ~25 s |
| cachetools | `4500e3d04288738d25acbb4973eb3c3e1bf41db9` | `src/cachetools/` | `tests/` | ~4.5 s |
| boltons | `961dcff3f42e73b245aef65e377fe82763b257bb` | `boltons/` | `tests/` | ~2 s |
| pluggy | `0a4974175aa2d873f401345b151297af2e74c851` | `src/pluggy/` | `testing/` | ~1.2 s |

- Repos are cloned at the pinned commit and treated read-only. A SHA-256 tree
  hash (all files excluding `.git/`) is recorded before and after the run;
  Q-INTACT requires byte identity.
- Observation runs execute with `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH`
  pointing at the package dir, cwd in a temp dir, `-p no:cacheprovider`.
  Nothing is installed into the environment and nothing is written into the
  checkout. Verified by the tree hash, not by assertion.

## Perturbation generator (frozen, generic, receiver-owned) — unchanged from Q1

`perturb.py` implements a seeded AST mutation generator. The operator set is
fixed and defined without reference to any repository's semantics:

| operator | transformation |
|---|---|
| `CMP_SWAP` | `==`→`!=`, `!=`→`==`, `<`→`<=`, `<=`→`<`, `>`→`>=`, `>=`→`>` |
| `ARITH_SWAP` | `+`→`-`, `-`→`+`, `*`→`/`, `/`→`*` |
| `BOOL_FLIP` | `True`→`False`, `False`→`True` |
| `NUM_DELTA` | integer literal `n` (abs(n) ≤ 1000) → `n+1` |
| `LOGIC_SWAP` | `and`→`or`, `or`→`and` |
| `NOT_DROP` | `not x` → `x` |

- A mutant is exactly one operator application at one site.
- Sites are enumerated deterministically: all eligible AST sites in the
  package dir, sorted by (file path, line, column). Test directories are
  never mutated: the regularity must come from library behavior, not from
  breaking the tests themselves.
- Given a seed string, `random.Random(seed)` shuffles the site list and the
  first N sites become the mutant set. Same seed → byte-identical mutant
  list (asserted by contract test).
- Frozen seeds: discovery halves `RSI-006-Q-discovery-A` and
  `RSI-006-Q-discovery-B` (unchanged from Q1). The confirmation nonce is
  generated fresh in step 5 of the causal order and recorded in the report.

## Observation — unchanged from Q1

Each mutant is applied to a pristine overlay copy of the package; the repo
checkout is never modified. The suite runs against the overlay via
`PYTHONPATH`. Outcomes are compared per-test to the green baseline. The
scoring contract is exact: a mutant is *killed* iff its observed behavior
differs from baseline — at least one test outcome differs (a test missing
from, or extra to, the baseline set counts as a difference), or the suite
run timed out (120 s limit; green baselines complete in ≤ ~25 s, so a
timeout is a behavioral signal, and the timeout flag is preserved in the
record).

- Outcome signature: the sorted list of `(test_id, outcome)` pairs.
- Collection error: missing or unparseable JUnit XML marks the observation
  as a collection error. A collection error is NOT a kill: the suite could
  not be measured, so there is no behavioral observation; it counts only
  against the collection-error sanity bound (< 0.10). Test stdout/stderr
  are suppressed by the harness; the cause of a collection error is
  therefore unobserved and must be reported as such, never diagnosed.
- Determinism rerun: the first `det_n` discovery-half-A mutants are
  re-observed; Q-DET requires byte-identical canonical observation
  records (agreement exactly 1.0).

## Qualification criteria (frozen) — unchanged from Q1

- **Q-DET**: determinism rerun agreement exactly 1.0 (1.0 exact; no
  tolerance).
- **Q-SIG**: each repo's discovery kill rate in **[0.05, 0.95]**.
- **Q-STAB**: per repo, at least **3** operators with ≥**10** mutants in
  each discovery half; per-operator half-to-half kill-rate difference
  ≤ **±0.25**; Spearman rank correlation of per-operator kill rates
  ≥ **0.7**.
- **Q-FRESH**: per-operator confirmation kill-rate drift ≤ **±0.30** vs
  the discovery mean; overall kill-rate drift ≤ **±0.15**. Confirmation
  measures resampling stability under a fresh seed, not transfer to unseen
  sites. The causal guarantee is one-directional: the confirmation seed is
  created after the discovery seal, so confirmation cannot have shaped
  discovery. Unseen-site confirmation — withheld cases, untouched
  repositories — belongs to the RSI-006 science layer, not to substrate
  qualification.
- Collection-error rate **< 0.10** (sanity bound).
- **Q-INTACT**: exact pre/post repository tree-hash identity.
- **Q-COST**: observations per minute, report-only.

## Formal verdicts

- `QUALIFIED_RSI_006_Q2_SUBSTRATE` — all criteria met on every repo.
- `NOT_QUALIFIED_RSI_006_Q2_SUBSTRATE` — at least one criterion failed.
- `INCONCLUSIVE_RSI_006_Q2_PRECONDITION_FAILURE` — a precondition failed
  (SHA mismatch, baseline not green/deterministic, feasibility guard
  failure, or missing observations). No scientific reading is licensed.
