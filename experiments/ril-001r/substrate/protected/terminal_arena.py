from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FAMILIES = ("bug", "performance", "constraint", "flaky", "migration", "cleanup")

# The terminal arena is deliberately a different surface from the training scorer.
# The final generator is used to choose search tactics for a live Hermes call; Hermes
# then has to solve receiver-generated maintenance triage cases from evidence.

@dataclass(frozen=True)
class Case:
    case_id: str
    family: str
    context: str
    options: dict[str, str]
    answer: str
    files: dict[str, str]


def _token(rng: random.Random, prefix: str) -> str:
    return f"{prefix}_{rng.randrange(1000, 9999)}"


def _shuffled_options(rng: random.Random, correct: str, wrong: list[str]) -> tuple[dict[str, str], str]:
    values = [correct, *wrong]
    rng.shuffle(values)
    keys = ["A", "B", "C", "D"]
    options = dict(zip(keys, values))
    answer = next(key for key, value in options.items() if value == correct)
    return options, answer


def _case(seed_rng: random.Random, family: str, index: int) -> Case:
    cid = f"{family}-{index:02d}"
    component = _token(seed_rng, family[:3])
    peer1 = _token(seed_rng, "peer")
    peer2 = _token(seed_rng, "peer")
    peer3 = _token(seed_rng, "peer")

    if family == "bug":
        correct = f"in {component}, split raw fields first and unescape each field second"
        options, answer = _shuffled_options(seed_rng, correct, [
            f"in {component}, unescape the full payload first and split fields second",
            f"in {component}, normalize delimiter runs first and then split before unescaping",
            f"in {component}, collapse doubled escapes first and then split decoded text",
        ])
        context = (
            f"A parser regression in {component} appears only when an escaped delimiter is present. "
            "Several stage-order fixes are plausible. Choose the one supported by repository evidence."
        )
        files = {
            "tests.txt": f"edge::{component}: split raw fields first; unescape each field only after boundaries are fixed.\n",
            "trace.txt": f"trace::{component}: current regression unescapes before splitting; delimiter then becomes structural.\n",
            "baseline.txt": f"baseline::{component}: ordinary unescaped inputs pass.\n",
            "constraints.txt": "constraint: escaping remains part of the public input contract.\n",
            "docs.txt": "docs: parser accepts escaped delimiters for backward compatibility.\n",
            "history.txt": "history: escaping was added to preserve literal delimiters in field values.\n",
            "adversarial.txt": f"adversarial::{component}: value='left\\|right|tail' must remain two fields.\n",
        }
    elif family == "performance":
        correct = f"optimize {component} first while preserving output semantics"
        options, answer = _shuffled_options(seed_rng, correct, [
            f"optimize {peer1} first while preserving output semantics",
            f"optimize {peer2} first while preserving output semantics",
            f"optimize {peer3} first while preserving output semantics",
        ])
        context = (
            f"Throughput dropped after a refactor. Candidate hot paths include {component}, {peer1}, {peer2}, and {peer3}. "
            "Choose the first optimization target supported by measured evidence."
        )
        files = {
            "profile.txt": f"profile: {component}=71.4% CPU; {peer1}=4.2%; {peer2}=2.1%; {peer3}=1.8%.\n",
            "baseline.txt": "baseline: outputs are correct but throughput is below the receiver threshold.\n",
            "tests.txt": "tests: output ordering and validation behavior are contractual.\n",
            "constraints.txt": "constraint: semantics and validation may not be weakened for speed.\n",
            "docs.txt": "docs: optimize the measured hot path before broad rewrites.\n",
            "history.txt": f"history: {component} entered the hot path in the last refactor.\n",
            "adversarial.txt": "adversarial: malformed input must still be rejected.\n",
        }
    elif family == "constraint":
        flag = f"--{component.replace('_', '-')}"
        correct = f"preserve {flag} semantics and refactor only the internal implementation"
        options, answer = _shuffled_options(seed_rng, correct, [
            f"keep the spelling {flag} but switch it to the new default semantics now",
            f"accept {flag} only through a compatibility shim that changes its edge-case result",
            f"replace {flag} with an alias that is accepted but ignored by the implementation",
        ])
        context = (
            f"A cleanup touches compatibility behavior around {flag}. Multiple transition policies are plausible. "
            "Choose the policy supported by the maintainer record."
        )
        files = {
            "constraints.txt": f"maintainer constraint: {flag} is supported through the next major release; semantics must not change.\n",
            "docs.txt": f"compatibility: preserve {flag}; internal implementation may change.\n",
            "history.txt": f"history: prior PR reverting removal of {flag} because downstream users depend on it.\n",
            "tests.txt": f"contract test: {flag} still produces the legacy-compatible result.\n",
            "baseline.txt": "baseline: all current compatibility tests pass.\n",
            "adversarial.txt": f"adversarial: old client invokes {flag} exactly as documented.\n",
        }
    elif family == "flaky":
        correct = f"wait for terminal evidence from {component} and reconcile once before classification"
        options, answer = _shuffled_options(seed_rng, correct, [
            f"retry the {component} request once when the first observation is non-success",
            f"debounce {component} observations for a fixed interval and use the earliest status",
            f"serialize {component} callbacks behind a process-local mutex before classification",
        ])
        context = (
            f"CI around asynchronous receiver {component} is intermittent. Retry, debounce, reconciliation, and serialization are all plausible repairs. "
            "Choose the one supported by the trace and contract evidence."
        )
        files = {
            "trace.txt": f"trace: {component} returns pending, then terminal-success 180ms later; classifier currently reads only the first state.\n",
            "adversarial.txt": f"control: true terminal-failure from {component} must still remain failure after reconciliation.\n",
            "baseline.txt": "baseline: repeated runs alternate pass/fail without code changes.\n",
            "tests.txt": "test contract: distinguish pending from terminal-failure; no blanket retry success.\n",
            "constraints.txt": "constraint: do not mask a terminal failure.\n",
            "history.txt": "history: provider became asynchronous; old synchronous assumption remained.\n",
        }
    elif family == "migration":
        old = f"{component}_v1"
        new = f"{component}_v2"
        correct = f"write {new} and read both {new} and {old} during the compatibility window"
        options, answer = _shuffled_options(seed_rng, correct, [
            f"write both {new} and {old} but read only {new} immediately",
            f"continue writing {old} while reading both fields until the next major boundary",
            f"write {new} and read only {new}, with legacy conversion handled out of band",
        ])
        context = (
            f"A schema migration renames {old} to {new}. Several mixed-version transitions are plausible. "
            "Choose the exact transition supported by the frozen migration record."
        )
        files = {
            "docs.txt": f"migration: new writers emit {new}; readers accept both {new} and {old} until the next major boundary.\n",
            "tests.txt": f"compat test: legacy fixture containing only {old} must still load.\n",
            "history.txt": f"history: rename to {new} approved with one-release read compatibility for {old}.\n",
            "constraints.txt": "constraint: no flag day; mixed-version fleets are expected.\n",
            "baseline.txt": f"baseline: current code reads {old} but has not begun writing {new}.\n",
            "adversarial.txt": f"adversarial: input containing only {new} must also load.\n",
        }
    elif family == "cleanup":
        correct = f"fold duplicate branch {component} into {peer1} after the shared validation step"
        options, answer = _shuffled_options(seed_rng, correct, [
            f"fold {peer1} into {component} before the shared validation step",
            f"fold {component} into {peer2} and keep separate validation paths",
            f"fold {peer1} into {peer3} and preserve {component} as the compatibility path",
        ])
        context = (
            f"A cleanup request identifies possible duplication among {component}, {peer1}, {peer2}, and {peer3}. "
            "Choose the exact consolidation supported by tests, baseline behavior, and history."
        )
        files = {
            "tests.txt": f"tests: {component} and {peer1} must produce the same validated result for all existing fixtures.\n",
            "baseline.txt": f"baseline: {component} duplicates {peer1} after validation; no distinct side effect is observed.\n",
            "constraints.txt": "constraint: validation and output semantics are protected.\n",
            "history.txt": f"history: {component} was copied from {peer1} during an emergency patch.\n",
            "docs.txt": "docs: refactors should reduce duplication without changing public behavior.\n",
            "adversarial.txt": "adversarial: invalid input must still fail after cleanup.\n",
        }
    else:
        raise ValueError(f"unknown family: {family}")

    task = (
        f"Case {cid}. {context}\n"
        "Select exactly one option ID from the task record after inspecting whatever evidence is needed."
    )
    return Case(cid, family, task, options, answer, files)


def generate_cases(seed_hex: str, per_kind: int) -> list[Case]:
    seed = int(hashlib.sha256(seed_hex.encode("utf-8")).hexdigest(), 16)
    rng = random.Random(seed)
    rows: list[Case] = []
    for family in FAMILIES:
        for index in range(1, per_kind + 1):
            rows.append(_case(rng, family, index))
    rng.shuffle(rows)
    return rows


def materialize_visible(root: str | Path, cases: list[Case]) -> dict[str, Any]:
    root = Path(root)
    cases_dir = root / "cases"
    cases_dir.mkdir(parents=True, exist_ok=False)
    manifest = []
    for case in cases:
        cdir = cases_dir / case.case_id
        cdir.mkdir()
        task = {
            "case_id": case.case_id,
            "context": case.context,
            "options": case.options,
        }
        (cdir / "TASK.json").write_text(json.dumps(task, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for name, text in case.files.items():
            (cdir / name).write_text(text, encoding="utf-8")
        manifest.append({
            "case_id": case.case_id,
            "task_sha256": hashlib.sha256((cdir / "TASK.json").read_bytes()).hexdigest(),
            "visible_files": {
                name: hashlib.sha256((cdir / name).read_bytes()).hexdigest()
                for name in sorted(case.files)
            },
        })
    value = {"schema": "openline.ril-001.terminal-visible.v1", "cases": manifest}
    (root / "VISIBLE_MANIFEST.json").write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return value


def gold(cases: list[Case]) -> dict[str, str]:
    return {case.case_id: case.answer for case in cases}


def score_answers(cases: list[Case], answers: dict[str, Any]) -> tuple[dict[str, Any], list[bool]]:
    expected = gold(cases)
    outcomes = []
    by_family: dict[str, dict[str, int]] = {}
    for case in cases:
        observed = str(answers.get(case.case_id, "")).strip().upper()
        ok = observed == expected[case.case_id]
        outcomes.append(ok)
        bucket = by_family.setdefault(case.family, {"successes": 0, "total": 0})
        bucket["total"] += 1
        bucket["successes"] += int(ok)
    successes = sum(outcomes)
    total = len(outcomes)
    return {
        "successes": successes,
        "total": total,
        "success_rate": successes / total if total else 0.0,
        "by_family": by_family,
    }, outcomes
