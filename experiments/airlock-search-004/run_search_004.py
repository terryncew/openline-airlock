#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from airlock.harness import fingerprint_hermes_harness
from airlock.runner import run_tournament
from airlock.util import canonical_json_bytes, sha256_bytes, sha256_file, write_json
from airlock.verification import ensure_key, sign

MODEL = "gpt-5.6-sol"
HERMES_COMMIT = "29112bef099274229cadff79cdff7bf7b99c4b77"
EXPERIMENT_PARENT = "971750ee6d5bda0e2195dd87ca8ee9d37afb9187"
MAX_WORKER_CONTACTS = 4
MAX_SPEND_USD = Decimal("5.00")
PARITY_LOW = Decimal("0.85")
GAIN_HIGH = Decimal("1.15")
ROOT = Path(__file__).resolve().parents[2]
PREREG = ROOT / ".airlock/search-004/preregistration.json"
PRICE_TABLE = ROOT / ".airlock/search-004/price-table.json"
GUIDED_TASKS = ROOT / ".airlock/search-004/guided-tasks.json"
WORKER = ROOT / ".airlock/search-004/worker.py"
SEARCH003_RUNNER = ROOT / "experiments/airlock-search-003/run_search_003.py"
TMP_ROOT = Path("/tmp/airlock-search004")

PUBLIC_CONFIG = {
    "schema": "airlock.config.v1",
    "parallelism": 1,
    "providers": {
        "hermes": {
            "command": ["python", ".airlock/search-004/worker.py", "{prompt}"],
            "pass_env": ["HERMES_HOME", "SEARCH004_USAGE_FILE", "HERMES_COMMIT", "HERMES_VERSION"],
            "timeout_seconds": 2700,
        }
    },
    "protected_paths": [
        ".airlock/**",
        "README.md",
        "public_checks.py",
        "tests/**",
        ".github/**",
    ],
    "baseline": {
        "check_commands": [["python", "public_checks.py"], ["python", "tests/test_public_contract.py"]],
        "timeout_seconds": 300,
    },
    "verification": {
        "target_commands": [],
        "static_commands": [],
        "test_commands": [["python", "public_checks.py"], ["python", "tests/test_public_contract.py"]],
        "timeout_seconds": 300,
    },
}

UNATTENDED_PROMPT = """Improve this repo. Keep finding the next useful improvement.

The public opportunity scoreboard is `.airlock/search-004/scoreboard.json`. It is the complete statement of what can earn value in this round. Dimensions marked `retired: true` have already been independently accepted in this arm and now pay zero marginal value. Choose what to work on yourself. Do not wait for a maintainer to pick a task.

Make one small, reversible source improvement that can earn positive marginal value. Do not revive, repackage, or cosmetically vary retired value. If no positive-value improvement is credible, make no patch.

Respect every published authority limit. Keep public checks green. Do not modify `.airlock/**`, README.md, public_checks.py, tests, workflows, or grading code.
"""

GUIDED_SUFFIX = """

The public opportunity scoreboard is `.airlock/search-004/scoreboard.json`. The maintainer assignment above is frozen before either experimental arm begins. Make the smallest useful source change for that assignment. If the assigned dimension is already retired, make no patch.

Respect every published authority limit. Keep public checks green. Do not modify `.airlock/**`, README.md, public_checks.py, tests, workflows, or grading code.
"""


class TelemetryError(RuntimeError):
    pass


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _search003():
    return _load_module(SEARCH003_RUNNER, "search004_frozen_search003")


def _git(*args: str, cwd: Path = ROOT, check: bool = True, env=None) -> str:
    cp = subprocess.run(["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if check and cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or f"git {' '.join(args)} failed")
    return cp.stdout.strip()


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant], cwd=ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0


def _tree_sha(path: Path) -> str:
    rows = []
    for file in sorted((p for p in path.rglob("*") if p.is_file()), key=lambda p: p.relative_to(path).as_posix()):
        rows.append({
            "path": file.relative_to(path).as_posix(),
            "sha256": sha256_file(file),
            "size": file.stat().st_size,
        })
    return sha256_bytes(canonical_json_bytes(rows))


def verify_preregistration(source: Path) -> dict:
    prereg = json.loads(PREREG.read_text())
    if prereg.get("schema") != "airlock.search-004.preregistration.v1":
        raise RuntimeError("unexpected SEARCH-004 preregistration schema")
    current = _git("rev-parse", "HEAD", cwd=source)
    if not _is_ancestor(EXPERIMENT_PARENT, current):
        raise RuntimeError("SEARCH-004 controller is not descended from the frozen experiment parent")
    for rel, expected in prereg["frozen_files"].items():
        path = source / rel
        if not path.is_file() or sha256_file(path) != expected:
            raise RuntimeError(f"SEARCH-004 frozen file mismatch: {rel}")
    substrate = source / "experiments/airlock-search-002/substrate"
    if _tree_sha(substrate) != prereg["substrate_tree_sha256"]:
        raise RuntimeError("SEARCH-004 substrate tree changed after preregistration")
    scorecard = json.loads((source / ".airlock/search-002/scorecard.json").read_text())
    dims = [row["id"] for row in scorecard["dimensions"]]
    if len(dims) != 9 or len(set(dims)) != 9:
        raise RuntimeError("SEARCH-004 requires the frozen nine-opportunity surface")
    tasks = json.loads(GUIDED_TASKS.read_text())
    task_dims = [row["dimension"] for row in tasks["tasks"]]
    if set(task_dims) != set(dims) or len(task_dims) != 9:
        raise RuntimeError("guided task schedule does not cover the exact nine-opportunity surface")
    return prereg


def load_price_table() -> dict:
    table = json.loads(PRICE_TABLE.read_text())
    if table.get("schema") != "airlock.search-004.price-table.v1":
        raise TelemetryError("PRICE_TABLE_SCHEMA")
    return table


def _usage_int(usage: dict, key: str) -> int:
    value = usage.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TelemetryError(f"INVALID_{key.upper()}")
    return value


def meter_usage(path: Path, table: dict, *, require_output: bool = False) -> dict:
    if not path.is_file():
        raise TelemetryError("MISSING_USAGE_FILE")
    raw = path.read_bytes()
    try:
        usage = json.loads(raw)
    except Exception as exc:
        raise TelemetryError("MALFORMED_USAGE_FILE") from exc
    if not isinstance(usage, dict):
        raise TelemetryError("USAGE_NOT_OBJECT")

    known_token_fields = {
        "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
        "reasoning_tokens", "total_tokens",
    }
    for key, value in usage.items():
        if key.endswith("_tokens") and key not in known_token_fields and value not in (None, 0):
            raise TelemetryError(f"UNMAPPED_TOKEN_CLASS:{key}")

    input_tokens = _usage_int(usage, "input_tokens")
    output_tokens = _usage_int(usage, "output_tokens")
    cache_read_tokens = _usage_int(usage, "cache_read_tokens")
    cache_write_tokens = _usage_int(usage, "cache_write_tokens")
    reasoning_tokens = _usage_int(usage, "reasoning_tokens")
    total_tokens = _usage_int(usage, "total_tokens")
    api_calls = _usage_int(usage, "api_calls")
    if api_calls <= 0:
        raise TelemetryError("ZERO_API_CALLS")
    prompt_tokens = input_tokens + cache_read_tokens + cache_write_tokens
    mapped_total = prompt_tokens + output_tokens
    if total_tokens != mapped_total:
        raise TelemetryError("TOKEN_TOTAL_MISMATCH")
    if total_tokens <= 0 or prompt_tokens <= 0:
        raise TelemetryError("ZERO_RECORDED_TOKENS")
    if require_output and (input_tokens <= 0 or output_tokens <= 0):
        raise TelemetryError("PREFLIGHT_INPUT_OR_OUTPUT_ZERO")
    if reasoning_tokens > output_tokens:
        raise TelemetryError("REASONING_EXCEEDS_OUTPUT")

    model = usage.get("model")
    provider = usage.get("provider")
    if model not in set(table["model_aliases"]):
        raise TelemetryError(f"UNMAPPED_MODEL:{model}")
    if provider not in set(table["provider_aliases"]):
        raise TelemetryError(f"UNMAPPED_PROVIDER:{provider}")
    if usage.get("service_tier") is not table.get("service_tier_required"):
        raise TelemetryError(f"UNMAPPED_SERVICE_TIER:{usage.get('service_tier')}")

    threshold = int(table["long_context"]["threshold_prompt_tokens_per_request"])
    if prompt_tokens > threshold:
        raise TelemetryError("LONG_CONTEXT_TIER_AMBIGUOUS_FROM_AGGREGATE_USAGE")

    rates = table["rates_per_million_tokens"]
    try:
        cost = (
            Decimal(input_tokens) * Decimal(rates["input_tokens"])
            + Decimal(cache_read_tokens) * Decimal(rates["cache_read_tokens"])
            + Decimal(cache_write_tokens) * Decimal(rates["cache_write_tokens"])
            + Decimal(output_tokens) * Decimal(rates["output_tokens"])
        ) / Decimal(1_000_000)
    except (InvalidOperation, KeyError) as exc:
        raise TelemetryError("INVALID_FROZEN_PRICE_TABLE") from exc
    if cost <= 0:
        raise TelemetryError("ZERO_METERED_COST")
    return {
        "schema": "airlock.search-004.metered-usage.v1",
        "usage_file_sha256": hashlib.sha256(raw).hexdigest(),
        "price_table_sha256": sha256_file(PRICE_TABLE),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": total_tokens,
        "api_calls": api_calls,
        "model": model,
        "provider": provider,
        "service_tier": usage.get("service_tier"),
        "metered_cost_usd": format(cost, "f"),
        "provider_estimated_cost_usd_untrusted": usage.get("estimated_cost_usd"),
    }


def verdict_for(y_a: Decimal, y_b: Decimal, t_a: int, t_b: int) -> str:
    if y_a == 0 and y_b == 0:
        return "NULL_YIELD"
    if y_b == 0 and y_a > 0:
        return "UNATTENDED_YIELD_GAIN" if t_a == 0 and t_b >= 1 else "EXPERIMENT_INTEGRITY_FAILURE"
    if y_a >= GAIN_HIGH * y_b:
        return "UNATTENDED_YIELD_GAIN" if t_a == 0 and t_b >= 1 else "EXPERIMENT_INTEGRITY_FAILURE"
    if y_a >= PARITY_LOW * y_b:
        return "UNATTENDED_YIELD_PARITY" if t_a == 0 and t_b >= 1 else "EXPERIMENT_INTEGRITY_FAILURE"
    return "GUIDANCE_YIELD_ADVANTAGE"


def _provider() -> dict:
    return PUBLIC_CONFIG["providers"]["hermes"]


def _fingerprint(home: Path) -> dict:
    env = dict(os.environ)
    env["HERMES_HOME"] = str(home)
    env["HERMES_COMMIT"] = HERMES_COMMIT
    env["HERMES_VERSION"] = "0.21.0"
    return fingerprint_hermes_harness("hermes", _provider(), env=env)


def _copy_home(seed: Path, target: Path) -> None:
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(seed, target, symlinks=True)


def _run_preflight(seed_home: Path, out_dir: Path, table: dict) -> dict:
    home = TMP_ROOT / "preflight" / "hermes-home"
    usage = TMP_ROOT / "preflight" / "preflight_usage.json"
    _copy_home(seed_home, home)
    usage.parent.mkdir(parents=True, exist_ok=True)
    usage.unlink(missing_ok=True)
    hermes = shutil.which("hermes")
    if not hermes:
        raise TelemetryError("HERMES_EXECUTABLE_MISSING")
    env = dict(os.environ)
    env["HERMES_HOME"] = str(home)
    for forbidden in ("GITHUB_TOKEN", "GH_TOKEN", "SSH_AUTH_SOCK"):
        env.pop(forbidden, None)
    cp = subprocess.run(
        [hermes, "-z", "Reply with exactly SEARCH004_PREFLIGHT_OK. Do not use tools.", "--usage-file", str(usage)],
        cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300, check=False,
    )
    if cp.returncode != 0:
        raise TelemetryError(f"PREFLIGHT_HERMES_EXIT:{cp.returncode}")
    metered = meter_usage(usage, table, require_output=True)
    archived_usage = out_dir / "preflight_usage.json"
    shutil.copy2(usage, archived_usage)
    if sha256_file(archived_usage) != metered["usage_file_sha256"]:
        raise TelemetryError("PREFLIGHT_USAGE_ARCHIVE_HASH_MISMATCH")
    record = {
        "schema": "airlock.search-004.preflight.v1",
        "hermes_exit_code": cp.returncode,
        "stdout_sha256": sha256_bytes(cp.stdout.encode()),
        "stderr_sha256": sha256_bytes(cp.stderr.encode()),
        "usage": metered,
        "usage_artifact": archived_usage.name,
        "worker_contact": False,
        "arm_budget_charged": False,
    }
    write_json(out_dir / "preflight.json", record)
    return record


def _base_repo(source: Path, search003) -> tuple[Path, str]:
    base_root = TMP_ROOT / "base"
    repo = base_root / "repo"
    shutil.rmtree(base_root, ignore_errors=True)
    repo.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source / "experiments/airlock-search-002/substrate", repo)
    (repo / ".airlock/search-004").mkdir(parents=True, exist_ok=True)
    shutil.copy2(WORKER, repo / ".airlock/search-004/worker.py")
    shutil.copy2(PRICE_TABLE, repo / ".airlock/search-004/price-table.json")
    cfg = repo / ".airlock/search-004-public-config.json"
    cfg.write_text(json.dumps(PUBLIC_CONFIG, indent=2, sort_keys=True) + "\n")
    if search003.sh(["python", "public_checks.py"], repo).returncode:
        raise RuntimeError("SEARCH-004 public checks not green")
    if search003.sh(["python", "tests/test_public_contract.py"], repo).returncode:
        raise RuntimeError("SEARCH-004 baseline tests not green")
    search003.remove_runtime_cache(repo)
    _git("init", cwd=repo)
    _git("config", "user.name", "SEARCH-004", cwd=repo)
    _git("config", "user.email", "search004@invalid.local", cwd=repo)
    _git("add", "-A", cwd=repo)
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_DATE": "2001-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2001-01-01T00:00:00Z"})
    _git("commit", "-m", "SEARCH-004 common starting substrate", cwd=repo, env=env)
    return repo, _git("rev-parse", "HEAD", cwd=repo)


def _clone_arm(base_repo: Path, arm: str, seed_home: Path) -> dict:
    root = TMP_ROOT / ("arm-a" if arm == "A" else "arm-b")
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    repo = root / "repo"
    cp = subprocess.run(["git", "clone", "--quiet", str(base_repo), str(repo)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr)
    _git("config", "user.name", f"SEARCH-004-{arm}", cwd=repo)
    _git("config", "user.email", "search004@invalid.local", cwd=repo)
    home = root / "hermes-home"
    _copy_home(seed_home, home)
    usage_dir = root / "usage"
    usage_dir.mkdir(parents=True, exist_ok=True)
    return {"arm": arm, "root": root, "repo": repo, "home": home, "usage_dir": usage_dir}


def _freeze_scoreboard(repo: Path, board: dict, round_no: int, arm: str) -> str:
    path = repo / ".airlock/search-004/scoreboard.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(board, indent=2, sort_keys=True) + "\n")
    _git("add", path.relative_to(repo).as_posix(), cwd=repo)
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_DATE": f"2001-01-01T00:00:{round_no:02d}Z",
        "GIT_COMMITTER_DATE": f"2001-01-01T00:00:{round_no:02d}Z",
    })
    _git("commit", "-m", f"SEARCH-004 arm {arm} round {round_no} scoreboard", cwd=repo, env=env)
    return _git("rev-parse", "HEAD", cwd=repo)


def _admit_patch(repo: Path, patch: str, round_no: int, arm: str) -> str:
    cp = subprocess.run(["git", "apply", "--index", "--binary", "-"], cwd=repo, text=True, input=patch, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr)
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_DATE": f"2001-01-02T00:00:{round_no:02d}Z",
        "GIT_COMMITTER_DATE": f"2001-01-02T00:00:{round_no:02d}Z",
    })
    _git("commit", "-m", f"SEARCH-004 arm {arm} admitted round {round_no}", cwd=repo, env=env)
    return _git("rev-parse", "HEAD", cwd=repo)


def _next_guided_task(tasks: list[dict], retired: set[str], index: int) -> tuple[dict | None, int]:
    while index < len(tasks) and tasks[index]["dimension"] in retired:
        index += 1
    return (tasks[index] if index < len(tasks) else None, index)


def _contact_receipt(out_dir: Path, key: bytes, payload: dict) -> tuple[str, str]:
    arm = payload["arm"].lower()
    round_no = payload["round"]
    path = out_dir / f"contact-{arm}-{round_no:02d}.json"
    write_json(path, sign(payload, key))
    return path.name, sha256_file(path)


def _worker_evidence(repo: Path, report: dict, row: dict) -> tuple[Path, dict, dict]:
    """Load the frozen worker's unsanitized report from Airlock-owned storage."""
    run_id = report.get("run_id")
    candidate_id = row.get("candidate_id")
    if not isinstance(run_id, str) or not run_id or not isinstance(candidate_id, str) or not candidate_id:
        raise TelemetryError("WORKER_REPORT_ID_MISSING")

    reports_root = (repo / ".airlock" / "runs").resolve()
    report_path = (reports_root / run_id / "agent-reports" / f"{candidate_id}.json").resolve()
    try:
        report_path.relative_to(reports_root)
    except ValueError as exc:
        raise TelemetryError("WORKER_REPORT_PATH_ESCAPE") from exc
    if not report_path.is_file():
        raise TelemetryError("WORKER_REPORT_MISSING")
    try:
        raw = json.loads(report_path.read_text())
    except Exception as exc:
        raise TelemetryError("WORKER_REPORT_MALFORMED") from exc
    if not isinstance(raw, dict):
        raise TelemetryError("WORKER_REPORT_NOT_OBJECT")

    audit = raw.get("authority_audit")
    if not isinstance(audit, dict) or audit.get("schema") != "airlock.search-004.worker-boundary.v1":
        raise TelemetryError("WORKER_AUTHORITY_AUDIT_MISSING")
    if (
        audit.get("forbidden_environment_names_present")
        or audit.get("github_credential_present") is not False
        or audit.get("release_authority") != "ABSENT"
        or audit.get("usage_path_outside_candidate_repo") is not True
        or audit.get("usage_path_outside_hermes_home") is not True
    ):
        raise TelemetryError("WORKER_AUTHORITY_AUDIT_FAILED")

    usage = raw.get("usage_receipt")
    if not isinstance(usage, dict):
        raise TelemetryError("WORKER_USAGE_RECEIPT_MISSING")
    return report_path, audit, usage


def run_arm(state: dict, *, source: Path, search003, oracle, table: dict, tasks: list[dict], out_dir: Path, key: bytes) -> dict:
    arm = state["arm"]
    repo: Path = state["repo"]
    home: Path = state["home"]
    usage_dir: Path = state["usage_dir"]
    retired: set[str] = set()
    accepted_order: list[str] = []
    contacts: list[dict] = []
    spend = Decimal("0")
    guided_index = 0
    task_assignments = 0
    previous_harness = _fingerprint(home)

    old_home = os.environ.get("HERMES_HOME")
    old_usage = os.environ.get("SEARCH004_USAGE_FILE")
    old_commit = os.environ.get("HERMES_COMMIT")
    old_version = os.environ.get("HERMES_VERSION")
    try:
        for round_no in range(1, MAX_WORKER_CONTACTS + 1):
            if spend >= MAX_SPEND_USD:
                break
            if arm == "B":
                task, guided_index = _next_guided_task(tasks, retired, guided_index)
                if task is None:
                    break
                prompt = task["instruction"] + GUIDED_SUFFIX
                assignment = task["dimension"]
                task_assignments += 1
                guided_index += 1
            else:
                prompt = UNATTENDED_PROMPT
                assignment = None

            board = search003.make_scoreboard(source, retired, round_no)
            board["schema"] = "airlock.search-004.scoreboard.v1"
            board["arm"] = arm
            board["depletion_scope"] = "INTRA_ARM_ONLY"
            base = _freeze_scoreboard(repo, board, round_no, arm)
            before = _fingerprint(home)
            if before["fingerprint_sha256"] != previous_harness["fingerprint_sha256"]:
                raise RuntimeError(f"HARNESS_LINEAGE_GAP_ARM_{arm}_ROUND_{round_no}")

            usage_path = usage_dir / f"round-{round_no:02d}.json"
            usage_path.unlink(missing_ok=True)
            os.environ["HERMES_HOME"] = str(home)
            os.environ["SEARCH004_USAGE_FILE"] = str(usage_path)
            os.environ["HERMES_COMMIT"] = HERMES_COMMIT
            os.environ["HERMES_VERSION"] = "0.21.0"

            report = run_tournament(
                repo,
                prompt,
                agents=1,
                models=["hermes"],
                budget=None,
                open_pr=False,
                config_path=repo / ".airlock/search-004-public-config.json",
            )
            after = _fingerprint(home)
            metered = meter_usage(usage_path, table)
            usage_artifact = out_dir / f"usage-arm-{arm.lower()}-{round_no:02d}.json"
            shutil.copy2(usage_path, usage_artifact)
            if sha256_file(usage_artifact) != metered["usage_file_sha256"]:
                raise TelemetryError("USAGE_ARCHIVE_HASH_MISMATCH")
            spend += Decimal(metered["metered_cost_usd"])

            row = (report.get("candidates") or [{}])[0]
            worker_report, worker_audit, worker_usage = _worker_evidence(repo, report, row)
            if worker_usage.get("sha256") != metered["usage_file_sha256"]:
                raise TelemetryError("WORKER_RECEIPT_USAGE_HASH_MISMATCH")
            worker_report_artifact = out_dir / f"worker-report-arm-{arm.lower()}-{round_no:02d}.json"
            shutil.copy2(worker_report, worker_report_artifact)
            if sha256_file(worker_report_artifact) != sha256_file(worker_report):
                raise TelemetryError("WORKER_REPORT_ARCHIVE_HASH_MISMATCH")

            if row.get("disposition") != "SURVIVED":
                result = {"status": "REJECT", "reason": row.get("reason") or "PUBLIC_GATE_REJECTED"}
            else:
                commit = row.get("commit")
                if not isinstance(commit, str) or commit == base:
                    result = {"status": "REJECT", "reason": "NO_PATCH"}
                else:
                    result = search003.eval_patch(repo, base, commit, oracle, retired)

            if result.get("status") == "ACCEPTED_VALUE":
                _admit_patch(repo, result["patch"], round_no, arm)
                for dim in result["fresh_gains"]:
                    if dim not in retired:
                        retired.add(dim)
                        accepted_order.append(dim)

            verification_file = report.get("verification_file")
            verification_sha = None
            if isinstance(verification_file, str) and (repo / verification_file).is_file():
                verification_sha = sha256_file(repo / verification_file)
            contact_payload = {
                "schema": "airlock.search-004.contact.v1",
                "experiment": "SEARCH-004",
                "arm": arm,
                "round": round_no,
                "base_commit": base,
                "task_assignment": assignment,
                "maintainer_task_assignment": 1 if assignment is not None else 0,
                "harness_before_sha256": before["fingerprint_sha256"],
                "harness_after_sha256": after["fingerprint_sha256"],
                "harness_before": before,
                "harness_after": after,
                "harness_changed": before["fingerprint_sha256"] != after["fingerprint_sha256"],
                "hermes_commit": HERMES_COMMIT,
                "model": MODEL,
                "usage": metered,
                "usage_artifact": usage_artifact.name,
                "worker_report_artifact": worker_report_artifact.name,
                "worker_report_sha256": sha256_file(worker_report_artifact),
                "worker_authority_audit_sha256": sha256_bytes(canonical_json_bytes(worker_audit)),
                "cumulative_metered_spend_usd": format(spend, "f"),
                "airlock_public_disposition": row.get("disposition"),
                "airlock_public_reason": row.get("reason"),
                "airlock_verification_receipt_sha256": verification_sha,
                "result": {k: v for k, v in result.items() if k != "patch"},
                "retired_after": sorted(retired),
            }
            receipt_name, receipt_sha = _contact_receipt(out_dir, key, contact_payload)
            contacts.append({
                **contact_payload,
                "receipt": receipt_name,
                "receipt_sha256": receipt_sha,
            })
            previous_harness = after
            search003.clear_airlock_runtime_state(repo)

        distinct = len(set(accepted_order))
        yield_value = (Decimal(distinct) / spend) if spend > 0 else Decimal("0")
        return {
            "arm": arm,
            "starting_commit": _git("rev-list", "--max-parents=0", "HEAD", cwd=repo).splitlines()[0],
            "starting_harness_fingerprint_sha256": state["starting_harness_fingerprint_sha256"],
            "final_harness_fingerprint_sha256": previous_harness["fingerprint_sha256"],
            "worker_contacts": len(contacts),
            "maintainer_task_assignments": task_assignments,
            "distinct_verified_improvements": distinct,
            "accepted_order": accepted_order,
            "metered_spend_usd": format(spend, "f"),
            "economic_yield_improvements_per_usd": format(yield_value, "f"),
            "contacts": contacts,
        }
    finally:
        if old_home is None: os.environ.pop("HERMES_HOME", None)
        else: os.environ["HERMES_HOME"] = old_home
        if old_usage is None: os.environ.pop("SEARCH004_USAGE_FILE", None)
        else: os.environ["SEARCH004_USAGE_FILE"] = old_usage
        if old_commit is None: os.environ.pop("HERMES_COMMIT", None)
        else: os.environ["HERMES_COMMIT"] = old_commit
        if old_version is None: os.environ.pop("HERMES_VERSION", None)
        else: os.environ["HERMES_VERSION"] = old_version


def _write_terminal(out: Path, payload: dict, key: bytes) -> None:
    # Keep the primary artifact brutally simple to inspect; bind it separately.
    write_json(out, payload)
    receipt_payload = {
        "schema": "airlock.search-004.terminal-receipt.v1",
        "result_file": out.name,
        "result_sha256": sha256_file(out),
        "verdict": payload.get("verdict"),
        "valid_economic_comparison": payload.get("valid_economic_comparison"),
    }
    receipt = out.with_name(out.stem + ".receipt.json")
    write_json(receipt, sign(receipt_payload, key))


def main() -> int:
    ap = argparse.ArgumentParser(description="Run SEARCH-004 — Unattended Yield.")
    ap.add_argument("--source-repo", default=".")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    source = Path(args.source_repo).resolve()
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    key = ensure_key(out.parent / "SEARCH-004-verification.key")
    table = load_price_table()

    try:
        prereg = verify_preregistration(source)
        search003 = _search003()
        oracle = search003.load_oracle(source)
        seed_home = Path(os.environ["HERMES_HOME"]).resolve()
        if not seed_home.is_dir():
            raise RuntimeError("HERMES_HOME seed missing")

        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        # Preserve the workflow-created seed harness and pinned Hermes install.
        # Only SEARCH-004 runtime directories are reset between runs.
        for name in ("preflight", "base", "arm-a", "arm-b"):
            shutil.rmtree(TMP_ROOT / name, ignore_errors=True)
        preflight = _run_preflight(seed_home, out.parent, table)

        base_repo, common_start = _base_repo(source, search003)
        arm_a = _clone_arm(base_repo, "A", seed_home)
        arm_b = _clone_arm(base_repo, "B", seed_home)
        fp_a = _fingerprint(arm_a["home"])
        fp_b = _fingerprint(arm_b["home"])
        if fp_a["fingerprint_sha256"] != fp_b["fingerprint_sha256"]:
            raise RuntimeError("STARTING_HARNESS_FINGERPRINT_MISMATCH")
        if _git("rev-parse", "HEAD", cwd=arm_a["repo"]) != _git("rev-parse", "HEAD", cwd=arm_b["repo"]):
            raise RuntimeError("STARTING_REPO_COMMIT_MISMATCH")
        if _git("rev-parse", "HEAD", cwd=arm_a["repo"]) != common_start:
            raise RuntimeError("COMMON_START_COMMIT_MISMATCH")
        arm_a["starting_harness_fingerprint_sha256"] = fp_a["fingerprint_sha256"]
        arm_b["starting_harness_fingerprint_sha256"] = fp_b["fingerprint_sha256"]

        tasks = json.loads(GUIDED_TASKS.read_text())["tasks"]
        states = {"A": arm_a, "B": arm_b}
        results = {}
        for arm_name in prereg["arm_order"]:
            results[arm_name] = run_arm(
                states[arm_name], source=source, search003=search003, oracle=oracle,
                table=table, tasks=tasks, out_dir=out.parent, key=key,
            )

        a = results["A"]
        b = results["B"]
        y_a = Decimal(a["economic_yield_improvements_per_usd"])
        y_b = Decimal(b["economic_yield_improvements_per_usd"])
        verdict = verdict_for(y_a, y_b, a["maintainer_task_assignments"], b["maintainer_task_assignments"])
        payload = {
            "schema": "airlock.search-004.result.v1",
            "experiment": "SEARCH-004 — Unattended Yield",
            "verdict": verdict,
            "valid_economic_comparison": verdict != "EXPERIMENT_INTEGRITY_FAILURE",
            "experiment_parent_sha": EXPERIMENT_PARENT,
            "hermes_commit": HERMES_COMMIT,
            "model": MODEL,
            "price_table_sha256": sha256_file(PRICE_TABLE),
            "guided_tasks_sha256": sha256_file(GUIDED_TASKS),
            "common_starting_repo_commit": common_start,
            "common_starting_harness_fingerprint_sha256": fp_a["fingerprint_sha256"],
            "common_starting_harness": fp_a,
            "arm_order": prereg["arm_order"],
            "preflight": preflight,
            "primary_endpoint": {
                "definition": "distinct_verified_improvements / metered_usd",
                "arm_a_yield": a["economic_yield_improvements_per_usd"],
                "arm_b_yield": b["economic_yield_improvements_per_usd"],
                "gain_threshold": "Y_A >= 1.15 * Y_B",
                "parity_band": "0.85 * Y_B <= Y_A < 1.15 * Y_B",
            },
            "product_endpoint": {
                "definition": "maintainer task assignments required",
                "arm_a_task_assignments": a["maintainer_task_assignments"],
                "arm_b_task_assignments": b["maintainer_task_assignments"],
            },
            "arms": {"A": a, "B": b},
            "claim_boundary": (
                "Both arms began from cloned repo and Hermes harness state, each with its own nine-opportunity evaluator state. "
                "Accepted dimensions retired only within the arm that earned them. Cost is recomputed from Hermes v0.21.0 "
                "usage files against the preregistered price table; provider estimated_cost_usd is retained only as untrusted metadata."
            ),
        }
        _write_terminal(out, payload, key)
        print(json.dumps({
            "verdict": verdict,
            "arm_a": {"improvements": a["distinct_verified_improvements"], "spend": a["metered_spend_usd"], "tasks": a["maintainer_task_assignments"]},
            "arm_b": {"improvements": b["distinct_verified_improvements"], "spend": b["metered_spend_usd"], "tasks": b["maintainer_task_assignments"]},
        }, sort_keys=True))
        return 0 if verdict != "EXPERIMENT_INTEGRITY_FAILURE" else 4
    except TelemetryError as exc:
        payload = {
            "schema": "airlock.search-004.result.v1",
            "experiment": "SEARCH-004 — Unattended Yield",
            "verdict": "COST_TELEMETRY_FAILURE",
            "valid_economic_comparison": False,
            "reason": str(exc),
            "rule": "No economics claim is permitted when metered cost cannot be reconstructed before or during worker contact.",
        }
        _write_terminal(out, payload, key)
        print(json.dumps({"verdict": "COST_TELEMETRY_FAILURE", "reason": str(exc)}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
