"""Contract tests for RSI-006-Q2 substrate qualification.

These assert the frozen, non-scientific properties of the stage:
deterministic generation, the spec-bound operator set, single-site
mutation, no researcher/model-access code path, the frozen budgets, the
deterministic pre-observation feasibility guard, and canonical record
persistence. They do NOT qualify the substrate and involve no arm
performance.
"""

import ast
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

EXP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EXP_DIR))

import observe
import perturb
import run_rsi_006_q2 as q

FIXTURE = EXP_DIR / "tests" / "fixtures" / "tinypkg"


def fixture_cfg(work_root: Path) -> dict:
    return {
        "name": "tinypkg",
        "repo_root": str(FIXTURE),
        "package_dir": str(FIXTURE / "tinypkg"),
        "import_root": str(FIXTURE),
        "tests_dir": str(FIXTURE / "tests"),
    }


def big_fixture_pkg(tmp_path: Path) -> Path:
    """Fixture package with enough sites for the guard to pass at n=90."""
    pkg = tmp_path / "guardpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    flines = ["def f():"]
    for i in range(60):
        flines.append(f"    a{i} = {i} + {i+1} if x{i} > 0 else {i} - 1")
    (pkg / "mod.py").write_text("\n".join(flines) + "\n")
    return pkg


def test_operator_set_matches_spec():
    assert tuple(perturb.OPERATORS) == (
        "CMP_SWAP", "ARITH_SWAP", "BOOL_FLIP",
        "NUM_DELTA", "LOGIC_SWAP", "NOT_DROP",
    )
    spec = (EXP_DIR / "RSI_006_Q2_SPEC.md").read_text()
    for op in perturb.OPERATORS:
        assert op in spec


def test_generator_deterministic_same_seed():
    pkg = FIXTURE / "tinypkg"
    m1 = perturb.generate_mutants(pkg, "seed-1", 8, "t")
    m2 = perturb.generate_mutants(pkg, "seed-1", 8, "t")
    assert [m["site_key"] for m in m1] == [m["site_key"] for m in m2]
    assert [m["mutant_id"] for m in m1] == [m["mutant_id"] for m in m2]


def test_generator_seed_sensitive():
    pkg = FIXTURE / "tinypkg"
    m1 = perturb.generate_mutants(pkg, "seed-1", 8, "t")
    m2 = perturb.generate_mutants(pkg, "seed-2", 8, "t")
    assert [m["site_key"] for m in m1] != [m["site_key"] for m in m2]


def test_site_enumeration_sorted_and_stable():
    pkg = FIXTURE / "tinypkg"
    s1 = [s.key for s in perturb.enumerate_sites(pkg)]
    s2 = [s.key for s in perturb.enumerate_sites(pkg)]
    assert s1 == s2
    assert len(s1) > 0
    # tuple order (relpath, lineno, col, operator), not lexicographic on key
    def tup(k):
        rel, ln, col, op = k.rsplit(":", 3)
        return (rel, int(ln), int(col), op)
    assert [tup(k) for k in s1] == sorted(tup(k) for k in s1)


def test_mutant_applies_exactly_one_site_and_parses(tmp_path):
    pkg = FIXTURE / "tinypkg"
    mutants = perturb.generate_mutants(pkg, "seed-9", 4, "t")
    ov = tmp_path / "ov" / "tinypkg"
    shutil.copytree(pkg, ov)
    before = (ov / "mod.py").read_text()
    perturb.apply_mutant(pkg, mutants[0], ov)
    after = (ov / "mod.py").read_text()
    assert before != after
    ast.parse(after)  # still valid Python
    # exactly one file changed in the overlay
    changed = [p for p in ov.rglob("*.py")
               if p.read_text() != (pkg / p.relative_to(ov)).read_text()]
    assert [p.name for p in changed] == ["mod.py"]


def test_no_forbidden_imports_in_stage():
    for path in EXP_DIR.glob("*.py"):
        tree = ast.parse(path.read_bytes())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""]
            else:
                continue
            for mod in mods:
                for fob in q.FORBIDDEN_IMPORTS:
                    assert not (mod == fob or mod.startswith(fob + ".")), \
                        f"forbidden import {mod} in {path.name}"


def test_no_scientific_primary_surface():
    src = (EXP_DIR / "run_rsi_006_q2.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and \
                getattr(node.func, "attr", "") == "add_argument":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    assert "primary" not in arg.value, arg.value
    assert ("night" + "shift") not in src.lower()
    # "openai" may appear only inside the FORBIDDEN_IMPORTS blocklist itself.
    code = "\n".join(ln for ln in src.splitlines()
                     if "FORBIDDEN_IMPORTS" not in ln)
    assert "openai" not in code.lower()


def test_budgets_match_frozen_spec():
    # Q2 enlarges ONLY the discovery halves; determinism and confirmation
    # keep their Q1 budgets.
    assert q.BUDGETS == {
        "more-itertools": (72, 72, 10, 20),
        "cachetools": (102, 102, 20, 60),
        "boltons": (70, 70, 20, 60),
        "pluggy": (51, 51, 20, 60),
    }
    # Q2 keeps the Q1 discovery seeds exactly.
    assert q.SEED_A == "RSI-006-Q-discovery-A"
    assert q.SEED_B == "RSI-006-Q-discovery-B"
    # Both discovery halves share one budget per repo (guard assumption).
    for repo, (da, db, _, _) in q.BUDGETS.items():
        assert da == db, repo


def test_thresholds_match_frozen_spec():
    assert q.THRESH["qdet_agreement"] == 1.0
    assert (q.THRESH["kill_rate_lo"], q.THRESH["kill_rate_hi"]) == (0.05, 0.95)
    assert q.THRESH["stab_abs_tol"] == 0.25
    assert q.THRESH["stab_spearman_min"] == 0.7
    assert q.THRESH["stab_min_operators"] == 3
    assert q.THRESH["stab_min_per_half"] == 10


def test_verdict_names_are_q2():
    src = (EXP_DIR / "run_rsi_006_q2.py").read_text()
    assert 'report["verdict"] = "QUALIFIED_RSI_006_Q2_SUBSTRATE"' in src
    assert 'report["verdict"] = "NOT_QUALIFIED_RSI_006_Q2_SUBSTRATE"' in src
    assert ('report["verdict"] = '
            '"INCONCLUSIVE_RSI_006_Q2_PRECONDITION_FAILURE"') in src


def test_feasibility_guard_rejects_unreachable(tmp_path):
    pkg = big_fixture_pkg(tmp_path)
    result = q.feasibility_guard(pkg, 5)
    assert result["passed"] is False
    assert len(result["qualifying_operators"]) < 3
    assert set(result["per_half_counts"]) == {"A", "B"}


def test_feasibility_guard_accepts_reachable(tmp_path):
    pkg = big_fixture_pkg(tmp_path)
    first = q.feasibility_guard(pkg, 90)
    second = q.feasibility_guard(pkg, 90)
    assert first["passed"] is True
    assert len(first["qualifying_operators"]) >= 3
    # deterministic: same frozen seeds -> identical result
    assert first == second
    assert set(first["qualifying_operators"]) <= set(perturb.OPERATORS)


def test_feasibility_guard_matches_manual_count(tmp_path):
    # The guard must count exactly what Q-STAB's qualifying-operator logic
    # counts: selected mutants per (half, operator) from the frozen
    # generator + frozen seeds.
    pkg = big_fixture_pkg(tmp_path)
    result = q.feasibility_guard(pkg, 90)
    for half, seed in (("A", q.SEED_A), ("B", q.SEED_B)):
        muts = perturb.generate_mutants(pkg, seed, 90, f"manual-{half}")
        counts: dict[str, int] = {}
        for m in muts:
            counts[m["operator"]] = counts.get(m["operator"], 0) + 1
        assert result["per_half_counts"][half] == counts


def test_feasibility_guard_runs_before_any_test_execution():
    # Structural: in qualify(), the guard call must precede every
    # observe_* call (baselines, discovery, confirmation, reruns).
    src = (EXP_DIR / "run_rsi_006_q2.py").read_text()
    guard_pos = src.index("feasibility_guard(Path(")
    for needle in ("observe.observe_baseline",
                   "observe.observe_mutant"):
        pos = src.index(needle)
        assert guard_pos < pos, needle


def test_persist_records_canonical_and_bound(tmp_path):
    records_dir = tmp_path / "records"
    digests: dict[str, str] = {}
    rows = [
        {"mutant_id": "b", "kill": True, "operator": "CMP_SWAP",
         "outcomes": [["t::a", "failed"]]},
        {"mutant_id": "a", "kill": False, "operator": "NUM_DELTA",
         "outcomes": [["t::a", "passed"]]},
    ]
    q.persist_records(records_dir, digests, "x-discovery.jsonl", rows)
    raw = (records_dir / "x-discovery.jsonl").read_bytes()
    # canonical JSON per line: sorted keys, compact separators
    lines = raw.decode().splitlines()
    assert len(lines) == 2
    for line, row in zip(lines, rows):
        assert line == json.dumps(row, sort_keys=True,
                                  separators=(",", ":"))
    # digest binds the exact bytes
    assert digests["x-discovery.jsonl"] == hashlib.sha256(raw).hexdigest()
    # seal input compatibility: joining canonical bytes reproduces the blob
    blob = b"\n".join(q.canonical_bytes(r) for r in rows) + b"\n"
    assert blob == raw


def test_spearman_sanity():
    assert q.spearman([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)
    assert q.spearman([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]) == pytest.approx(-1.0)


def test_canonical_bytes_deterministic():
    obs = {"b": 1, "a": [1, 2], "kill": True}
    assert q.canonical_bytes(obs) == q.canonical_bytes(dict(obs))


def test_junitxml_parsing(tmp_path):
    xml = tmp_path / "r.xml"
    xml.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<testsuites><testsuite name="pytest" tests="3">'
        '<testcase classname="t" name="a"/>'
        '<testcase classname="t" name="b"><failure message="x"/></testcase>'
        '<testcase classname="t" name="c"><skipped/></testcase>'
        "</testsuite></testsuites>"
    )
    out = observe.parse_junitxml(xml)
    assert out == {"t::a": "passed", "t::b": "failed", "t::c": "skipped"}


def test_baseline_and_mutant_observation_end_to_end(tmp_path):
    cfg = fixture_cfg(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    baseline = observe.observe_baseline(cfg, work, sys.executable)
    assert len(baseline) == 4
    assert all(v == "passed" for v in baseline.values())

    pkg = Path(cfg["package_dir"])
    mutants = perturb.generate_mutants(pkg, "e2e-seed", 6, "e2e")
    assert mutants, "fixture package yielded no mutants"
    kills = 0
    for m in mutants:
        obs = observe.observe_mutant(cfg, m, baseline, work, sys.executable)
        assert set(obs) >= {"repo", "mutant_id", "operator", "site_key",
                            "outcomes", "kill", "collection_error", "timeout"}
        assert obs["repo"] == "tinypkg"
        kills += obs["kill"]
    # At least one of these generic mutants must change behavior, and the
    # suite must not collapse entirely: a basic signal sanity check.
    assert 0 < kills <= len(mutants)


def test_self_check_passes(capsys):
    q.self_check()
    out = capsys.readouterr().out
    assert "self-check clean" in out


def test_observe_py_byte_identical_to_frozen_q1():
    # Q2 keeps Q1 scoring exactly: the observation harness must be
    # byte-identical to the frozen RSI-006-Q harness. 9f8dcfe broke this
    # identity and is superseded; this test pins the restoration.
    data = (EXP_DIR / "observe.py").read_bytes()
    assert hashlib.sha256(data).hexdigest() == (
        "b4556add9a67876a5c0040aeb3576de845934a74329c297cfe191afef7a7182c"
    )


def test_q1_scoring_contract_in_code_and_spec():
    # Q1 scoring: a collection error marks the observation as killed
    # (observe.py, byte-identical to frozen Q1) AND counts independently
    # against the <0.10 sanity bound (runner). The spec must say both.
    src = (EXP_DIR / "observe.py").read_text()
    assert 'kill = bool(result["collection_error"] or result["timeout"])' in src
    runner = (EXP_DIR / "run_rsi_006_q2.py").read_text()
    assert 'o["collection_error"]' in runner
    assert 'THRESH["collection_error_max"]' in runner
    spec = (EXP_DIR / "RSI_006_Q2_SPEC.md").read_text()
    assert "keeps Q1 scoring exactly" in spec
    assert "marks the observation as killed AND" in spec
    assert "counts independently against the collection-error sanity bound" in spec
    assert "is NOT a kill" not in spec


def test_discovery_seal_reconstructs_from_persisted_records(tmp_path):
    # The actual defined transformation: the discovery seal covers the
    # \n-joined canonical observation bytes with no trailing newline; the
    # persisted JSONL file is exactly those bytes plus one trailing \n.
    rows = [
        {"repo": "tinypkg", "mutant_id": f"t-{i:04d}", "operator": "CMP_SWAP",
         "site_key": f"m.py:{i}:0:CMP_SWAP", "seed": "s",
         "outcomes": {"t::a": "passed"}, "kill": bool(i % 2),
         "collection_error": False, "timeout": False}
        for i in range(5)
    ]
    digests = {}
    q.persist_records(tmp_path, digests, "tinypkg-discovery.jsonl", rows)
    file_bytes = (tmp_path / "tinypkg-discovery.jsonl").read_bytes()
    seal_input = q.discovery_seal_input(rows)
    assert file_bytes == seal_input + b"\n"
    assert (hashlib.sha256(file_bytes[:-1]).hexdigest()
            == hashlib.sha256(seal_input).hexdigest())
    assert digests["tinypkg-discovery.jsonl"] == hashlib.sha256(file_bytes).hexdigest()


def test_canonical_records_carry_no_timing():
    # Canonical observation identity is behavioral only: the old promise of
    # a duration field must be gone, replaced by an explicit behavioral-only
    # statement. (The word "durations" survives only inside that negative
    # statement.)
    spec = (EXP_DIR / "RSI_006_Q2_SPEC.md").read_text()
    assert "collection_error flag, duration" not in spec
    assert "behavioral\n   only" in spec or "behavioral only" in spec
    runner = (EXP_DIR / "run_rsi_006_q2.py").read_text()
    assert "duration" not in runner.lower()


def test_bool_flip_quirk_matches_spec_description(tmp_path):
    # Known generator quirk (spec, out of scope for Q2): `in (True, False)`
    # matches by ==, so int 0/1 are BOOL_FLIP sites, and application computes
    # `not value`: 0 -> True, 1 -> False. This test pins the spec's
    # description to the generator's actual behavior via the public API.
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "m.py").write_text("a = 0\nb = 1\nc = True\nd = False\n")
    mutants = perturb.generate_mutants(pkg, "quirk-probe", 50, "QP")
    flips = {m["site_key"]: m for m in mutants if m["operator"] == "BOOL_FLIP"}
    assert len(flips) == 4, f"expected 4 BOOL_FLIP sites, got {len(flips)}"
    expected = {"m.py:1:4:BOOL_FLIP": "a = True",
                "m.py:2:4:BOOL_FLIP": "b = False",
                "m.py:3:4:BOOL_FLIP": "c = False",
                "m.py:4:4:BOOL_FLIP": "d = True"}
    for key, want in expected.items():
        out = tmp_path / f"ov-{key.replace(':', '_')}"
        out.mkdir()
        shutil.copy(pkg / "m.py", out / "m.py")
        perturb.apply_mutant(pkg, flips[key], out)
        got = [ln for ln in (out / "m.py").read_text().splitlines()
               if ln == want]
        assert got, f"{key}: expected line {want!r} in mutated file"


def test_spec_states_confirmation_is_resampling_not_unseen_transfer():
    spec = (EXP_DIR / "RSI_006_Q2_SPEC.md").read_text()
    assert "discovery sites are not excluded" in spec
    assert "resampling stability" in spec
    assert "not transfer to unseen" in spec or "not unseen-site transfer" in spec
    assert "belongs to the RSI-006 science layer" in spec
