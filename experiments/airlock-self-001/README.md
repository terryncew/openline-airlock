# AIRLOCK-SELF-001

AIRLOCK-SELF-001 is the first positive-control test after FAR-003.

It asks whether the same frozen admission rule is reachable by a maintainer-directed worker and by an autonomous worker given only:

> Improve this repository. Find the highest-value small, reversible change you can justify.

The repository contains one prospectively measurable local opportunity in `office_ops.py`: `first_over_budget` preserves the correct answer but keeps consuming the iterable after the answer is already known. The autonomous arm is not told where that opportunity is. The maintainer-directed arm is.

Both arms start from the exact same commit, receive the same number of worker attempts, use the same provider, and are judged by the same frozen evaluator. A candidate can win only if it produces a large scoped efficiency gain, preserves every protected behavior, stays within the reversible change budget, and wins uniquely.

Interpretation is preregistered:

- directed YES + autonomous YES => `AUTONOMOUS_IMPROVEMENT_EARNED`
- directed YES + autonomous NO => `SEARCH_GAP`
- directed NO => `POSITIVE_CONTROL_NOT_EARNED`; autonomous zero is uninterpretable

This is a positive-control search experiment, not proof that Airlock can discover arbitrary high-value improvements in an organic production codebase.
