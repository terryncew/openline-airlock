# Hermes harness fingerprinting

Nightshift treats Hermes as a mutable worker. That is useful, but it creates a measurement problem: the same model can behave differently after its harness changes. Model identity alone is therefore insufficient attribution for an economics experiment.

Airlock now fingerprints the Hermes harness at the controller boundary before every Nightshift tournament and again immediately after the worker returns. The signed generation receipt binds repository state, model identity, the observed harness state, execution evidence, reported cost, and the independently evaluated result.

A transition is represented as:

`repo X + harness A + model M + cost -> verified result Z`

If persistent worker state changes during that generation window, the controller records `A -> B`. Before the next tournament Airlock requires the new pre-spend fingerprint to equal the prior observed `B`. If the state changed outside that observed transition, Nightshift refuses to spend. This makes harness lineage an enforced continuity condition rather than a label. The receipt proves the observed state transition and ordering; it does not prove which process caused every byte-level mutation inside that window.

## What is included

The Hermes-first fingerprint deliberately stays narrow. It binds:

- the Airlock model/profile identity and exact adapter command;
- the requested underlying model/routing setting from non-secret Hermes config when observable;
- a deterministic tool-registry fingerprint for tracked `tools/` state;
- Hermes source commit/version when observable, plus the executable SHA-256 when available;
- behavior-bearing `config.yaml` after credential values are redacted;
- global `SOUL.md`;
- persistent `skills/`, `memories/`, `hooks/`, `tools/`, and `context/` files when present.

Repository-local context such as `AGENTS.md`, `.hermes.md`, `CLAUDE.md`, or `.cursorrules` is already part of the repository state Airlock evaluates. The harness fingerprint is for mutable worker state outside that repo commit.

## What is excluded

Credentials and noisy runtime state stay outside the identity: `.env`, `auth.json`, secret-like filenames, key/token files, databases such as `state.db`, sessions, logs, caches, checkpoints, temporary state, and profile HOME contents. Credential rotation should not manufacture a new harness identity.

The receipt stores file digests and metadata, not file contents. `config.yaml` secret-like values are redacted before hashing. This is a provenance boundary, not a claim that arbitrary user-authored skill text can never contain sensitive material.

## Requested model versus effective model

Model routing is part of the measurement boundary. The pre-spend harness fingerprint records the model requested by Hermes configuration, the adapter command, and the tool-registry fingerprint. After execution, each attempt records the effective model from `agent_report.model` when the worker exposes it. If the worker does not expose an effective model, Airlock records `UNAVAILABLE` rather than silently assuming the requested model actually ran.

That distinction matters for fallback routers and future self-modifying harnesses: `requested M` and `effective M2` are different experimental states even if the same Hermes profile initiated both.

## SEARCH-004 rule

SEARCH-004 should not compare autonomous Hermes with maintainer-guided Hermes unless both arms record harness fingerprints. If the starting fingerprints differ, the comparison is confounded unless the preregistration explicitly makes harness choice an experimental variable. Every observed harness mutation during an arm must remain in the signed lineage. Where effective-model evidence is unavailable, that missing observation remains explicit in the receipt and should be treated as an attribution limitation rather than filled in by assumption.

That keeps the economic question clean: did the allocation method buy more independently verified value per dollar, or did one arm quietly run a different evolved harness?

Airlock stays outside the machinery being improved. Hermes can change its own harness; Hermes still cannot decide whether that change produced value worth paying for.
