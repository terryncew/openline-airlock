"""RSI-006-Q observation harness.

Applies one mutant inside an overlay copy of the package (the checkout itself
is never modified) and runs the repository's test suite once in a fresh
subprocess. Records a behavioral observation: per-test outcomes parsed from
--junitxml, compared against the pinned baseline vector.

Timing values are excluded from the record: observation identity is
behavioral, not temporal.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import perturb

RUN_TIMEOUT_S = 120


def parse_junitxml(xml_path: Path) -> dict[str, str]:
    """Map test_id -> outcome in {passed, failed, error, skipped}."""
    outcomes: dict[str, str] = {}
    root = ET.parse(xml_path).getroot()
    for case in root.iter("testcase"):
        classname = case.get("classname", "")
        name = case.get("name", "")
        test_id = f"{classname}::{name}"
        if case.find("skipped") is not None:
            outcomes[test_id] = "skipped"
        elif case.find("failure") is not None:
            outcomes[test_id] = "failed"
        elif case.find("error") is not None:
            outcomes[test_id] = "error"
        else:
            outcomes[test_id] = "passed"
    return outcomes


def run_suite_once(
    import_root: Path,
    tests_dir: Path,
    repo_root: Path,
    work_dir: Path,
    python: str,
) -> dict:
    """Run the suite once; return {outcomes, collection_error, timeout}."""
    xml_path = work_dir / "results.xml"
    cmd = [
        python,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "--tb=no",
        f"--junitxml={xml_path}",
        "--rootdir",
        str(repo_root),
        str(tests_dir),
    ]
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(import_root)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(work_dir),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=RUN_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return {"outcomes": {}, "collection_error": False, "timeout": True}
    if not xml_path.exists():
        return {"outcomes": {}, "collection_error": True, "timeout": False}
    try:
        outcomes = parse_junitxml(xml_path)
    except ET.ParseError:
        return {"outcomes": {}, "collection_error": True, "timeout": False}
    return {
        "outcomes": outcomes,
        "collection_error": False,
        "timeout": False,
        "returncode": proc.returncode,
    }


def compute_kill(result: dict, baseline: dict[str, str]) -> bool:
    """Scoring contract (RSI_006_Q2_SPEC.md): kill is behavioral only.

    kill=True iff the mutant's observed behavior differs from the green
    baseline:
      - the suite run timed out (the baseline completes within the limit;
        the timeout flag is preserved in the record), or
      - at least one test outcome differs, counting tests missing from or
        extra to the baseline set as differences.
    A collection error is NEVER a kill: the suite could not be measured,
    so there is no behavioral observation. Collection errors count only
    against the collection-error sanity bound.
    """
    if result["collection_error"]:
        return False
    if result["timeout"]:
        return True
    outcomes = result["outcomes"]
    for test_id, base_outcome in baseline.items():
        if outcomes.get(test_id, "<missing>") != base_outcome:
            return True
    return bool(set(outcomes) - set(baseline))


def observe_mutant(
    repo_cfg: dict,
    mutant: dict,
    baseline: dict[str, str],
    work_root: Path,
    python: str,
) -> dict:
    """Run one mutant; return the canonical observation record."""
    package_dir = Path(repo_cfg["package_dir"])
    overlay_root = Path(tempfile.mkdtemp(prefix="rsi006q-ov-", dir=str(work_root)))
    overlay_pkg = overlay_root / package_dir.name
    run_dir = Path(tempfile.mkdtemp(prefix="rsi006q-run-", dir=str(work_root)))
    try:
        shutil.copytree(package_dir, overlay_pkg)
        perturb.apply_mutant(package_dir, mutant, overlay_pkg)
        result = run_suite_once(
            overlay_root,
            Path(repo_cfg["tests_dir"]),
            Path(repo_cfg["repo_root"]),
            run_dir,
            python,
        )
    finally:
        shutil.rmtree(overlay_root, ignore_errors=True)
        shutil.rmtree(run_dir, ignore_errors=True)

    outcomes = result["outcomes"]
    kill = compute_kill(result, baseline)

    return {
        "repo": repo_cfg["name"],
        "mutant_id": mutant["mutant_id"],
        "operator": mutant["operator"],
        "site_key": mutant["site_key"],
        "seed": mutant["seed"],
        "outcomes": outcomes,
        "kill": kill,
        "collection_error": result["collection_error"],
        "timeout": result["timeout"],
    }


def observe_baseline(
    repo_cfg: dict, work_root: Path, python: str
) -> dict[str, str]:
    """Run the unmutated suite; return the baseline outcome vector."""
    run_dir = Path(tempfile.mkdtemp(prefix="rsi006q-base-", dir=str(work_root)))
    try:
        result = run_suite_once(
            Path(repo_cfg["import_root"]),
            Path(repo_cfg["tests_dir"]),
            Path(repo_cfg["repo_root"]),
            run_dir,
            python,
        )
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
    if result["collection_error"] or result["timeout"] or not result["outcomes"]:
        raise RuntimeError(
            f"baseline run failed for {repo_cfg['name']}: {result}"
        )
    return result["outcomes"]


def main() -> None:  # pragma: no cover - manual smoke only
    print("observe.py: import ok; use run_rsi_006_q.py --qualify to run", file=sys.stderr)


if __name__ == "__main__":
    main()
