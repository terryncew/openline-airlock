# AIRLOCK-SEARCH-001

Can a coding agent find better work to do when you give it a better way to explore a repo?

This compares two versions of the same Hermes worker with the same model, repo, candidate count, checks, and hidden evaluation.

**Free-form** gets: “Improve this repo.”

**Repo Scout** has to understand the repo first, list several possible improvements, check whether each one is actually useful, look at speed/reliability/dev experience/security/maintainability/user impact, inspect one decisive fact when the diagnosis is fuzzy, rank the options, and only then build the best small reversible fix.

The worker cannot see or change the hidden evaluation.

The previous SEARCH-001 run does not count. The setup accidentally deleted `office_ops.py`, the file the public checks exercise, so Hermes never got a valid repo to search. This version keeps the target and fails immediately if the starting checks are broken.

A win means Repo Scout finds an independently accepted improvement and Free-form does not.

If that happens, the next test is the same Repo Scout workflow on fresh hidden opportunities. No multi-step self-improvement yet.
