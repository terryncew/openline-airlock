# AIRLOCK-REPO-EVIDENCE-001

This experiment is the fresh falsifier earned by AIRLOCK-SWE-GATE-001.

AIRLOCK-SWE-GATE-001 found two separate things: zero-config initialization was
too unreliable for the twelve-repository aggregate, and independently a Flake8
pair showed that functionally passing patches could remain indistinguishable to
Airlock even when only one satisfied a repository maintainer constraint.

PR #100 changed the product boundary: executable correctness and repository-owned
acceptance evidence are now evaluated separately. This experiment tests only
that acceptance correction. It does not test or repair initialization.

## Frozen product

Airlock product base:

`c2495433c6da402f2ca9492f1830d2e4bc2b2bb7`

The workflow fails before the external cases if `src/airlock`,
`src/airlock_submit`, or `pyproject.toml` differ from that base.

## Fresh cases

Exactly four repositories are frozen before execution:

- `CodMughees/envradar` — repository CI and CONTRIBUTING evidence; Ruff constraint.
- `Technologicat/pyan` — repository CI evidence; Ruff constraint.
- `pallets/itsdangerous` — pre-commit repository evidence.
- `osori/korean-romanizer` — repository quality workflow; mypy constraint.

None is one of the twelve AIRLOCK-SWE-GATE-001 repositories.

For every case, two one-commit candidates share one base. Both must pass the
same explicit functional target. External truth must independently establish
that the noncompliant candidate fails the pre-existing repository constraint
and the compliant candidate passes it.

That external constraint command is never supplied to Airlock. Airlock gets
only the functional target. Its current product code must discover whatever
additional acceptance evidence the repository itself owns.

## Verdict boundary

`DISCRIMINATED` means the noncompliant candidate is withheld while the compliant
candidate survives.

`UNDERCONSTRAINED` means both survive. One live-verified underconstrained pair
falsifies the current general discovery claim.

`OVERCONSERVATIVE_OR_INSUFFICIENT` means both are withheld. That is not success.

`INVERTED` means the noncompliant candidate survives while the compliant
candidate is withheld.

The strong claim is earned only if all four fresh pairs are `DISCRIMINATED`.

Do not rerun AIRLOCK-SWE-GATE-001 and do not repair a negative result inside this
experiment. Freeze the receipt first.
