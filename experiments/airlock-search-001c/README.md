# AIRLOCK-SEARCH-001C — Outcome Trace

Measure First proved Hermes can find numbers that move. It still picked measurements that did not matter to the repo's hidden definition of useful improvement.

Outcome Trace changes the search rule:

**Start from something developers or users can already see, then trace inward.**

Before any code is allowed, Hermes must find at least three possible improvements anchored to public repo evidence: docs, CLI/API behavior, public checks, benchmarks, changelog, or git history.

For the chosen opportunity it has to show:

1. the public behavior that matters;
2. the path from that public surface to the source file it wants to change;
3. what top-level outcome should improve;
4. a reproducible local command that exercises that outcome;
5. a patch plan of no more than two files.

Planning is a separate read-only Hermes call. If it edits the repo, has no valid public anchor, cannot reproduce the public outcome, or needs more than two files, the implementation call never happens.

Only after the plan passes does a second Hermes call get permission to write code. The same public outcome is measured again after the patch. Only candidates with a reproduced top-level gain reach the unchanged hidden evaluator.

The earlier Free-form, Repo Scout, and Measure First results stay frozen.

The directed SELF-001 control was checked only for discovery-channel type. It was maintainer-targeted rather than discovered through a public channel, so it gives Outcome Trace no hints and no weighting.

If Outcome Trace earns a hidden winner, the next step is fresh-target replication. If it loses, freeze the deficit again and change the exploration primitive rather than tuning this run.
