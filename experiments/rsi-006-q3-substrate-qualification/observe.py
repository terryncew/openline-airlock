"""RSI-006-Q3 observation harness.

Same behavioral semantics as the RSI-006-Q2 harness (byte-identical
scoring: a mutant is killed on collection error, timeout, an outcome
difference, a missing baseline test, or an extra test; collection errors
independently count against the sanity bound). What changed for Q3 is
launch observability: every suite launch preserves its exact argv,
interpreter, cwd, environment identity, exit status, stdout, stderr,
JUnit report (when produced), and start/end timestamps.
``collection_error`` remains a disposition only; the underlying
command/output/report is always preserved alongside it.

The canonical observation record keeps exactly the Q2 shape
(repo, mutant_id, operator, site_key, seed, outcomes, kill,
collection_error, timeout): launch evidence travels as a sidecar, never
inside the canonical bytes the discovery seal covers.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

RUN_TIMEOUT_S = 120


class LaunchError(RuntimeError):
    """A baseline launch failed; carries the full launch record."""

    def __init__(self, message: str, launch: dict):
        super().__init__(message)
        self.launch = launch


def parse_junitxml_bytes(data: bytes) -> dict[str, str]:
    """Map test_id -> outcome in {passed, failed, error, skipped}."""
    outcomes: dict[str, str] = {}
    root = ET.fromstring(data)
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


def _env_fingerprint(env: dict[str, str]) -> str:
    blob = "\x00".join(f"{k}={v}" for k, v in sorted(env.items()))
    return hashlib.sha256(blob.encode("utf-8", errors="replace")).hexdigest()


def _encode_bytes(data: bytes) -> dict:
    """Byte-exact encoding of captured output.

    ``bytes_b64`` is the exact byte record (base64); ``sha256``/``len``
    bind it; ``text`` is a lossy human-readable decoding (errors
    replaced) and must never be treated as the evidence bytes.
    """
    import base64

    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "len": len(data),
        "text": data.decode("utf-8", errors="replace"),
        "bytes_b64": base64.b64encode(data).decode("ascii"),
    }


def _launch_record(
    cmd: list[str],
    python: str,
    work_dir: Path,
    env: dict[str, str],
    overrides: dict[str, str],
    start_ts: float,
    end_ts: float,
    exit_status: int | None,
    stdout_b: bytes,
    stderr_b: bytes,
    junit_bytes: bytes | None,
    disposition: str,
    child_pid: int | None = None,
) -> dict:
    return {
        "argv": list(cmd),
        "interpreter": python,
        "cwd": str(work_dir),
        "env_overrides": dict(overrides),
        "env_fingerprint": _env_fingerprint(env),
        "child_pid": child_pid,
        "exit_status": exit_status,
        # Byte-exact stdout/stderr: the b64 payload is the evidence;
        # "text" is a lossy convenience decoding.
        "stdout": _encode_bytes(stdout_b),
        "stderr": _encode_bytes(stderr_b),
        # The JUnit report bytes are preserved here as a sidecar: the
        # run directory is deleted after the launch, so without this the
        # report would be hash-without-bytes.
        "junit_xml": _encode_bytes(junit_bytes)
        if junit_bytes is not None
        else None,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "duration_s": round(end_ts - start_ts, 3),
        "disposition": disposition,
    }


def run_suite_once(
    import_root: Path,
    tests_dir: Path,
    repo_root: Path,
    work_dir: Path,
    python: str,
    on_process_start: "Callable[[int], None] | None" = None,
) -> dict:
    """Run the suite once.

    Returns {outcomes, collection_error, timeout, launch} where ``launch``
    is the full launch-evidence record. Scoring inputs (outcomes,
    collection_error, timeout) have identical semantics to RSI-006-Q2.

    ``on_process_start`` is the authorization-consumption hook: when not
    None it is called with the child pid immediately after the suite
    subprocess has actually started (``subprocess.Popen`` returned). Only
    the mutant path (``observe_mutant``) passes it; the baseline path
    never does, so environment qualification cannot consume scientific
    authorization. A spawn failure (``OSError``) never reaches the hook.
    """
    start_ts = time.time()
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
    overrides = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(import_root)}
    env.update(overrides)
    try:
        # Popen, not run: the process-start boundary must be observable.
        # The contact hook fires only after this returns, i.e. only once
        # the OS has actually spawned the suite subprocess.
        proc = subprocess.Popen(
            cmd,
            cwd=str(work_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as oe:
        # The interpreter itself could not be launched (missing binary,
        # permission denied, ...). This is the Q2 failure mode generalized:
        # a disposition with the underlying error preserved, never a bare
        # "collection_error". No process started, so the contact hook is
        # not fired.
        end_ts = time.time()
        err_b = f"suite launch failed to spawn: {oe}".encode("utf-8")
        launch = _launch_record(
            cmd, python, work_dir, env, overrides, start_ts, end_ts,
            None, b"", err_b, None, "launch_spawn_failed",
            child_pid=None,
        )
        return {"outcomes": {}, "collection_error": True, "timeout": False,
                "launch": launch}
    child_pid = proc.pid
    if on_process_start is not None:
        try:
            on_process_start(child_pid)
        except BaseException:
            # The hook failed after the process actually started, so the
            # authorization is consumed; reap the child so a hook defect
            # cannot strand a suite subprocess, then propagate.
            proc.kill()
            proc.communicate()
            raise
    try:
        stdout_b, stderr_b = proc.communicate(timeout=RUN_TIMEOUT_S)
        exit_status: int | None = proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout_b, stderr_b = proc.communicate()
        end_ts = time.time()
        launch = _launch_record(
            cmd, python, work_dir, env, overrides, start_ts, end_ts,
            None, stdout_b, stderr_b, None, "timeout",
            child_pid=child_pid,
        )
        return {"outcomes": {}, "collection_error": False, "timeout": True,
                "launch": launch}
    end_ts = time.time()
    junit_bytes = xml_path.read_bytes() if xml_path.exists() else None
    if junit_bytes is None:
        launch = _launch_record(
            cmd, python, work_dir, env, overrides, start_ts, end_ts,
            exit_status, stdout_b, stderr_b, None,
            "collection_error_no_junitxml",
            child_pid=child_pid,
        )
        return {"outcomes": {}, "collection_error": True, "timeout": False,
                "launch": launch}
    try:
        outcomes = parse_junitxml_bytes(junit_bytes)
    except ET.ParseError:
        launch = _launch_record(
            cmd, python, work_dir, env, overrides, start_ts, end_ts,
            exit_status, stdout_b, stderr_b, junit_bytes,
            "collection_error_unparseable_junitxml",
            child_pid=child_pid,
        )
        return {"outcomes": {}, "collection_error": True, "timeout": False,
                "launch": launch}
    launch = _launch_record(
        cmd, python, work_dir, env, overrides, start_ts, end_ts,
        exit_status, stdout_b, stderr_b, junit_bytes, "ok",
        child_pid=child_pid,
    )
    return {
        "outcomes": outcomes,
        "collection_error": False,
        "timeout": False,
        "returncode": proc.returncode,
        "launch": launch,
    }


def observe_mutant(
    repo_cfg: dict,
    mutant: dict,
    baseline: dict[str, str],
    work_root: Path,
    python: str,
    on_process_start: "Callable[[int], None] | None" = None,
) -> dict:
    """Run one mutant.

    Returns {"record": canonical observation record (Q2 shape),
    "launch": launch-evidence record}. The mutant generator is imported
    lazily so that Stage 1 (environment qualification), which only needs
    untouched-suite launches, never loads the mutation substrate.

    ``on_process_start`` is forwarded to ``run_suite_once``: the contact
    gate hook, fired only after the mutant-observation subprocess has
    actually started.
    """
    import perturb  # lazy: keeps Stage 1 free of the mutation substrate

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
            on_process_start=on_process_start,
        )
    finally:
        shutil.rmtree(overlay_root, ignore_errors=True)
        shutil.rmtree(run_dir, ignore_errors=True)

    outcomes = result["outcomes"]
    kill = bool(result["collection_error"] or result["timeout"])
    if not kill:
        for test_id, base_outcome in baseline.items():
            if outcomes.get(test_id, "<missing>") != base_outcome:
                kill = True
                break
        else:
            # Any test not in the baseline also counts as a behavior change.
            if set(outcomes) - set(baseline):
                kill = True

    record = {
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
    return {"record": record, "launch": result["launch"]}


def observe_baseline(
    repo_cfg: dict, work_root: Path, python: str
) -> tuple[dict[str, str], dict]:
    """Run the unmutated suite; return (baseline outcome vector, launch).

    Raises LaunchError (carrying the full launch record) when the launch
    fails to produce a usable outcome vector.
    """
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
        raise LaunchError(
            f"baseline run failed for {repo_cfg['name']}: "
            f"disposition={result['launch']['disposition']} "
            f"exit_status={result['launch']['exit_status']}",
            result["launch"],
        )
    return result["outcomes"], result["launch"]


def main() -> None:  # pragma: no cover - manual smoke only
    print("observe.py: import ok; use run_rsi_006_q3.py --qualify to run",
          file=sys.stderr)


if __name__ == "__main__":
    main()
