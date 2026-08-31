# AIRLOCK-COLD-ADOPTION-001

Status: **PASS on 0.2.2 after a falsifying 0.2.1 run**

## Frozen target

- Repository: `terryncew/terrynce-curve-emergence-tuner`
- Commit: `fbb43d7667b2f47f906ebeb76613b87928c592be`
- Airlock under test: merged `0.2.1` commit `d3ca3dac6e5543152b3b004b3ca9d2d7e8535026`
- Target edits allowed: none
- Target check edits allowed: none
- Target rule edits allowed after `airlock init`: none

The target's declared CI command sequence passed unchanged under Python 3.12:

1. `pip install -e '.[dev]'`
2. `pytest` — 21 tests and 10 subtests passed
3. `tk001 synthetic /tmp/airlock-cold-adoption-synthetic39.csv`
4. `tk001 validate /tmp/airlock-cold-adoption-synthetic39.csv`
5. `tk001 replay /tmp/airlock-cold-adoption-synthetic39.csv`

Zero-config `airlock init` detected Python/pytest, confirmed the starting commit, protected `tests/**`, `.github/**`, `.airlock/**`, and `pyproject.toml`, and required `pytest -q`.

The canonical SHA-256 of those protected paths plus the complete verification section was unchanged across every candidate run:

`29e02b9570fd5fbfdf43221a9ab255d4031266d96f068e98430a8537b2f8f507`

Only provider commands for deterministic experiment arms were added outside that boundary.

## Falsifier

The candidate changed `load_protocol()` to raise `AIRLOCK_CANDIDATE_BINDING_SENTINEL` unconditionally. No protected path changed. The patch is frozen in `docs/receipts/airlock-cold-adoption-001-sentinel.patch`.

The same candidate content was used on both versions:

- Candidate patch SHA-256: `48bc0a4493ad177d6547bb75c25ffc61902f0222b8526ba70b24952fb300c4e8`
- Candidate tree: `1bf536655fb3594d385bd0ce5f97f824a772ff2d`

### 0.2.1 result — FAIL

Airlock returned `READY`, marked the candidate `SURVIVED`, and wrote a signed `READY_FOR_REVIEW` record even though the candidate made three tests fail when its source was actually imported.

- Run: `20260901-075818-4fdbd7`
- Run SHA-256: `1e903b83a802db70e3c73b4d57a58ef4e461c88b6fbf95d3c5b715ebdd82b58a`
- Signed record SHA-256: `13478d10be734c28036d4b0fd97e7f9bb88cc6b47bd55390f1772a5af51c978c`
- Raw run: `docs/receipts/airlock-cold-adoption-001-v0.2.1-run.json`
- Raw signed record: `docs/receipts/airlock-cold-adoption-001-v0.2.1-verification.json`
- Observed import: the original checkout's `src/terrynce_kilauea/protocol.py`
- Default `tests/test_protocol.py` exit code: `0`
- Candidate-bound `tests/test_protocol.py` exit code: `1`

Cause: the target's editable install put the starting checkout on Python's import path. Local Airlock checks ran in a candidate Git worktree but did not put that worktree's `src/` ahead of the editable base path.

### 0.2.2 result — PASS

Airlock now puts the active worktree's `src/` and repository root first on `PYTHONPATH` for baseline, agent, and local candidate checks. The legacy container worker now uses the same candidate path already used by the Actions evaluator.

The identical sentinel candidate returned `NO_PATCH_READY`, `BLOCKED`, `TESTS_FAILED`; `pytest -q` exited `1` and named the sentinel in failures.

- Run: `20260901-080309-b86fba`
- Run SHA-256: `dfe9f9a8a161b416b1bd09760208213b7612885f8b9e0c93c3742c2cfa85af4c`
- Raw run: `docs/receipts/airlock-cold-adoption-001-v0.2.2-run.json`
- Signed survivor record: none

## Frozen 0.2.2 arms

| Arm | Expected | Observed | Run SHA-256 |
|---|---|---|---|
| Behavior-preserving `protocol.py` refactor | `SURVIVED` | `READY / SURVIVED` | `c5ea3efac14b70b4a8873aa2a2daf11734419e31841096770508a5ebd4911162` |
| Edit `tests/test_protocol.py` | `BLOCKED` before commands | `PROTECTED_FILES_CHANGED`; no command ran | `3f1371a6332eb3e53bea6118f54ffe4acdd9d29dff5b32b6d168ad878007cc62` |
| Add unreferenced `tools/cold_adoption_probe.py` | `NEEDS_EVIDENCE` | `no_baseline_test_references_changed_module` | `645b6466126b3acc4ff68e124193ca769c4fd5e8406ca60ad2993672f5565f0d` |

The target commit remained unchanged and had no tracked diff after the runs.

## Boundary

This proves the listed Python target and candidate arms against the exact commits and hashes above. It does not prove candidate binding for every build system or custom command. No public fork submission was made; the GitHub contribution path is not evidence for this increment.
