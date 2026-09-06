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


def run(
    argv: list[str],
    cwd: Path,
    *,
    env: dict[str, str] | None = None,
    timeout: int = 900,
) -> dict[str, Any]:
    return compact_result(airlock_run(argv, cwd, env=env, timeout=timeout))


def git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()


def git(repo: Path, *args: str, timeout: int = 300) -> str:
    result = airlock_run(["git", *args], repo, timeout=timeout)
    if result["exit_code"] != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {result['stderr'][-2000:]}"
        )
    return result["stdout"].strip()


def pristine(repo: Path, base: str) -> None:
    git(repo, "checkout", "--detach", base)
    git(repo, "reset", "--hard", base)
    git(repo, "clean", "-fdx")


def load_preregistration() -> dict[str, Any]:
    data = json.loads(PREREG_PATH.read_text())
    if data.get("experiment") != "AIRLOCK-REPO-EVIDENCE-002":
        raise RuntimeError("wrong preregistration experiment")
    cases = data.get("cases", [])
    if len(cases) != 4:
        raise RuntimeError("preregistration must contain exactly four cases")
    case_ids = [case["case_id"] for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise RuntimeError("duplicate case id")
    repo_ids = {case["repo_id"] for case in cases}
    excluded = set(data["freshness"]["excluded_airlock_swe_gate_001_repo_ids"])
    excluded |= set(data["freshness"]["excluded_airlock_repo_evidence_001_repo_ids"])
    overlap = sorted(repo_ids & excluded)
    if overlap:
        raise RuntimeError(f"freshness exclusion violated: {overlap}")
    return data


def verify_product_base(prereg: dict[str, Any]) -> dict[str, Any]:
    expected = prereg["airlock_product_base"]
    observed = git(AIRLOCK_ROOT, "rev-parse", "HEAD")
    product = {
        "expected_base": expected,
        "observed_head": observed,
        "preregistration_sha256": sha256_file(PREREG_PATH),
        "component_sha256": {
            path: sha256_file(AIRLOCK_ROOT / path) for path in PRODUCT_PATHS
        },
    }
    diff = airlock_run(
        [
            "git",
            "diff",
            "--exit-code",
            expected,
            "HEAD",
            "--",
            "src/airlock",
            "src/airlock_submit",
            "pyproject.toml",
        ],
        AIRLOCK_ROOT,
        timeout=120,
    )
    product["product_diff_exit_code"] = diff["exit_code"]
    if diff["exit_code"] != 0:
        raise RuntimeError(
            "experiment branch changed frozen product paths: "
            + diff["stdout"][-1000:]
            + diff["stderr"][-1000:]
        )
    return product


def clone_exact(case: dict[str, Any], root: Path) -> tuple[Path, list[dict[str, Any]]]:
    repo = root / "repo"
    repo.mkdir(parents=True)
    records = []
    records.append(run(["git", "init", "-q"], repo, timeout=120))
    records.append(
        run(
            ["git", "remote", "add", "origin", f"https://github.com/{case['repository']}.git"],
            repo,
            timeout=120,
        )
    )
    records.append(
        run(
            [
                "git",
                "-c",
                "protocol.version=2",
                "fetch",
                "--no-tags",
                "--depth=1",
                "origin",
                case["commit"],
            ],
            repo,
            timeout=600,
        )
    )
    if any(record["exit_code"] != 0 for record in records):
        raise RuntimeError("upstream fetch failed")
    records.append(run(["git", "checkout", "--detach", "FETCH_HEAD"], repo, timeout=120))
    if records[-1]["exit_code"] != 0:
        raise RuntimeError("upstream checkout failed")
    observed = git(repo, "rev-parse", "HEAD")
    if observed != case["commit"]:
        raise RuntimeError(
            f"commit mismatch: expected {case['commit']} observed {observed}"
        )
    git(repo, "config", "user.name", "Airlock Repo Evidence")
    git(repo, "config", "user.email", "airlock-repo-evidence@example.invalid")
    return repo, records


def verify_anchors(repo: Path, case: dict[str, Any]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for rel, expected in case["anchors"].items():
        path = repo / rel
        if not path.is_file():
            raise RuntimeError(f"anchor missing: {rel}")
        digest = git_blob_sha(path)
        observed[rel] = digest
        if digest != expected:
            raise RuntimeError(
                f"anchor drift {rel}: expected {expected} observed {digest}"
            )
    return observed


def make_venv(case_root: Path) -> Path:
    venv = case_root / "venv"
    proc = subprocess.run(
        [sys.executable, "-m", "venv", str(venv)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"venv creation failed: {proc.stderr[-2000:]}")
    return venv


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def venv_bin(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin")


def case_env(venv: Path, case_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = str(venv_bin(venv)) + os.pathsep + env.get("PATH", "")
    env["VIRTUAL_ENV"] = str(venv)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PRE_COMMIT_HOME"] = str(case_root / "pre-commit-cache")
    env["PDM_IGNORE_SAVED_PYTHON"] = "1"
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


def setup_case(
    repo: Path,
    case_root: Path,
    case: dict[str, Any],
    venv: Path,
) -> list[dict[str, Any]]:
    env = case_env(venv, case_root)
    records = []
    bootstrap = run(
        [str(venv_python(venv)), "-m", "pip", "install", "--upgrade", "pip"],
        repo,
        env=env,
        timeout=600,
    )
    records.append(bootstrap)
    if bootstrap["exit_code"] != 0 or bootstrap["timed_out"]:
        raise RuntimeError("pip bootstrap failed")

    for raw in case["setup_commands"]:
        argv = expand_setup(raw, venv)
        record = run(argv, repo, env=env, timeout=case["timeout_seconds"])
        records.append(record)
        if record["exit_code"] != 0 or record["timed_out"]:
            raise RuntimeError(f"setup command failed: {argv}")

    tracked = run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        repo,
        env=env,
        timeout=120,
    )
    records.append(tracked)
    if tracked["exit_code"] != 0 or tracked["stdout_tail"].strip():
        raise RuntimeError(
            "setup changed tracked repository state: " + tracked["stdout_tail"]
        )
    return records


def apply_operations(repo: Path, operations: list[dict[str, Any]]) -> None:
    for op in operations:
        path = repo / op["path"]
        text = path.read_text(encoding="utf-8")
        if op["op"] == "replace":
            old = op["old"]
            count = text.count(old)
            if count != 1:
                raise RuntimeError(
                    f"mutation needle count for {op['path']} is {count}, expected 1"
                )
            path.write_text(text.replace(old, op["new"], 1), encoding="utf-8")
        elif op["op"] == "append":
            path.write_text(text + op["text"], encoding="utf-8")
        else:
            raise RuntimeError(f"unsupported mutation op {op['op']!r}")


def create_candidate(
    repo: Path,
    base: str,
    case: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    pristine(repo, base)
    apply_operations(repo, case["mutations"][label])
    status = git(repo, "status", "--porcelain")
    if not status.strip():
        raise RuntimeError(f"{label} mutation created no change")
    git(repo, "add", "-A")
    git(
        repo,
        "commit",
        "--no-gpg-sign",
        "-m",
        f"AIRLOCK-REPO-EVIDENCE-002 {case['case_id']} {label}",
    )
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
            [
                str((wt / "src").resolve()),
                str(wt.resolve()),
                candidate_env.get("PYTHONPATH", ""),
            ]
        ).rstrip(os.pathsep)
        result = airlock_run(
            argv,
            wt,
            env=candidate_env,
            timeout=timeout,
        )
        return compact_result(result)


def external_truth(
    repo: Path,
    base: str,
    candidates: dict[str, dict[str, Any]],
    case: dict[str, Any],
    env: dict[str, str],
) -> dict[str, Any]:
    # AIRLOCK-REPO-EVIDENCE-001 taught us that a candidate pair is not useful
    # if the nominally compliant verifier was already red on the frozen base.
    # Prove that precondition first.
    baseline_constraint = run_command_in_commit(
        repo,
        base,
        case["external_acceptance_command"],
        env,
        case["timeout_seconds"],
        f"repo-evidence-002-{case['case_id']}-base-constraint-",
    )

    result: dict[str, Any] = {
        "base_acceptance_constraint": baseline_constraint,
    }
    for label in ("noncompliant", "compliant"):
        candidate = candidates[label]
        target_records = []
        for argv in case["target_commands"]:
            target_records.append(
                run_command_in_commit(
                    repo,
                    candidate["commit"],
                    argv,
                    env,
                    case["timeout_seconds"],
                    f"repo-evidence-002-{case['case_id']}-{label}-target-",
                )
            )
        constraint = run_command_in_commit(
            repo,
            candidate["commit"],
            case["external_acceptance_command"],
            env,
            case["timeout_seconds"],
            f"repo-evidence-002-{case['case_id']}-{label}-constraint-",
        )
        result[label] = {
            "target_commands": target_records,
            "acceptance_constraint": constraint,
        }

    base_green = (
        baseline_constraint["exit_code"] == 0
        and not baseline_constraint["timed_out"]
    )
    non_target_ok = all(
        row["exit_code"] == 0 and not row["timed_out"]
        for row in result["noncompliant"]["target_commands"]
    )
    good_target_ok = all(
        row["exit_code"] == 0 and not row["timed_out"]
        for row in result["compliant"]["target_commands"]
    )
    bad_constraint = result["noncompliant"]["acceptance_constraint"]
    good_constraint = result["compliant"]["acceptance_constraint"]

    result["preconditions"] = {
        "base_acceptance_green": base_green,
        "noncompliant_functional_target_green": non_target_ok,
        "compliant_functional_target_green": good_target_ok,
        "noncompliant_acceptance_red": (
            bad_constraint["exit_code"] != 0 and not bad_constraint["timed_out"]
        ),
        "compliant_acceptance_green": (
            good_constraint["exit_code"] == 0 and not good_constraint["timed_out"]
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

    with WorktreeSandbox(
        repo,
        candidate["commit"],
        prefix=f"repo-evidence-002-airlock-{candidate['label']}-",
    ) as wt:
        target = run_checks(
            wt,
            target_commands,
            timeout=timeout,
            kind="target",
        )
        item["checks"].append(target)
        if target["status"] != "PASS":
            item.update({"disposition": "BLOCKED", "reason": "TARGET_FAILED"})
            return item

        # Deliberately empty. The benchmark does not give Airlock the external
        # verifier. kind=regression invokes the frozen product's own
        # repository-owned acceptance discovery/replay machinery.
        regression = run_checks(
            wt,
            [],
            timeout=timeout,
            kind="regression",
        )
        item["checks"].append(regression)
        if regression["status"] != "PASS":
            item.update(
                {
                    "disposition": "BLOCKED",
                    "reason": "REPOSITORY_ACCEPTANCE_FAILED",
                }
            )
            return item

    sufficiency = sufficiency_check(
        repo,
        base,
        candidate["changed_paths"],
        [],
        target_commands,
    )
    item["checks"].append(sufficiency)
    if sufficiency["status"] != "PASS":
        item.update(
            {
                "disposition": "NEEDS_EVIDENCE",
                "reason": sufficiency["basis"],
            }
        )
    else:
        item.update(
            {
                "disposition": "SURVIVED",
                "reason": "FUNCTIONAL_AND_REPOSITORY_EVIDENCE_PASSED",
            }
        )
    return item


def classify_pair(
    noncompliant: dict[str, Any],
    compliant: dict[str, Any],
) -> str:
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


def aggregate_verdict(cases: list[dict[str, Any]]) -> str:
    if any(case.get("status") == "INCONCLUSIVE_INFRASTRUCTURE" for case in cases):
        return "INCONCLUSIVE_INFRASTRUCTURE"
    if any(case.get("status") == "INCONCLUSIVE_EXTERNAL_TRUTH" for case in cases):
        return "INCONCLUSIVE_EXTERNAL_TRUTH"

    classes = [case.get("pair_class") for case in cases]
    if "UNDERCONSTRAINED" in classes:
        return "CURRENT_REPOSITORY_ACCEPTANCE_DISCOVERY_INCOMPLETE"
    if "INVERTED" in classes:
        return "CURRENT_REPOSITORY_ACCEPTANCE_GATE_INVERTED"
    if classes and all(value == "DISCRIMINATED" for value in classes):
        return "REPOSITORY_ACCEPTANCE_DISCRIMINATION_EARNED"
    if "OVERCONSERVATIVE_OR_INSUFFICIENT" in classes:
        return "INCONCLUSIVE_CONSERVATIVE_GATE"
    return "INCONCLUSIVE_INFRASTRUCTURE"


def execute_case(
    case: dict[str, Any],
    out_dir: Path,
) -> dict[str, Any]:
    case_out = out_dir / "cases" / case["case_id"]
    case_out.mkdir(parents=True, exist_ok=True)
    case_root = Path(tempfile.mkdtemp(prefix=f"airlock-{case['case_id']}-"))
    receipt: dict[str, Any] = {
        "schema": "airlock.repo-evidence-002.case.v1",
        "case_id": case["case_id"],
        "repo_id": case["repo_id"],
        "repository": case["repository"],
        "pinned_commit": case["commit"],
        "evidence_note": case.get("evidence_note"),
        "encoded_repository_command": case.get("encoded_repository_command"),
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
            # Observational receipt only. The harness never supplies these
            # discovered commands back to Airlock; evaluate_airlock_candidate
            # invokes the product code independently.
            receipt["airlock_baseline_evidence"] = discover_acceptance_evidence(
                repo,
                base,
            )

            candidates = {
                "compliant": create_candidate(repo, base, case, "compliant"),
                "noncompliant": create_candidate(repo, base, case, "noncompliant"),
            }
            receipt["candidates"] = candidates
            receipt["external_truth"] = external_truth(
                repo,
                base,
                candidates,
                case,
                env,
            )

            if not receipt["external_truth"]["reproduced"]:
                receipt["status"] = "INCONCLUSIVE_EXTERNAL_TRUTH"
                receipt["pair_class"] = "INCONCLUSIVE"
                write_json(case_out / "case.json", receipt)
                return receipt

            receipt["airlock"] = {
                "noncompliant": evaluate_airlock_candidate(
                    repo,
                    base,
                    candidates["noncompliant"],
                    case["target_commands"],
                    protected,
                    case["timeout_seconds"],
                ),
                "compliant": evaluate_airlock_candidate(
                    repo,
                    base,
                    candidates["compliant"],
                    case["target_commands"],
                    protected,
                    case["timeout_seconds"],
                ),
                "protected_patterns": protected,
            }
            receipt["pair_class"] = classify_pair(
                receipt["airlock"]["noncompliant"],
                receipt["airlock"]["compliant"],
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
    lines = [
        "# AIRLOCK-REPO-EVIDENCE-002",
        "",
        f"Verdict: **{result['verdict']}**",
        "",
        "| Case | External truth | Noncompliant | Compliant | Pair |",
        "| --- | --- | --- | --- | --- |",
    ]
    for case in result["cases"]:
        truth = (
            "PASS"
            if (case.get("external_truth") or {}).get("reproduced")
            else case.get("status", "UNKNOWN")
        )
        airlock = case.get("airlock") or {}
        non = (airlock.get("noncompliant") or {}).get("disposition", "—")
        good = (airlock.get("compliant") or {}).get("disposition", "—")
        lines.append(
            f"| {case['case_id']} | {truth} | {non} | {good} | "
            f"{case.get('pair_class', 'INCONCLUSIVE')} |"
        )
    lines.extend(
        [
            "",
            "The external verifier is ground truth only. It was never supplied "
            "to Airlock as a target, regression check, or benchmark rule.",
            "",
            "The harness ran every frozen case even if an earlier pair already "
            "falsified the aggregate claim.",
            "",
            "AIRLOCK-SWE-GATE-001 and AIRLOCK-REPO-EVIDENCE-001 were not rerun.",
        ]
    )
    return "\n".join(lines) + "\n"


def self_test() -> None:
    prereg = load_preregistration()
    assert prereg["airlock_product_base"]
    assert classify_pair(
        {"disposition": "BLOCKED"}, {"disposition": "SURVIVED"}
    ) == "DISCRIMINATED"
    assert classify_pair(
        {"disposition": "NEEDS_EVIDENCE"}, {"disposition": "SURVIVED"}
    ) == "DISCRIMINATED"
    assert classify_pair(
        {"disposition": "SURVIVED"}, {"disposition": "SURVIVED"}
    ) == "UNDERCONSTRAINED"
    assert classify_pair(
        {"disposition": "BLOCKED"}, {"disposition": "NEEDS_EVIDENCE"}
    ) == "OVERCONSERVATIVE_OR_INSUFFICIENT"
    assert classify_pair(
        {"disposition": "SURVIVED"}, {"disposition": "BLOCKED"}
    ) == "INVERTED"

    for case in prereg["cases"]:
        external = case["external_acceptance_command"]
        assert external not in case["target_commands"]
        # Mutations are source-only. None can rewrite the repository-owned judge.
        for label in ("compliant", "noncompliant"):
            for op in case["mutations"][label]:
                assert not op["path"].startswith(".github/workflows/")
                assert op["path"] not in {
                    "pyproject.toml",
                    ".flake8",
                    ".pre-commit-config.yaml",
                    ".pre-commit-config.yml",
                }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    self_test()
    if args.self_test:
        print("AIRLOCK-REPO-EVIDENCE-002 harness self-test: PASS")
        return 0

    if args.output_dir is None:
        parser.error("--output-dir is required unless --self-test is used")

    prereg = load_preregistration()
    product = verify_product_base(prereg)
    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    cases = []
    for case in prereg["cases"]:
        print(f"[AIRLOCK-REPO-EVIDENCE-002] {case['case_id']}", flush=True)
        cases.append(execute_case(case, out_dir))

    result = {
        "schema": "airlock.repo-evidence-002.result.v1",
        "experiment": "AIRLOCK-REPO-EVIDENCE-002",
        "product_under_test": product,
        "preregistration_sha256": sha256_file(PREREG_PATH),
        "cases": cases,
    }
    result["pair_class_counts"] = {
        value: sum(
            1 for case in cases if case.get("pair_class") == value
        )
        for value in (
            "DISCRIMINATED",
            "UNDERCONSTRAINED",
            "OVERCONSERVATIVE_OR_INSUFFICIENT",
            "INVERTED",
            "INCONCLUSIVE",
        )
    }
    result["verdict"] = aggregate_verdict(cases)

    write_json(out_dir / "result.json", result)
    (out_dir / "result.md").write_text(
        render_markdown(result),
        encoding="utf-8",
    )
    print(render_markdown(result), end="")

    # Negative and preregistered inconclusive scientific results are completed
    # experiment outputs. Only an uncaught harness/global-integrity failure
    # should make the workflow itself red.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
