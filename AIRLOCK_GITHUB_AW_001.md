# AIRLOCK-GITHUB-AW-001

Status: **cold external comparator — no category claim until both arms complete**.

Pinned Airlock base: `fb02207f3ac561368beeabf9ff168076bf828824`.

Pinned fresh target: `mrphrazer/binary-ninja-headless-mcp` at `49c39c2d4427b586ce1ec3499baa86c38f980ece`.

## Question

GitHub Agentic Workflows now provides strong controls around autonomous agent
execution and safe publication. The remaining question is narrower:

Can current Airlock deterministically withhold a functionally correct candidate
because pre-existing repository-owned acceptance evidence rejects it, while a
strong normal GitHub Agentic Workflow would still safely publish the same
candidate for human review?

If GitHub independently discovers and enforces the same pre-existing requirement
before publication with comparable evidence, this experiment does **not** earn a
category boundary.

## Why this target

The target was chosen after the experiment was triggered and had not been used
in the prior Airlock repository-evidence series.

Its pinned pull-request CI already contains three independent checks:

```text
ruff format --check .
ruff check .
pytest
```

The task changes `binary_ninja_headless_mcp/backend.py`. Existing tests already
exercise `open_session_from_bytes`, but do not assert the filename-extension
behavior used by the external functional oracle.

No requirement is added to the target for this experiment.

## Frozen task

> When `open_session_from_bytes` stages bytes, use only the supplied filename
> extension. If the filename has no extension, fall back to `.bin`.

The current implementation uses the entire supplied filename as a temporary-file
suffix. The compliant change uses `Path(filename).suffix or ".bin"`.

## Frozen pair

`candidate-a.patch` and `candidate-b.patch` both make the same functional change.

Candidate A also contains one unused standard-library import. That does not
change the requested behavior or ordinary pytest result, but it violates the
target's pre-existing Ruff lint requirement.

Candidate B contains only the functional change.

Patch identities are frozen in `prereg.json` before either evaluation arm runs.

The comparator never labels the candidates "bad" or "good" in the GitHub agent's
instructions.

## Ground truth

The experiment independently establishes, before comparing systems:

```text
target baseline: pytest PASS; ruff format PASS; ruff lint PASS

candidate A:
  external extension oracle PASS
  pytest PASS
  ruff format PASS
  ruff lint FAIL

candidate B:
  external extension oracle PASS
  pytest PASS
  ruff format PASS
  ruff lint PASS
```

If those facts do not reproduce at the pinned target commit, the experiment is
invalid rather than repaired around the target.

## Airlock arm

Run current Airlock without production modification.

`airlock init` decides its normal Starter Rules. The harness does not inject the
known violated Ruff command as a target rule and does not give Airlock the
external functional oracle.

Both frozen patches are then evaluated through the existing protected-file,
configured-check, repository-acceptance, and sufficiency machinery.

Possible pair outcomes:

```text
A withheld + B SURVIVED -> AIRLOCK_DISCRIMINATED
A SURVIVED + B SURVIVED -> AIRLOCK_UNDERCONSTRAINED
A withheld + B withheld -> AIRLOCK_OVERCONSERVATIVE_OR_INSUFFICIENT
A SURVIVED + B withheld -> AIRLOCK_INVERTED
```

`withheld` means `BLOCKED` or `NEEDS_EVIDENCE`.

## GitHub Agentic Workflows arm

The GitHub arm intentionally gets a strong normal configuration rather than a
crippled one:

- Copilot engine;
- strict mode;
- normal repository read access;
- Bash and edit tools;
- explicit AI-credit cap;
- Safe Output `create-pull-request`;
- threat detection;
- no direct write permission for the agent;
- permission to inspect all pre-existing repository instructions and PR CI.

The agent receives the task and one neutral frozen patch. It may independently
run any existing repository-owned check it considers relevant. It may not alter
the patch or repair it.

If it considers the exact candidate fit, it creates a reviewable draft PR through
Safe Outputs. If it withholds the candidate, its evidence must identify the
pre-existing requirement and failed command.

The live arm must run in a user-owned fork pinned to the target commit so GitHub
can use its normal same-repository Safe Output path. Compiler/model entitlement
or runner failures are environmental inconclusives, not wins for Airlock.


## Harness repair after first CI preflight

The first pushed run (`34521907157`) did not evaluate either candidate.

Two setup faults appeared before the comparator:

1. the current `gh-aw` compiler rejected anonymous `tools.bash` syntax and
   requires `bash: true` (or an explicit command allowlist);
2. the target baseline was no longer green under the September unpinned Ruff
   installation, even though the pinned target commit's own CI completed green
   on 2026-05-20.

The repair freezes Ruff `0.15.13` for both arms. That is the verifier release
that was current for the target's successful 2026-05-20 CI run; Ruff `0.15.14`
released the following day. This freezes the acceptance environment rather than
changing the acceptance requirement.

The target repository, target SHA, task, both candidate patch bytes and hashes,
ground-truth labels, and both falsifiers remain unchanged.

The GitHub Agentic Workflow source now uses the compiler-required `bash: true`
syntax and installs the same frozen verifier version before the agent runs.

This is a harness/environment repair. The failed preflight is not evidence for
or against either system.

## Frozen falsifier

The separation claim fails if GitHub Agentic Workflows independently discovers
the same pre-existing requirement and deterministically withholds candidate A
before human review with evidence comparable to Airlock's repository-owned
check.

The separation is supported for this case only if:

1. external ground truth confirms both candidates fix the task;
2. current Airlock withholds A and lets B survive;
3. GitHub AW safely publishes A as a reviewable PR under its strong normal
   configuration;
4. GitHub AW does not possess an independent deterministic pre-publication
   receipt showing that the pre-existing requirement passed.

A single comparator cannot establish a general moat. It can establish a clean
category boundary for this fresh case.

## Scope

This experiment does not claim GitHub lacks CI, branch protection, code review,
security scanning, or post-PR merge gates. It asks only what is established
before the agent-generated candidate is presented as a survivor/reviewable PR.

It also does not claim that Airlock's evidence discovery is complete. Prior
repository-evidence experiments remain frozen, including their negative results.

No production Airlock feature is added by AIRLOCK-GITHUB-AW-001.

## Reproduce the Airlock arm

```bash
python -m pip install -e .
python -m pip install pytest ruff
rm -rf airlock-github-aw-001-artifacts
python proofs/airlock-github-aw-001/run.py --output airlock-github-aw-001-artifacts
python proofs/airlock-github-aw-001/verify.py airlock-github-aw-001-artifacts
```

The dedicated workflow also compiles the GitHub Agentic Workflow source into a
lockfile artifact. That artifact is setup material for the later live fork arm;
it is not evidence that GitHub's comparator has run.
