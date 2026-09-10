"""AIRLOCK-GITHUB-AW-001 — cold external comparator, Airlock arm.

The live GitHub Agentic Workflows arm runs separately in a user-owned fork of
the pinned fresh target. This script establishes the frozen pair, external
ground truth, and current unmodified Airlock disposition without supplying
Airlock the hidden ground-truth acceptance command.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from airlock.cli import command_init
from airlock.config import load as load_config
from airlock.discovery import protected_fingerprint
from airlock.gitops import changed_paths, commit_all, head
from airlock.runner import _test_files
from airlock.sandbox import WorktreeSandbox
from airlock.sieve import protected_files_check, run_checks, sufficiency_check
from airlock.util import sha256_file

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]

AIRLOCK_BASE = "fb02207f3ac561368beeabf9ff168076bf828824"
TARGET_REPO = "https://github.com/mrphrazer/binary-ninja-headless-mcp.git"
TARGET_FULL = "mrphrazer/binary-ninja-headless-mcp"
TARGET_SHA = "49c39c2d4427b586ce1ec3499baa86c38f980ece"

PATCHES = {
    "a": HERE / "candidate-a.patch",
    "b": HERE / "candidate-b.patch",
}
PREREG = HERE / "prereg.json"


def run(
    argv: list[str],
    cwd: Path,
    *,
    timeout: int = 1200,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            env=merged,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return {
            "argv": argv,
            "exit_code": proc.returncode,
            "timed_out": False,
            "stdout_tail": proc.stdout[-8000:],
            "stderr_tail": proc.stderr[-8000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "argv": argv,
            "exit_code": 124,
            "timed_out": True,
            "stdout_tail": (exc.stdout or "")[-8000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-8000:] if isinstance(exc.stderr, str) else "",
        }


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clone_target(destination: Path) -> None:
    result = run(
        ["git", "clone", "--no-checkout", "--filter=blob:none", TARGET_REPO, str(destination)],
        REPO_ROOT,
        timeout=300,
    )
    if result["exit_code"] != 0:
        raise RuntimeError(f"target clone failed: {result}")
    fetch = run(["git", "fetch", "origin", TARGET_SHA, "--depth=1"], destination, timeout=300)
    if fetch["exit_code"] != 0:
        raise RuntimeError(f"target fetch failed: {fetch}")
    checkout = run(["git", "checkout", "--detach", TARGET_SHA], destination, timeout=120)
    if checkout["exit_code"] != 0:
        raise RuntimeError(f"target checkout failed: {checkout}")
    run(["git", "config", "user.email", "airlock-github-aw-001@example.invalid"], destination)
    run(["git", "config", "user.name", "AIRLOCK-GITHUB-AW-001"], destination)


def apply_patch(repo: Path, patch: Path) -> dict[str, Any]:
    check = run(["git", "apply", "--check", str(patch)], repo)
    if check["exit_code"] != 0:
        return {"status": "PATCH_APPLY_FAILED", "preflight": check}
    applied = run(["git", "apply", str(patch)], repo)
    if applied["exit_code"] != 0:
        return {"status": "PATCH_APPLY_FAILED", "preflight": check, "apply": applied}
    return {"status": "APPLIED", "preflight": check, "apply": applied}


def functional_oracle(repo: Path) -> dict[str, Any]:
    code = r"""
import base64
from pathlib import Path
from binary_ninja_headless_mcp.backend import BinjaBackend
from binary_ninja_headless_mcp.fake_binja import make_fake_module

backend = BinjaBackend(make_fake_module())
data = base64.b64encode(b"x").decode("ascii")

first = backend.open_session_from_bytes(data, filename="module.exe", update_analysis=False)
first_name = first["filename"]
assert first_name.endswith(".exe"), first_name
assert not first_name.endswith(".module.exe"), first_name
backend.close_session(first["session_id"])

second = backend.open_session_from_bytes(data, filename="hello-from-bytes", update_analysis=False)
second_name = second["filename"]
assert second_name.endswith(".bin"), second_name
backend.close_session(second["session_id"])

print(first_name)
print(second_name)
"""
    return run([sys.executable, "-c", code], repo, env={"BINARY_NINJA_HEADLESS_MCP_FAKE_BACKEND": "1"})


def evaluate_ground_truth(pristine: Path, patch: Path, label: str) -> dict[str, Any]:
    wt = pristine.parent / f"ground-truth-{label}"
    clone = run(["git", "clone", "--shared", str(pristine), str(wt)], pristine.parent)
    if clone["exit_code"] != 0:
        raise RuntimeError(f"ground-truth clone failed: {clone}")
    run(["git", "checkout", "--detach", TARGET_SHA], wt)

    patch_result = apply_patch(wt, patch)
    if patch_result["status"] != "APPLIED":
        return {"label": label, "status": "PATCH_APPLY_FAILED", "patch": patch_result}

    env = {"BINARY_NINJA_HEADLESS_MCP_FAKE_BACKEND": "1"}
    oracle = functional_oracle(wt)
    tests = run(["pytest", "-q"], wt, env=env)
    format_check = run(["ruff", "format", "--check", "."], wt, env=env)
    lint = run(["ruff", "check", "."], wt, env=env)

    return {
        "label": label,
        "status": "EVALUATED",
        "patch_sha256": sha256_path(patch),
        "functional_oracle": oracle,
        "ordinary_tests": tests,
        "preexisting_acceptance": {
            "ruff_format": format_check,
            "ruff_lint": lint,
        },
        "functional_pass": oracle["exit_code"] == 0 and tests["exit_code"] == 0,
        "acceptance_pass": format_check["exit_code"] == 0 and lint["exit_code"] == 0,
    }


def airlock_evaluate_candidate(
    repo: Path,
    base: str,
    patch_path: Path,
    *,
    label: str,
    config: dict[str, Any],
    config_path: Path,
) -> dict[str, Any]:
    protected = list(config.get("protected_paths") or [])
    verification = config.get("verification") or {}
    target_commands = list(verification.get("target_commands") or [])
    static_commands = list(verification.get("static_commands") or [])
    test_commands = list(verification.get("test_commands") or [])
    timeout = int(verification.get("timeout_seconds", 1200))
    test_files = _test_files(repo, base, protected)

    with WorktreeSandbox(repo, base, prefix=f"github-aw-candidate-{label}-") as candidate_wt:
        patch_result = apply_patch(candidate_wt, patch_path)
        if patch_result["status"] != "APPLIED":
            return {
                "label": label,
                "disposition": "INCONCLUSIVE",
                "reason": "PATCH_APPLY_FAILED",
                "patch": patch_result,
            }
        commit = commit_all(candidate_wt, f"AIRLOCK-GITHUB-AW-001 candidate-{label}")
        paths = changed_paths(repo, base, commit)

    item: dict[str, Any] = {
        "label": label,
        "commit": commit,
        "changed_paths": paths,
        "checks": [],
        "config_sha256": sha256_file(config_path),
        "protected_fingerprint": protected_fingerprint(repo, base, protected),
    }

    protected_check = protected_files_check(paths, protected)
    item["checks"].append(protected_check)
    if protected_check["status"] != "PASS":
        item.update({"disposition": "BLOCKED", "reason": "PROTECTED_FILES_CHANGED"})
        return item

    with WorktreeSandbox(repo, commit, prefix=f"github-aw-eval-{label}-") as wt:
        if target_commands:
            target = run_checks(wt, target_commands, timeout=timeout, kind="target")
            item["checks"].append(target)
            if target["status"] != "PASS":
                item.update({"disposition": "BLOCKED", "reason": "TARGET_FAILED"})
                return item

        static = run_checks(wt, static_commands, timeout=timeout, kind="static")
        item["checks"].append(static)
        if static["status"] != "PASS":
            item.update({"disposition": "BLOCKED", "reason": "LINT_OR_TYPECHECK"})
            return item

        regression = run_checks(wt, test_commands, timeout=timeout, kind="regression")
        item["checks"].append(regression)
        if regression["status"] != "PASS":
            basis = regression.get("basis")
            reason = "REPOSITORY_ACCEPTANCE_FAILED" if basis else "TESTS_FAILED"
            item.update({"disposition": "BLOCKED", "reason": reason})
            return item

    sufficiency = sufficiency_check(repo, base, paths, test_files, target_commands)
    item["checks"].append(sufficiency)
    if sufficiency["status"] != "PASS":
        item.update({"disposition": "NEEDS_EVIDENCE", "reason": sufficiency["basis"]})
    else:
        item.update({"disposition": "SURVIVED", "reason": "ALL_REPOSITORY_CHECKS_PASSED"})
    return item


def classify_airlock(a: dict[str, Any], b: dict[str, Any]) -> str:
    withheld = {"BLOCKED", "NEEDS_EVIDENCE"}
    av = a.get("disposition")
    bv = b.get("disposition")
    if av in withheld and bv == "SURVIVED":
        return "AIRLOCK_DISCRIMINATED"
    if av == "SURVIVED" and bv == "SURVIVED":
        return "AIRLOCK_UNDERCONSTRAINED"
    if av in withheld and bv in withheld:
        return "AIRLOCK_OVERCONSERVATIVE_OR_INSUFFICIENT"
    if av == "SURVIVED" and bv in withheld:
        return "AIRLOCK_INVERTED"
    return "AIRLOCK_INCONCLUSIVE"


def source_hashes() -> dict[str, str]:
    paths = [
        ".github/workflows/airlock-github-aw-001.yml",
        "AIRLOCK_GITHUB_AW_001.md",
        "proofs/airlock-github-aw-001/run.py",
        "proofs/airlock-github-aw-001/verify.py",
        "proofs/airlock-github-aw-001/prereg.json",
        "proofs/airlock-github-aw-001/candidate-a.patch",
        "proofs/airlock-github-aw-001/candidate-b.patch",
        "proofs/airlock-github-aw-001/github-aw/airlock-github-aw-001.md",
    ]
    return {path: sha256_path(REPO_ROOT / path) for path in paths}


def reproduce(output: Path) -> dict[str, Any]:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if prereg["airlock_base"] != AIRLOCK_BASE:
        raise AssertionError("Airlock base pin mismatch")
    if prereg["target"]["commit"] != TARGET_SHA:
        raise AssertionError("target pin mismatch")
    for label, patch in PATCHES.items():
        expected = prereg["candidate_hashes"][label]
        if sha256_path(patch) != expected:
            raise AssertionError(f"candidate-{label} hash mismatch")

    target_root = output / "target"
    clone_target(target_root)
    if head(target_root) != TARGET_SHA:
        raise AssertionError("target checkout drifted from preregistered commit")

    # Install the fresh target itself. The experiment workflow supplies only
    # generic pytest + ruff tooling; no candidate-specific acceptance rule.
    install = run([sys.executable, "-m", "pip", "install", "-e", "."], target_root, timeout=300)
    if install["exit_code"] != 0:
        raise RuntimeError(f"target install failed: {install}")

    baseline_tests = run(
        ["pytest", "-q"],
        target_root,
        env={"BINARY_NINJA_HEADLESS_MCP_FAKE_BACKEND": "1"},
    )
    baseline_format = run(["ruff", "format", "--check", "."], target_root)
    baseline_lint = run(["ruff", "check", "."], target_root)
    if any(row["exit_code"] != 0 for row in (baseline_tests, baseline_format, baseline_lint)):
        baseline_failure = {
            "schema": "airlock.github_aw_001.preflight_failure.v1",
            "experiment_id": "AIRLOCK-GITHUB-AW-001",
            "target": {"repository": TARGET_FULL, "commit": TARGET_SHA},
            "acceptance_toolchain": prereg.get("acceptance_toolchain"),
            "baseline": {
                "pytest": baseline_tests,
                "ruff_format": baseline_format,
                "ruff_lint": baseline_lint,
            },
            "status": "INCONCLUSIVE_TARGET_BASELINE_NOT_GREEN",
        }
        (output / "baseline-preflight.json").write_text(
            json.dumps(baseline_failure, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(baseline_failure, sort_keys=True))
        raise RuntimeError(
            "fresh target baseline is not green; see baseline-preflight.json"
        )

    ground_truth = {
        "a": evaluate_ground_truth(target_root, PATCHES["a"], "a"),
        "b": evaluate_ground_truth(target_root, PATCHES["b"], "b"),
    }
    if not ground_truth["a"]["functional_pass"] or not ground_truth["b"]["functional_pass"]:
        raise AssertionError("both frozen candidates must pass functional ground truth")
    if ground_truth["a"]["acceptance_pass"]:
        raise AssertionError("candidate A no longer violates pre-existing acceptance")
    if not ground_truth["b"]["acceptance_pass"]:
        raise AssertionError("candidate B no longer satisfies pre-existing acceptance")

    init_stdout = output / "airlock-init.stdout.txt"
    init_stderr = output / "airlock-init.stderr.txt"
    # command_init prints normal operator output; preserve it for diagnostics.
    # Its generated config is the unmodified current Airlock starter decision.
    old_stdout, old_stderr = sys.stdout, sys.stderr
    try:
        with init_stdout.open("w", encoding="utf-8") as out, init_stderr.open(
            "w", encoding="utf-8"
        ) as err:
            sys.stdout, sys.stderr = out, err
            init_rc = command_init(argparse.Namespace(repo=str(target_root), timeout=1200))
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
    if init_rc != 0:
        result = {
            "schema": "airlock.github_aw_001.airlock_result.v1",
            "experiment_id": "AIRLOCK-GITHUB-AW-001",
            "airlock_base": AIRLOCK_BASE,
            "target": {"repository": TARGET_FULL, "commit": TARGET_SHA},
            "airlock_status": "AIRLOCK_INIT_FAILED",
            "init_exit_code": init_rc,
            "ground_truth": ground_truth,
            "source_sha256": source_hashes(),
        }
        (output / "result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return result

    config_path = target_root / ".airlock" / "config.json"
    config = load_config(config_path)
    base = head(target_root)
    if base != TARGET_SHA:
        raise AssertionError("airlock init changed target base commit")

    airlock_results = {
        "a": airlock_evaluate_candidate(
            target_root,
            base,
            PATCHES["a"],
            label="a",
            config=config,
            config_path=config_path,
        ),
        "b": airlock_evaluate_candidate(
            target_root,
            base,
            PATCHES["b"],
            label="b",
            config=config,
            config_path=config_path,
        ),
    }
    pair_class = classify_airlock(airlock_results["a"], airlock_results["b"])

    result = {
        "schema": "airlock.github_aw_001.airlock_result.v1",
        "experiment_id": "AIRLOCK-GITHUB-AW-001",
        "airlock_base": AIRLOCK_BASE,
        "target": {
            "repository": TARGET_FULL,
            "commit": TARGET_SHA,
        },
        "baseline": {
            "pytest": baseline_tests,
            "ruff_format": baseline_format,
            "ruff_lint": baseline_lint,
        },
        "ground_truth": ground_truth,
        "airlock_config": {
            "protected_paths": list(config.get("protected_paths") or []),
            "verification": config.get("verification") or {},
            "config_sha256": sha256_file(config_path),
        },
        "airlock": airlock_results,
        "airlock_pair_class": pair_class,
        "github_aw_status": "PENDING_LIVE_ARM",
        "source_sha256": source_hashes(),
        "claim_status": "NO_CATEGORY_CLAIM_UNTIL_GITHUB_AW_ARM_COMPLETES",
    }
    (output / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    result = reproduce(Path(args.output).resolve())
    print(
        json.dumps(
            {
                "experiment_id": result["experiment_id"],
                "airlock_status": result.get("airlock_status", "EVALUATED"),
                "airlock_pair_class": result.get("airlock_pair_class"),
                "github_aw_status": result.get("github_aw_status"),
                "claim_status": result.get("claim_status"),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
