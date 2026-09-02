# AIRLOCK-SEARCH-001

SEARCH-001 tests search strategy only against pinned SELF-001 substrate `91861c77e4b03ace60df147b0accf94f4351de18`.

Generation and evaluation are separate jobs. The worker repository physically excludes the hidden evaluator, hidden scope registry, SELF-001 preregistration, fixtures, and directed SELF-001 harness before a fresh Git repository is created. Candidate patches cross afterward as inert artifacts.

Four equal-budget strategies are preregistered: baseline free-form, triage-and-rank, hypotheses-first, and planner-select. All use Hermes gpt-5.6-sol with four candidates.

`SEARCH_STRATEGY_GAIN` is earned only when baseline has no unique admissible winner and at least one modified strategy does under the frozen SELF-001 selector.

One run. No rescue after results. No SELF-002 here.

**Improve the searcher, never the judge.**
