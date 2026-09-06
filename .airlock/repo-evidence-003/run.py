#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import traceback
from typing import Any

AIRLOCK_ROOT = Path(__file__).resolve().parents[2]
if str(AIRLOCK_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(AIRLOCK_ROOT / "src"))

from airlock.acceptance import discover_acceptance_evidence
from airlock.discovery import protected_patterns
from airlock.gitops import changed_paths
from airlock.sandbox import WorktreeSandbox
from airlock.sieve import protected_files_check, run_checks, sufficiency_check
from airlock.util import compact_result, run as airlock_run, sha256_file, write_json

HERE = Path(__file__).resolve().parent
PREREG_PATH = HERE / "preregistration.json"
PRODUCT_PATHS = (
    "src/airlock/acceptance.py",
    "src/airlock/discovery.py",
    "src/airlock/sieve.py",
    "src/airlock/util.py",
)


def run(argv: list[str], cwd: Path, *, env: dict[str, str] | None = None, timeout: int = 900) -> dict[str, Any]:
    return compact_result(airlock_run(argv, cwd, env=env, timeout=timeout))


def git_blob_sha_bytes(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()


def git_blob_sha(path: Path) -> str:
    return git_blob_sha_bytes(path.read_bytes())


def git(repo: Path, *args: str, timeout: int = 300) -> str:
    result = airlock_run(["git", *args], repo, timeout=timeout)
    if result["exit_code"] != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result['stderr'][-2000:]}")
    return result["stdout"].strip()


def pristine(repo: Path, base: str) -> None:
    git(repo, "checkout", "--detach", base)
    git(repo, "reset", "--hard", base)
    git(repo, "clean", "-fdx")


def load_preregistration() -> dict[str, Any]:
    data = json.loads(PREREG_PATH.read_text())
    if data.get("experiment") != "AIRLOCK-REPO-EVIDENCE-003":
        raise RuntimeError("wrong preregistration experiment")
    case = data.get("case") or {}
    if not case.get("case_id"):
        raise RuntimeError("missing frozen case")

    excluded = set(data["freshness"]["excluded_airlock_swe_gate_001_repo_ids"])
    excluded |= set(data["freshness"]["excluded_airlock_repo_evidence_001_repo_ids"])
    excluded |= set(data["freshness"]["excluded_airlock_repo_evidence_002_repo_ids"])
    if case["repo_id"] in excluded:
        raise RuntimeError(f"freshness exclusion violated: {case['repo_id']}")
    return data


def verify_prior_receipt(prereg: dict[str, Any]) -> dict[str, Any]:
    spec = prereg["prior_receipt"]
    path = AIRLOCK_ROOT / spec["path"]
    if not path.is_file():
        raise RuntimeError(f"prior receipt missing: {spec['path']}")

    observed_blob = git_blob_sha(path)
    if observed_blob != spec["git_blob_sha"]:
        raise RuntimeError(
            f"prior receipt blob drift: expected {spec['git_blob_sha']} observed {observed_blob}"
        )

    data = json.loads(path.read_text())
    if data.get("experiment") != spec["required_experiment"]:
        raise RuntimeError("prior receipt experiment mismatch")
    if data.get("verdict") != spec["required_verdict"]:
        raise RuntimeError("prior receipt verdict mismatch")

    cases = {case["case_id"]: case for case in data.get("cases", [])}
    required = spec["required_cases"]
    if set(cases) != set(required):
        raise RuntimeError("prior receipt case set mismatch")
    for case_id, pair_class in required.items():
        if cases[case_id].get("pair_class") != pair_class:
            raise RuntimeError(
                f"prior receipt pair mismatch for {case_id}: "
                f"{cases[case_id].get('pair_class')} != {pair_class}"
            )

    counts = data.get("pair_class_counts") or {}
    for key, expected in spec["required_pair_class_counts"].items():
        if counts.get(key) != expected:
            raise RuntimeError(
                f"prior receipt count mismatch {key}: {counts.get(key)} != {expected}"
            )

    return {
        "path": spec["path"],
        "git_blob_sha": observed_blob,
        "experiment": data["experiment"],
        "verdict": data["verdict"],
        "pair_class_counts": counts,
        "validated": True,
    }


def verify_product_base(prereg: dict[str, Any]) -> dict[str, Any]:
    expected = prereg["airlock_product_base"]
    observed = git(AIRLOCK_ROOT, "rev-parse", "HEAD")
    product = {
        "expected_base": expected,
        "observed_head": observed,
        "preregistration_sha256": sha256_file(PREREG_PATH),
        "component_sha256": {path: sha256_file(AIRLOCK_ROOT / path) for path in PRODUCT_PATHS},
    }
    diff = airlock_run(
        ["git", "diff", "--exit-code", expected, "HEAD", "--", "src/airlock", "src/airlock_submit", "pyproject.toml"],
        AIRLOCK_ROOT,
        timeout=120,
    )
    product["product_diff_exit_code"] = diff["exit_code"]
    if diff["exit_code"] != 0:
        raise RuntimeError(
            "experiment branch changed frozen product paths: "
            + diff["stdout"][-1000:] + diff["stderr"][-1000:]
        )
    return product


def clone_exact(case: dict[str, Any], root: Path) -> tuple[Path, list[dict[str, Any]]]:
    repo = root / "repo"
    repo.mkdir(parents=True)
    records = [
        run(["git", "init", "-q"], repo, timeout=120),
        run(["git", "remote", "add", "origin", f"https://github.com/{case['repository']}.git"], repo, timeout=120),
        run(["git", "-c", "protocol.version=2", "fetch", "--no-tags", "--depth=1", "origin", case["commit"]], repo, timeout=600),
    ]
    if any(row["exit_code"] != 0 for row in records):
        raise RuntimeError("upstream fetch failed")
    records.append(run(["git", "checkout", "--detach", "FETCH_HEAD"], repo, timeout=120))
    if records[-1]["exit_code"] != 0:
        raise RuntimeError("upstream checkout failed")
    observed = git(repo, "rev-parse", "HEAD")
    if observed != case["commit"]:
        raise RuntimeError(f"commit mismatch: expected {case['commit']} observed {observed}")
    git(repo, "config", "user.name", "Airlock Repo Evidence")
    git(repo, "config", "user.email", "airlock-repo-evidence@example.invalid")
    return repo, records


def verify_anchors(repo: Path, case: dict[str, Any]) -> dict[str, str]:
    observed = {}
    for rel, expected in case["anchors"].items():
        path = repo / rel
        if not path.is_file():
            raise RuntimeError(f"anchor missing: {rel}")
        digest = git_blob_sha(path)
        observed[rel] = digest
        if digest != expected:
            raise RuntimeError(f"anchor drift {rel}: expected {expected} observed {digest}")
    return observed


def make_venv(case_root: Path) -> Path:
    venv = case_root / "venv"
    cp = subprocess.run(
        [sys.executable, "-m", "venv", str(venv)],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    if cp.returncode != 0:
        raise RuntimeError(f"venv creation failed: {cp.stderr[-2000:]}")
    return venv


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def venv_bin(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin")


def case_env(venv: Path, case_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = str(venv_bin(venv)) + os.pathsep + env.get("PATH", "")
    env["VIRTUAL_ENV"] = str(venv)
    env["UV_PROJECT_ENVIRONMENT"] = str(venv)
    env["UV_CACHE_DIR"] = str(case_root / "uv-cache")
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return env


@contextmanager
def installed_environment(env: dict[str, str]):
    old = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old)


def expand_setup(argv: list[str], venv: Path) -> list[str]:
    python = str(venv_python(venv))
    return [part.replace("{python}", python) for part in argv]


def setup_case(repo: Path, case_root: Path, case: dict[str, Any], venv: Path) -> list[dict[str, Any]]:
    env = case_env(venv, case_root)
    records = []
    bootstrap = run([str(venv_python(venv)), "-m", "pip", "install", "--upgrade", "pip"], repo, env=env, timeout=600)
    records.append(bootstrap)
    if bootstrap["exit_code"] != 0 or bootstrap["timed_out"]:
        raise RuntimeError("pip bootstrap failed")

    for raw in case["setup_commands"]:
        argv = expand_setup(raw, venv)
        record = run(argv, repo, env=env, timeout=case["timeout_seconds"])
        records.append(record)
        if record["exit_code"] != 0 or record["timed_out"]:
            raise RuntimeError(f"setup command failed: {argv}")

    tracked = run(["git", "status", "--porcelain", "--untracked-files=no"], repo, env=env, timeout=120)
    records.append(tracked)
    if tracked["exit_code"] != 0 or tracked["stdout_tail"].strip():
        raise RuntimeError("setup changed tracked repository state: " + tracked["stdout_tail"])
    return records


def apply_operations(repo: Path, operations: list[dict[str, Any]]) -> None:
    for op in operations:
        path = repo / op["path"]
        text = path.read_text(encoding="utf-8")
        if op["op"] == "append":
            path.write_text(text + op["text"], encoding="utf-8")
        elif op["op"] == "replace":
            old = op["old"]
            if text.count(old) != 1:
                raise RuntimeError(f"mutation needle count for {op['path']} is not 1")
            path.write_text(text.replace(old, op["new"], 1), encoding="utf-8")
        else:
            raise RuntimeError(f"unsupported mutation op {op['op']!r}")


def create_candidate(repo: Path, base: str, case: dict[str, Any], label: str) -> dict[str, Any]:
    pristine(repo, base)
    apply_operations(repo, case["mutations"][label])
    if not git(repo, "status", "--porcelain").strip():
        raise RuntimeError(f"{label} mutation created no change")
    git(repo, "add", "-A")
    git(repo, "commit", "--no-gpg-sign", "-m", f"AIRLOCK-REPO-EVIDENCE-003 {case['case_id']} {label}")
    commit = git(repo, "rev-parse", "HEAD")
    paths = changed_paths(repo, base, commit)
    patch = airlock_run(["git", "diff", "--binary", base, commit], repo, timeout=120)
    if patch["exit_code"] != 0:
        raise RuntimeError("cannot capture candidate patch")
    return {
        "label": label,
        "commit": commit,
        "changed_paths": paths,
        "patch_sha256": hashlib.sha256(patch["stdout"].encode()).hexdigest(),
    }


def run_command_in_commit(
    repo: Path,
    commit: str,
    argv: list[str],
    env: dict[str, str],
    timeout: int,
    prefix: str,
) -> dict[str, Any]:
    with WorktreeSandbox(repo, commit, prefix=prefix) as wt:
        candidate_env = dict(env)
        candidate_env["PYTHONPATH"] = os.pathsep.join(
            [str((wt / "src").resolve()), str(wt.resolve()), candidate_env.get("PYTHONPATH", "")]
        ).rstrip(os.pathsep)
        return compact_result(airlock_run(argv, wt, env=candidate_env, timeout=timeout))


def external_truth(
    repo: Path,
    base: str,
    candidates: dict[str, dict[str, Any]],
    case: dict[str, Any],
    env: dict[str, str],
) -> dict[str, Any]:
    baseline = run_command_in_commit(
        repo, base, case["external_acceptance_command"], env, case["timeout_seconds"],
        f"repo-evidence-003-{case['case_id']}-base-constraint-",
    )
    result = {"base_acceptance_constraint": baseline}
    for label in ("noncompliant", "compliant"):
        candidate = candidates[label]
        targets = [
            run_command_in_commit(
                repo, candidate["commit"], argv, env, case["timeout_seconds"],
                f"repo-evidence-003-{case['case_id']}-{label}-target-",
            )
            for argv in case["target_commands"]
        ]
        constraint = run_command_in_commit(
            repo, candidate["commit"], case["external_acceptance_command"], env,
            case["timeout_seconds"],
            f"repo-evidence-003-{case['case_id']}-{label}-constraint-",
        )
        result[label] = {"target_commands": targets, "acceptance_constraint": constraint}

    result["preconditions"] = {
        "base_acceptance_green": baseline["exit_code"] == 0 and not baseline["timed_out"],
        "noncompliant_functional_target_green": all(
            r["exit_code"] == 0 and not r["timed_out"]
            for r in result["noncompliant"]["target_commands"]
        ),
        "compliant_functional_target_green": all(
            r["exit_code"] == 0 and not r["timed_out"]
            for r in result["compliant"]["target_commands"]
        ),
        "noncompliant_acceptance_red": (
            result["noncompliant"]["acceptance_constraint"]["exit_code"] != 0
            and not result["noncompliant"]["acceptance_constraint"]["timed_out"]
        ),
        "compliant_acceptance_green": (
            result["compliant"]["acceptance_constraint"]["exit_code"] == 0
            and not result["compliant"]["acceptance_constraint"]["timed_out"]
        ),
    }
    result["reproduced"] = all(result["preconditions"].values())
    return result


def evaluate_airlock_candidate(
    repo: Path,
    base: str,
    candidate: dict[str, Any],
    target_commands: list[list[str]],
    protected: list[str],
    timeout: int,
) -> dict[str, Any]:
    item = dict(candidate)
    item["checks"] = []

    protected_check = protected_files_check(candidate["changed_paths"], protected)
    item["checks"].append(protected_check)
    if protected_check["status"] != "PASS":
        item.update({"disposition": "BLOCKED", "reason": "PROTECTED_FILES_CHANGED"})
        return item

    with WorktreeSandbox(repo, candidate["commit"], prefix=f"repo-evidence-003-airlock-{candidate['label']}-") as wt:
        target = run_checks(wt, target_commands, timeout=timeout, kind="target")
        item["checks"].append(target)
        if target["status"] != "PASS":
            item.update({"disposition": "BLOCKED", "reason": "TARGET_FAILED"})
            return item

        # The benchmark supplies no repository acceptance command here.
        # kind=regression invokes only Airlock's frozen product discovery/replay.
        regression = run_checks(wt, [], timeout=timeout, kind="regression")
        item["checks"].append(regression)
        if regression["status"] != "PASS":
            item.update({"disposition": "BLOCKED", "reason": "REPOSITORY_ACCEPTANCE_FAILED"})
            return item

    sufficiency = sufficiency_check(repo, base, candidate["changed_paths"], [], target_commands)
    item["checks"].append(sufficiency)
    if sufficiency["status"] != "PASS":
        item.update({"disposition": "NEEDS_EVIDENCE", "reason": sufficiency["basis"]})
    else:
        item.update({
            "disposition": "SURVIVED",
            "reason": "FUNCTIONAL_AND_REPOSITORY_EVIDENCE_PASSED",
        })
    return item


def classify_pair(noncompliant: dict[str, Any], compliant: dict[str, Any]) -> str:
    n = noncompliant.get("disposition")
    g = compliant.get("disposition")
    withheld = {"BLOCKED", "NEEDS_EVIDENCE"}
    if n in withheld and g == "SURVIVED":
        return "DISCRIMINATED"
    if n == "SURVIVED" and g == "SURVIVED":
        return "UNDERCONSTRAINED"
    if n in withheld and g in withheld:
        return "OVERCONSERVATIVE_OR_INSUFFICIENT"
    if n == "SURVIVED" and g in withheld:
        return "INVERTED"
    return "INCONCLUSIVE"


def aggregate_verdict(case: dict[str, Any], prior: dict[str, Any]) -> str:
    if case.get("status") == "INCONCLUSIVE_INFRASTRUCTURE":
        return "INCONCLUSIVE_INFRASTRUCTURE"
    if case.get("status") == "INCONCLUSIVE_EXTERNAL_TRUTH":
        return "INCONCLUSIVE_EXTERNAL_TRUTH"

    pair = case.get("pair_class")
    if pair == "DISCRIMINATED" and prior.get("validated"):
        return "CUMULATIVE_FOUR_INTERPRETABLE_DISCRIMINATIONS"
    if pair == "UNDERCONSTRAINED":
        return "CURRENT_REPOSITORY_ACCEPTANCE_DISCOVERY_INCOMPLETE"
    if pair == "INVERTED":
        return "CURRENT_REPOSITORY_ACCEPTANCE_GATE_INVERTED"
    if pair == "OVERCONSERVATIVE_OR_INSUFFICIENT":
        return "INCONCLUSIVE_CONSERVATIVE_GATE"
    return "INCONCLUSIVE_INFRASTRUCTURE"


def execute_case(case: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    case_out = out_dir / "case"
    case_out.mkdir(parents=True, exist_ok=True)
    case_root = Path(tempfile.mkdtemp(prefix=f"airlock-{case['case_id']}-"))
    receipt: dict[str, Any] = {
        "schema": "airlock.repo-evidence-003.case.v1",
        "case_id": case["case_id"],
        "repo_id": case["repo_id"],
        "repository": case["repository"],
        "pinned_commit": case["commit"],
        "evidence_note": case["evidence_note"],
    }

    try:
        repo, fetch_records = clone_exact(case, case_root)
        receipt["fetch"] = fetch_records
        receipt["anchors"] = verify_anchors(repo, case)
        base = git(repo, "rev-parse", "HEAD")
        protected = protected_patterns(repo)
        venv = make_venv(case_root)
        env = case_env(venv, case_root)
        receipt["setup"] = setup_case(repo, case_root, case, venv)
        pristine(repo, base)

        with installed_environment(env):
            receipt["airlock_baseline_evidence"] = discover_acceptance_evidence(repo, base)
            candidates = {
                "compliant": create_candidate(repo, base, case, "compliant"),
                "noncompliant": create_candidate(repo, base, case, "noncompliant"),
            }
            receipt["candidates"] = candidates
            receipt["external_truth"] = external_truth(repo, base, candidates, case, env)
            if not receipt["external_truth"]["reproduced"]:
                receipt["status"] = "INCONCLUSIVE_EXTERNAL_TRUTH"
                receipt["pair_class"] = "INCONCLUSIVE"
                write_json(case_out / "case.json", receipt)
                return receipt

            receipt["airlock"] = {
                "noncompliant": evaluate_airlock_candidate(
                    repo, base, candidates["noncompliant"], case["target_commands"],
                    protected, case["timeout_seconds"]
                ),
                "compliant": evaluate_airlock_candidate(
                    repo, base, candidates["compliant"], case["target_commands"],
                    protected, case["timeout_seconds"]
                ),
                "protected_patterns": protected,
            }
            receipt["pair_class"] = classify_pair(
                receipt["airlock"]["noncompliant"], receipt["airlock"]["compliant"]
            )
            receipt["status"] = "EVALUATED"
            write_json(case_out / "case.json", receipt)
            return receipt

    except Exception as exc:
        receipt["status"] = "INCONCLUSIVE_INFRASTRUCTURE"
        receipt["pair_class"] = "INCONCLUSIVE"
        receipt["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback_tail": traceback.format_exc()[-5000:],
        }
        write_json(case_out / "case.json", receipt)
        return receipt
    finally:
        shutil.rmtree(case_root, ignore_errors=True)


def render_markdown(result: dict[str, Any]) -> str:
    case = result["case"]
    truth = "PASS" if (case.get("external_truth") or {}).get("reproduced") else case.get("status", "UNKNOWN")
    airlock = case.get("airlock") or {}
    non = (airlock.get("noncompliant") or {}).get("disposition", "—")
    good = (airlock.get("compliant") or {}).get("disposition", "—")
    lines = [
        "# AIRLOCK-REPO-EVIDENCE-003",
        "",
        f"Verdict: **{result['verdict']}**",
        "",
        f"Frozen prior receipt: **{result['prior_receipt']['verdict']}** "
        f"(3 DISCRIMINATED / 1 INCONCLUSIVE).",
        "",
        "| Fresh case | External truth | Noncompliant | Compliant | Pair |",
        "| --- | --- | --- | --- | --- |",
        f"| {case['case_id']} | {truth} | {non} | {good} | {case.get('pair_class', 'INCONCLUSIVE')} |",
        "",
        "AIRLOCK-REPO-EVIDENCE-002 remains `INCONCLUSIVE_EXTERNAL_TRUTH`; this experiment does not rewrite it.",
        "",
        "The external verifier is ground truth only. It was never supplied to Airlock as a target, regression check, configuration rule, or wrapper hint.",
        "",
        "AIRLOCK-SWE-GATE-001, AIRLOCK-REPO-EVIDENCE-001, and AIRLOCK-REPO-EVIDENCE-002 were not rerun.",
    ]
    return "\n".join(lines) + "\n"


def self_test() -> None:
    prereg = load_preregistration()
    case = prereg["case"]
    assert case["repo_id"] == "significantdigits"
    assert case["external_acceptance_command"][0] == "uvx"
    assert case["external_acceptance_command"] not in case["target_commands"]
    assert classify_pair({"disposition": "BLOCKED"}, {"disposition": "SURVIVED"}) == "DISCRIMINATED"
    assert classify_pair({"disposition": "SURVIVED"}, {"disposition": "SURVIVED"}) == "UNDERCONSTRAINED"
    assert classify_pair({"disposition": "BLOCKED"}, {"disposition": "NEEDS_EVIDENCE"}) == "OVERCONSERVATIVE_OR_INSUFFICIENT"
    assert classify_pair({"disposition": "SURVIVED"}, {"disposition": "BLOCKED"}) == "INVERTED"

    for label in ("compliant", "noncompliant"):
        for op in case["mutations"][label]:
            assert not op["path"].startswith(".github/workflows/")
            assert op["path"] not in {
                "pyproject.toml", "uv.lock", "pytest.ini", ".flake8",
                ".pre-commit-config.yaml", ".pre-commit-config.yml",
            }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    self_test()
    if args.self_test:
        print("AIRLOCK-REPO-EVIDENCE-003 harness self-test: PASS")
        return 0

    if args.output_dir is None:
        parser.error("--output-dir is required unless --self-test is used")

    prereg = load_preregistration()
    prior = verify_prior_receipt(prereg)
    product = verify_product_base(prereg)

    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    case = execute_case(prereg["case"], out_dir)

    result = {
        "schema": "airlock.repo-evidence-003.result.v1",
        "experiment": "AIRLOCK-REPO-EVIDENCE-003",
        "product_under_test": product,
        "prior_receipt": prior,
        "preregistration_sha256": sha256_file(PREREG_PATH),
        "case": case,
    }
    result["verdict"] = aggregate_verdict(case, prior)
    write_json(out_dir / "result.json", result)
    (out_dir / "result.md").write_text(render_markdown(result), encoding="utf-8")
    print(render_markdown(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
