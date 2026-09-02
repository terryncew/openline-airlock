# AIRLOCK-SEARCH-001B — Measure First

Repo Scout got better at producing patches, but it still picked work that looked useful instead of work it could prove mattered.

This variant changes only the way the coding agent chooses a problem.

Before it can keep a patch, Hermes has to:

1. Find at least three possible improvements.
2. Attach a local numeric probe to the serious ones.
3. Pick one small target.
4. Measure the untouched repo.
5. Make the patch.
6. Run the exact same probe again.
7. Throw the patch away unless the measurement actually improves.

Airlock independently reruns that probe on both versions. Patches over two files or 120 changed lines are discarded before hidden evaluation.

The hidden evaluator is unchanged and unavailable to Hermes.

The earlier Free-form and Repo Scout results stay frozen. They are historical controls; this experiment does not rerun them.

If Measure First earns a real winner, the next test is the same search workflow on fresh hidden opportunities. Only then do we test repeated self-improvement.
