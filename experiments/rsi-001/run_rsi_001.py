#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any

from airlock.nightshift import run_nightshift
from airlock.verification import sign, verify_signature

try:
    from openline_verified_memory import (
        AIRLOCK_PROMOTION_SCHEMA,
        AIRLOCK_STANDING_SCHEMA,
        EvidenceError,
        derive_airlock_memory,
        established,
        signed_record_sha256,
    )
except ImportError as exc:  # fail closed: the cross-repo verifier is part of the experiment
    raise SystemExit(
        "RSI-001 requires openline-verified-memory pinned to "
        "454c5a3b28f2b7da673f6acf0007fc1d7b6f4d8e"
    ) from exc


AIRLOCK_BASE_COMMIT = "74f24d6a094053b7304b2660c6c8a8b47710fa18"
VERIFIED_MEMORY_COMMIT = "454c5a3b28f2b7da673f6acf0007fc1d7b6f4d8e"
INSTALL_REF = "refs/heads/rsi/installed"
LESSON = {
    "lesson_id": "rsi-001-earned-improvement",
    "title": "Only installed, still-supported improvements are inherited",
    "text": (
        "A unique Nightshift selection is only a candidate memory. Exact receiver-observed "
        "installation earns inheritance; a later receiver REOPEN removes it from the next "
        "generation's established memory without rolling installed code back."
    ),
}


def sh(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    cp = subprocess.run(
        list(args),
        cwd=None if cwd is None else str(cwd),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and cp.returncode != 0:
        raise RuntimeError(
            f"command failed ({cp.returncode}): {' '.join(args)}\n{cp.stderr.strip()}"
        )
    return cp.stdout.strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_receipt(repo: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else repo / path


def memory_dict(generation: dict, key: bytes, promotion: dict | None = None, standing: dict | None = None) -> dict:
    return derive_airlock_memory(
        lesson_id=LESSON["lesson_id"],
        title=LESSON["title"],
        text=LESSON["text"],
        generation_record=generation,
        promotion_record=promotion,
        standing_record=standing,
        key=key,
    ).to_dict()


def build_fixture(root: Path) -> dict[str, str]:
    repo = root / "repo"
    repo.mkdir(parents=True)
    sh("git", "init", "-q", str(repo))
    sh("git", "-C", str(repo), "config", "user.name", "RSI-001")
    sh("git", "-C", str(repo), "config", "user.email", "rsi-001@example.invalid")

    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / ".airlock" / "objectives").mkdir(parents=True)
    (repo / "src" / "value.py").write_text("VALUE = 0\n", encoding="utf-8")
    (repo / "tests" / "check.py").write_text(
        "from src.value import VALUE\n"
        "raise SystemExit(0 if isinstance(VALUE, int) and VALUE >= 0 else 1)\n",
        encoding="utf-8",
    )
    (repo / ".airlock" / "objectives" / "measure.py").write_text(
        "import json\n"
        "from src.value import VALUE\n"
        "print(json.dumps({'value': VALUE}))\n",
        encoding="utf-8",
    )
    objective = {
        "schema": "airlock.objective.v1",
        "name": "RSI-001 fixture value",
        "goal": "Increase fixture value by one without changing the evaluator.",
        "measure": {
            "command": [sys.executable, ".airlock/objectives/measure.py"],
            "direction": "maximize",
            "unit": "points",
            "repeats": 1,
            "timeout_seconds": 30,
            "pass_env": [],
            "protected_evaluator_paths": [".airlock/objectives/measure.py"],
        },
        "bounds": {
            "max_generations": 1,
            "max_changed_files": 1,
            "max_changed_lines": 10,
        },
        "selection": {
            "minimum_gain": "1",
            "complexity_penalty_per_changed_line": "0",
            "minimum_score_gap": "0",
        },
    }
    write_json(repo / ".airlock" / "objective.json", objective)
    config = {
        "schema": "airlock.config.v1",
        "parallelism": 1,
        "protected_paths": ["tests/**", ".github/**", ".airlock/**", "pyproject.toml"],
        "verification": {
            "static_commands": [[sys.executable, "-m", "py_compile", "src/value.py"]],
            "test_commands": [[sys.executable, "tests/check.py"]],
            "target_commands": [[sys.executable, "tests/check.py"]],
            "timeout_seconds": 30,
            "coverage_mode": "changed-module-reference",
        },
        "providers": {
            "hermes": {
                "command": ["hermes", "-z", "{prompt}"],
                "pass_env": ["HERMES_HOME", "OPENROUTER_API_KEY"],
                "timeout_seconds": 30,
            }
        },
        "init_baseline": {"green": True},
    }
    write_json(repo / ".airlock" / "config.json", config)
    (repo / ".gitignore").write_text(
        ".airlock/runs/\n"
        ".airlock/records/\n"
        ".airlock/improvements/\n"
        ".airlock/verification.key\n"
        ".airlock/index.json\n",
        encoding="utf-8",
    )
    sh("git", "add", ".", cwd=repo)
    sh("git", "commit", "-qm", "rsi-001 base", cwd=repo)
    base = sh("git", "rev-parse", "HEAD", cwd=repo)
    sh("git", "branch", "rsi/installed", base, cwd=repo)

    bin_dir = root / "bin"
    bin_dir.mkdir()
    hermes = bin_dir / "hermes"
    hermes.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os\n"
        "from pathlib import Path\n"
        "if os.environ.get('AIRLOCK_RELEASE_AUTHORITY') != 'ABSENT': raise SystemExit(20)\n"
        "if os.environ.get('OPENROUTER_API_KEY') != 'rsi-fixture-secret': raise SystemExit(21)\n"
        "Path('src/value.py').write_text('VALUE = 1\\n')\n"
        "Path(os.environ['AIRLOCK_AGENT_REPORT']).write_text(json.dumps({\n"
        "  'reported_cost_usd': '0.01',\n"
        "  'provider': 'fixture',\n"
        "  'model': 'fake-hermes-rsi-001'\n"
        "}))\n"
        "print('rsi-001 candidate written')\n",
        encoding="utf-8",
    )
    hermes.chmod(hermes.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    hermes_home = root / "hermes-home"
    hermes_home.mkdir()

    state = {
        "repo": str(repo),
        "base_commit": base,
        "install_ref": INSTALL_REF,
        "hermes_executable": str(hermes),
        "hermes_home": str(hermes_home),
        "state_dir": str(root / "state"),
    }
    write_json(root / "state.json", state)
    return state


def phase_select(state_path: Path) -> None:
    state = read_json(state_path)
    repo = Path(state["repo"])
    state_dir = Path(state["state_dir"])
    state_dir.mkdir(parents=True, exist_ok=True)
    hermes = Path(state["hermes_executable"])
    generator_before = sha256_file(hermes)

    report = run_nightshift(
        repo,
        objective_path=".airlock/objective.json",
        generations=1,
        agents=1,
        profiles=[],
        budget=0.10,
    )
    if report.get("accepted_generations") != 1 or report.get("status") != "COMPLETED_LIMIT":
        raise AssertionError(f"Nightshift did not select exactly one winner: {report}")
    if len(report.get("generations", [])) != 1:
        raise AssertionError("expected exactly one generation")

    receipt_path = resolve_receipt(repo, report["generations"][0]["receipt"])
    generation = read_json(receipt_path)
    key = (repo / ".airlock" / "verification.key").read_bytes()
    if not verify_signature(generation, key):
        raise AssertionError("Nightshift generation signature did not verify")

    candidate = memory_dict(generation, key)
    if candidate["status"] != "candidate" or candidate["survived"] != 0:
        raise AssertionError("selection alone incorrectly earned inheritance")

    selected = candidate["selected_commit"]
    target_after_selection = sh("git", "rev-parse", INSTALL_REF, cwd=repo)
    if target_after_selection != state["base_commit"]:
        raise AssertionError("installation ref moved before receiver installation")

    candidate_paths = [
        row.strip()
        for row in sh("git", "diff", "--name-only", f"{state['base_commit']}..{selected}", cwd=repo).splitlines()
        if row.strip()
    ]
    if candidate_paths != ["src/value.py"]:
        raise AssertionError(f"candidate escaped ordinary code path: {candidate_paths}")

    generator_after = sha256_file(hermes)
    if generator_after != generator_before:
        raise AssertionError("Hermes generator executable changed during candidate generation")
    lineage = report.get("run_context", {}).get("harness_lineage", [])
    if not lineage or any(row.get("changed") for row in lineage):
        raise AssertionError("Hermes harness changed during RSI-001")

    result = {
        "phase": "selection",
        "process_pid": os.getpid(),
        "run_id": generation["payload"]["run_id"],
        "generation": generation["payload"]["generation"],
        "generation_record": str(receipt_path),
        "generation_record_sha256": signed_record_sha256(generation),
        "selected_commit": selected,
        "base_commit": state["base_commit"],
        "install_ref": INSTALL_REF,
        "install_ref_after_selection": target_after_selection,
        "candidate_paths": candidate_paths,
        "memory": candidate,
        "next_generation_established_count": len(established([derive_airlock_memory(
            lesson_id=LESSON["lesson_id"],
            title=LESSON["title"],
            text=LESSON["text"],
            generation_record=generation,
            key=key,
        )])),
        "generator_sha256_before": generator_before,
        "generator_sha256_after": generator_after,
        "harness_frozen": True,
        "nightshift_status": report["status"],
        "nightshift_accepted_generations": report["accepted_generations"],
    }
    write_json(state_dir / "selection.json", result)


def phase_install(state_path: Path) -> None:
    state = read_json(state_path)
    repo = Path(state["repo"])
    state_dir = Path(state["state_dir"])
    selected_result = read_json(state_dir / "selection.json")
    generation = read_json(Path(selected_result["generation_record"]))
    key = (repo / ".airlock" / "verification.key").read_bytes()

    # Process restart must reconstruct CANDIDATE from disk, not from volatile state.
    recovered_candidate = memory_dict(generation, key)
    if recovered_candidate["status"] != "candidate":
        raise AssertionError("restart did not reconstruct candidate standing")
    selected = recovered_candidate["selected_commit"]
    before = sh("git", "rev-parse", INSTALL_REF, cwd=repo)
    if before != state["base_commit"]:
        raise AssertionError("installation ref was not still at the frozen base on restart")

    # Negative control: a validly signed receipt for the wrong commit must not earn inheritance.
    wrong_payload = {
        "schema": AIRLOCK_PROMOTION_SCHEMA,
        "run_id": generation["payload"]["run_id"],
        "generation": generation["payload"]["generation"],
        "base_commit": generation["payload"]["base_commit"],
        "generation_receipt_sha256": signed_record_sha256(generation),
        "selected_commit": state["base_commit"],
        "observed_branch_after": selected,
        "status": "INSTALLED",
    }
    wrong_install_rejected = False
    try:
        derive_airlock_memory(
            lesson_id=LESSON["lesson_id"],
            title=LESSON["title"],
            text=LESSON["text"],
            generation_record=generation,
            promotion_record=sign(wrong_payload, key),
            key=key,
        )
    except EvidenceError:
        wrong_install_rejected = True
    if not wrong_install_rejected:
        raise AssertionError("wrong-commit promotion unexpectedly earned inheritance")

    sh("git", "branch", "-f", "rsi/installed", selected, cwd=repo)
    observed = sh("git", "rev-parse", INSTALL_REF, cwd=repo)
    if observed != selected:
        raise AssertionError("receiver did not observe exact selected commit after installation")

    support = state_dir / "support.witness"
    support.write_text("RSI-001 receiver support live\n", encoding="utf-8")
    promotion_payload = {
        "schema": AIRLOCK_PROMOTION_SCHEMA,
        "run_id": generation["payload"]["run_id"],
        "generation": generation["payload"]["generation"],
        "base_commit": generation["payload"]["base_commit"],
        "generation_receipt_sha256": signed_record_sha256(generation),
        "selected_commit": selected,
        "installation_ref": INSTALL_REF,
        "observed_branch_before": before,
        "observed_branch_after": observed,
        "support_witness_sha256": sha256_file(support),
        "status": "INSTALLED",
        "claim_boundary": "Synthetic receiver installation into an isolated fixture ref; not deployment authority.",
    }
    promotion = sign(promotion_payload, key)
    promotion_path = state_dir / "promotion.json"
    write_json(promotion_path, promotion)

    inherited_obj = derive_airlock_memory(
        lesson_id=LESSON["lesson_id"],
        title=LESSON["title"],
        text=LESSON["text"],
        generation_record=generation,
        promotion_record=promotion,
        key=key,
    )
    inherited = inherited_obj.to_dict()
    if inherited["status"] != "inherited" or inherited["survived"] != 1:
        raise AssertionError("exact installation failed to earn inherited standing")
    if len(established([inherited_obj])) != 1:
        raise AssertionError("inherited memory was not available to the next generation")

    result = {
        "phase": "installation",
        "process_pid": os.getpid(),
        "recovered_preinstall_status": recovered_candidate["status"],
        "wrong_install_rejected": wrong_install_rejected,
        "promotion_record": str(promotion_path),
        "promotion_record_sha256": signed_record_sha256(promotion),
        "support_witness": str(support),
        "support_witness_sha256": sha256_file(support),
        "install_ref_before": before,
        "install_ref_after": observed,
        "memory": inherited,
        "next_generation_established_count": len(established([inherited_obj])),
    }
    write_json(state_dir / "installation.json", result)


def phase_reopen(state_path: Path) -> None:
    state = read_json(state_path)
    repo = Path(state["repo"])
    state_dir = Path(state["state_dir"])
    selected_result = read_json(state_dir / "selection.json")
    install_result = read_json(state_dir / "installation.json")
    generation = read_json(Path(selected_result["generation_record"]))
    promotion = read_json(Path(install_result["promotion_record"]))
    key = (repo / ".airlock" / "verification.key").read_bytes()
    support = Path(install_result["support_witness"])
    if support.exists():
        raise AssertionError("REOPEN control requires the support witness to be absent")

    selected = selected_result["selected_commit"]
    before = sh("git", "rev-parse", INSTALL_REF, cwd=repo)
    if before != selected:
        raise AssertionError("installed state moved before standing reevaluation")

    standing_payload = {
        "schema": AIRLOCK_STANDING_SCHEMA,
        "selected_commit": selected,
        "promotion_receipt_sha256": signed_record_sha256(promotion),
        "decision": "REOPEN",
        "reason": "SUPPORT_WITNESS_MISSING",
        "observed_support_witness": "MISSING",
        "installed_state_action": "NONE",
        "claim_boundary": "Synthetic support-loss control; tests propagation of signed REOPEN, not real-world evidence-loss detection.",
    }
    standing = sign(standing_payload, key)
    standing_path = state_dir / "standing.json"
    write_json(standing_path, standing)

    questioned_obj = derive_airlock_memory(
        lesson_id=LESSON["lesson_id"],
        title=LESSON["title"],
        text=LESSON["text"],
        generation_record=generation,
        promotion_record=promotion,
        standing_record=standing,
        key=key,
    )
    questioned = questioned_obj.to_dict()
    after = sh("git", "rev-parse", INSTALL_REF, cwd=repo)
    if questioned["status"] != "questioned":
        raise AssertionError("signed REOPEN did not question inherited memory")
    if questioned["installed_state_action"] != "NONE":
        raise AssertionError("memory standing unexpectedly acquired rollback authority")
    if after != selected:
        raise AssertionError("REOPEN changed installed code")
    if established([questioned_obj]):
        raise AssertionError("questioned memory leaked into next-generation established set")

    result = {
        "phase": "reopen",
        "process_pid": os.getpid(),
        "standing_record": str(standing_path),
        "standing_record_sha256": signed_record_sha256(standing),
        "support_witness_observed": "MISSING",
        "install_ref_before": before,
        "install_ref_after": after,
        "memory": questioned,
        "next_generation_established_count": len(established([questioned_obj])),
    }
    write_json(state_dir / "reopen.json", result)


def run_phase(script: Path, phase: str, state_path: Path, env: dict[str, str]) -> None:
    cp = subprocess.run(
        [sys.executable, str(script), "--phase", phase, "--state", str(state_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    if cp.returncode != 0:
        raise RuntimeError(
            f"RSI-001 phase {phase} failed ({cp.returncode})\nstdout:\n{cp.stdout}\nstderr:\n{cp.stderr}"
        )


def orchestrate(output: Path | None) -> dict:
    root = Path(tempfile.mkdtemp(prefix="airlock-rsi-001-"))
    script = Path(__file__).resolve()
    try:
        state = build_fixture(root)
        state_path = root / "state.json"
        env = dict(os.environ)
        env["PATH"] = str(root / "bin") + os.pathsep + env.get("PATH", "")
        env["HERMES_HOME"] = state["hermes_home"]
        env["OPENROUTER_API_KEY"] = "rsi-fixture-secret"

        run_phase(script, "select", state_path, env)
        selection = read_json(Path(state["state_dir"]) / "selection.json")

        # This is the interruption boundary: the selection process has exited and no
        # promotion receipt exists. Only persisted receiver evidence may cross it.
        promotion_path = Path(state["state_dir"]) / "promotion.json"
        if promotion_path.exists():
            raise AssertionError("promotion receipt existed before restart")

        run_phase(script, "install", state_path, env)
        installation = read_json(Path(state["state_dir"]) / "installation.json")

        support = Path(installation["support_witness"])
        support.unlink()
        run_phase(script, "reopen", state_path, env)
        reopen = read_json(Path(state["state_dir"]) / "reopen.json")

        pids = [selection["process_pid"], installation["process_pid"], reopen["process_pid"]]
        if len(set(pids)) != 3:
            raise AssertionError("phases did not execute across independent processes")

        result = {
            "schema": "airlock.rsi-001.result.v1",
            "verdict": "PASS_RSI_001_EARNED_INHERITANCE",
            "airlock_base_main_commit": AIRLOCK_BASE_COMMIT,
            "verified_memory_commit": VERIFIED_MEMORY_COMMIT,
            "process_restart_proved": True,
            "phase_process_pids": pids,
            "generator_frozen": selection["harness_frozen"],
            "generator_sha256": selection["generator_sha256_before"],
            "candidate_paths": selection["candidate_paths"],
            "selected_commit": selection["selected_commit"],
            "install_ref": INSTALL_REF,
            "states": {
                "after_selection_before_installation": selection["memory"]["status"],
                "after_restart_exact_installation": installation["memory"]["status"],
                "after_support_loss_reopen": reopen["memory"]["status"],
            },
            "next_generation_established_counts": {
                "before_installation": selection["next_generation_established_count"],
                "after_installation": installation["next_generation_established_count"],
                "after_reopen": reopen["next_generation_established_count"],
            },
            "wrong_install_negative_control_rejected": installation["wrong_install_rejected"],
            "installed_state_after_reopen": reopen["install_ref_after"],
            "installed_state_unchanged_by_reopen": reopen["install_ref_before"] == reopen["install_ref_after"],
            "receipt_hashes": {
                "generation": selection["generation_record_sha256"],
                "promotion": installation["promotion_record_sha256"],
                "standing": reopen["standing_record_sha256"],
            },
            "claim_boundary": [
                "Uses fake Hermes through the real Nightshift path; no paid live-Hermes claim.",
                "Does not claim hostile-process isolation; the Hermes profile is not a sandbox.",
                "Installation is an isolated synthetic Git ref, not deployment authority.",
                "Support loss is a controlled missing-witness falsifier; this does not claim automatic detection of arbitrary real-world evidence loss.",
                "RSI-001 tests earned inheritance only. Generator self-modification remains deferred to RSI-002.",
            ],
        }
        if output is not None:
            write_json(output, result)
        return result
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RSI-001 earned-inheritance experiment")
    parser.add_argument("--phase", choices=["select", "install", "reopen"])
    parser.add_argument("--state", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.phase:
        if args.state is None:
            parser.error("--state is required with --phase")
        if args.phase == "select":
            phase_select(args.state)
        elif args.phase == "install":
            phase_install(args.state)
        else:
            phase_reopen(args.state)
        return 0

    result = orchestrate(args.output)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
