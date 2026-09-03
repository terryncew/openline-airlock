from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from . import ci
from .config import load as load_config
from .gitops import add_worktree, changed_paths, commit_all, ensure_clean, git, head, remove_worktree, sanitize_branch
from .providers import resolve_provider
from .sandbox import WorktreeSandbox
from .sieve import protected_files_check, run_checks
from .util import canonical_json_bytes, compact_result, expand, run, scrub_agent_env, sha256_bytes, sha256_file, worktree_env
from .verification import sign, verify_signature

SCHEMA = "airlock.ci.doctor.v1"
MANDATORY_PROTECTED = (".github/**", ".airlock/**")


class CIDoctorError(RuntimeError):
    exit_code = 2


class DoctorNotAuthorized(CIDoctorError):
    exit_code = 2


class DoctorEvidenceIncomplete(CIDoctorError):
    exit_code = 3


def _full_sha(value: Any) -> str | None:
    token = str(value or "").lower()
    if len(token) == 40 and all(ch in "0123456789abcdef" for ch in token):
        return token
    return None


def _receipt_sha(receipt: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(receipt))


def _agent_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text())
    except Exception:
        return {}
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    for key in ("reported_cost_usd", "provider", "model", "local_checks_passed"):
        if key in value:
            out[key] = value[key]
    return out


def _configured_checks(worktree: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    verification = config.get("verification") or {}
    timeout = int(verification.get("timeout_seconds", 1200))
    groups = (
        ("target", verification.get("target_commands", [])),
        ("static", verification.get("static_commands", [])),
        ("regression", verification.get("test_commands", [])),
    )
    return [run_checks(worktree, list(commands or []), timeout=timeout, kind=kind) for kind, commands in groups]


def _has_any_configured_check(config: dict[str, Any]) -> bool:
    verification = config.get("verification") or {}
    return any(bool(verification.get(key)) for key in ("target_commands", "static_commands", "test_commands"))


def _required_reproduction_kinds(payload: dict[str, Any]) -> set[str]:
    mapping = {
        "TEST_FAILURE": "regression",
        "LINT_OR_TYPE_FAILURE": "static",
        "COMPILE_OR_BUILD_FAILURE": "target",
    }
    required: set[str] = set()
    for finding in payload.get("findings", []):
        if not isinstance(finding, dict) or finding.get("role") != "PRIMARY":
            continue
        kind = mapping.get(str(finding.get("reason_code") or ""))
        if kind is None:
            return set()
        required.add(kind)
    return required


def _failed_commands(checks: list[dict[str, Any]], required_kinds: set[str]) -> list[dict[str, Any]]:
    by_kind = {str(group.get("rule")): group for group in checks}
    if not required_kinds or any(by_kind.get(kind, {}).get("status") != "FAIL" for kind in required_kinds):
        return []
    rows: list[dict[str, Any]] = []
    for kind in sorted(required_kinds):
        group = by_kind[kind]
        for command in group.get("commands", []):
            if isinstance(command, dict) and (command.get("exit_code") != 0 or command.get("timed_out")):
                rows.append(command)
    return rows


def _prompt(payload: dict[str, Any], failed: list[dict[str, Any]], protected: list[str]) -> str:
    run_row = payload.get("run") or {}
    findings = [row for row in payload.get("findings", []) if isinstance(row, dict) and row.get("role") == "PRIMARY"]
    lines = [
        "You are Airlock CI Doctor, one isolated code-repair attempt.",
        "A sealed Airlock CI receipt authorized code-repair generation only. It did not authorize merge, deployment, workflow repair, or baseline changes.",
        "",
        f"Repository: {run_row.get('repository')}",
        f"CI run: {run_row.get('run_id')} / attempt {run_row.get('run_attempt')}",
        f"Provider execution SHA: {run_row.get('provider_run_head_sha')}",
        "",
        "Recorder findings:",
    ]
    for finding in findings:
        lines.append(
            f"- {finding.get('job')} :: {finding.get('step')} :: {finding.get('reason_code')} "
            f"({finding.get('rule_id')}) — {finding.get('evidence_summary')}"
        )
    lines.extend(["", "Local reproduction before agent spend:"])
    for row in failed:
        argv = row.get("argv") or []
        lines.append(f"- argv: {json.dumps(argv, ensure_ascii=False)}")
        stdout_tail = str(row.get("stdout_tail") or "").strip()
        stderr_tail = str(row.get("stderr_tail") or "").strip()
        if stdout_tail:
            lines.append(f"  stdout tail: {stdout_tail[-1200:]}")
        if stderr_tail:
            lines.append(f"  stderr tail: {stderr_tail[-1200:]}")
    lines.extend([
        "",
        "Repair the reproduced code failure with the smallest complete change.",
        "Do not modify protected paths, tests, workflow files, Airlock policy, or receipt evidence.",
        "Do not push, merge, open a pull request, rerun GitHub Actions, or change Git configuration.",
        "Airlock will independently rerun the repository's configured checks after you finish.",
        "",
        "Protected paths:",
        *[f"- {path}" for path in protected],
    ])
    return "\n".join(lines) + "\n"


def _load_authorized_receipt(repo: Path, receipt_path: Path) -> tuple[dict[str, Any], bytes, str]:
    key_path = repo / ".airlock" / "verification.key"
    if not key_path.is_file():
        raise DoctorEvidenceIncomplete("local Airlock verification key is missing")
    try:
        receipt = json.loads(receipt_path.read_text())
    except Exception as exc:
        raise DoctorEvidenceIncomplete("CI receipt is not valid JSON") from exc
    if not isinstance(receipt, dict):
        raise DoctorEvidenceIncomplete("CI receipt is not an object")
    key = key_path.read_bytes()
    if not ci.verify_ci_receipt(receipt, key).get("valid"):
        raise DoctorEvidenceIncomplete("CI receipt failed Airlock integrity verification")
    payload = receipt.get("payload") or {}
    authorization = payload.get("authorization") or {}
    if payload.get("disposition") != "CODE_REPAIR_ALLOWED" or authorization.get("code_repair") is not True:
        raise DoctorNotAuthorized("CI receipt does not authorize code repair")
    if authorization.get("retry") is True:
        raise DoctorNotAuthorized("code-repair receipt unexpectedly grants retry authority")
    for forbidden in ("merge", "deployment", "baseline_change", "workflow_repair"):
        if authorization.get(forbidden) is True:
            raise DoctorNotAuthorized(f"CI receipt unexpectedly grants {forbidden} authority")
    primary = [row for row in payload.get("findings", []) if isinstance(row, dict) and row.get("role") == "PRIMARY"]
    if not primary or any(row.get("cause_class") != "CODE_REGRESSION" for row in primary):
        raise DoctorNotAuthorized("sealed primary findings are not exclusively code regressions")
    return receipt, key, _receipt_sha(receipt)


def _repair_base(payload: dict[str, Any]) -> str:
    run_row = payload.get("run") or {}
    if str(run_row.get("event") or "") == "pull_request":
        triggering = _full_sha(run_row.get("triggering_sha"))
        if triggering:
            return triggering
    provider = _full_sha(run_row.get("provider_run_head_sha"))
    if provider:
        return provider
    raise DoctorEvidenceIncomplete("CI receipt does not contain a usable repair-base SHA")


def verify_doctor_receipt(path: Path, key: bytes) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except Exception:
        return {"valid": False, "reason": "JSON"}
    payload = value.get("payload") if isinstance(value, dict) else None
    semantic = (
        isinstance(payload, dict)
        and payload.get("schema") == SCHEMA
        and payload.get("decision") in {"READY_FOR_REVIEW", "NO_LOCAL_REPRODUCTION", "NO_PATCH_READY", "GENERATOR_FAILED"}
        and payload.get("authority", {}).get("merge") is False
        and payload.get("authority", {}).get("deployment") is False
        and payload.get("authority", {}).get("workflow_repair") is False
        and payload.get("authority", {}).get("baseline_change") is False
        and payload.get("authority", {}).get("github_write") is False
        and payload.get("authority", {}).get("retry") is False
        and payload.get("authority", {}).get("code_repair_generation") is True
    )
    signature_ok = verify_signature(value, key) if isinstance(value, dict) else False
    return {"valid": bool(semantic and signature_ok), "signature": signature_ok, "semantics": semantic}


def run_doctor(
    repo: Path,
    receipt_path: Path,
    *,
    model: str,
    budget: float,
    agent_runner: Callable[..., dict[str, Any]] = run,
) -> dict[str, Any]:
    repo = repo.resolve()
    receipt_path = receipt_path.expanduser().resolve()
    if not math.isfinite(budget) or budget <= 0:
        raise DoctorNotAuthorized("--budget must be a positive finite amount")
    ensure_clean(repo)
    config_path = repo / ".airlock" / "config.json"
    if not config_path.is_file():
        raise DoctorEvidenceIncomplete(".airlock/config.json is missing")
    config = load_config(config_path)
    if not _has_any_configured_check(config):
        raise DoctorEvidenceIncomplete("CI Doctor requires at least one configured repository check")

    receipt, key, source_receipt_sha = _load_authorized_receipt(repo, receipt_path)
    payload = receipt["payload"]
    run_row = payload.get("run") or {}
    provider_repo = str(run_row.get("repository") or "")
    local_repo = ci._local_remote_repo(repo)
    if not local_repo or local_repo.casefold() != provider_repo.casefold():
        raise DoctorNotAuthorized("local repository identity does not match the sealed CI receipt")
    base = _repair_base(payload)
    if head(repo).lower() != base:
        raise DoctorNotAuthorized("local HEAD does not match the sealed CI repair base")

    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    run_dir = repo / ".airlock" / "doctor" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    configured_protected = [str(row) for row in config.get("protected_paths", [])]
    protected = list(dict.fromkeys([*configured_protected, *MANDATORY_PROTECTED]))

    with WorktreeSandbox(repo, base, prefix="airlock-doctor-repro-") as baseline_wt:
        baseline_checks = _configured_checks(baseline_wt, config)
    required_kinds = _required_reproduction_kinds(payload)
    failed = _failed_commands(baseline_checks, required_kinds)
    local_reproduction = {
        "status": "REPRODUCED" if failed else "NOT_REPRODUCED",
        "required_kinds": sorted(required_kinds),
        "checks": baseline_checks,
    }

    common = {
        "schema": SCHEMA,
        "doctor_run_id": run_id,
        "source_ci_receipt_path": str(receipt_path),
        "source_ci_receipt_sha256": source_receipt_sha,
        "source_bundle_sha256": payload.get("source_bundle_sha256"),
        "source_canonical_payload_sha256": payload.get("canonical_payload_sha256"),
        "ci_run": {
            "repository": provider_repo,
            "run_id": run_row.get("run_id"),
            "run_attempt": run_row.get("run_attempt"),
            "provider_run_head_sha": run_row.get("provider_run_head_sha"),
            "triggering_sha": run_row.get("triggering_sha"),
            "repair_base": base,
        },
        "config_sha256": sha256_file(config_path),
        "protected_paths": protected,
        "local_reproduction": local_reproduction,
        "model": model,
        "budget_usd": budget,
        "authority": {
            "code_repair_generation": True,
            "retry": False,
            "merge": False,
            "deployment": False,
            "baseline_change": False,
            "workflow_repair": False,
            "github_write": False,
        },
    }

    if not failed:
        signed = sign({**common, "decision": "NO_LOCAL_REPRODUCTION", "worker_started": False, "changed_paths": [], "candidate": None}, key)
        out = run_dir / "doctor.json"
        out.write_bytes(canonical_json_bytes(signed) + b"\n")
        return {"decision": "NO_LOCAL_REPRODUCTION", "worker_started": False, "receipt_path": out, "ready_branch": None}

    provider = resolve_provider(config, model)
    prompt = _prompt(payload, failed, protected)
    prompt_path = run_dir / "prompt.txt"
    prompt_path.write_text(prompt)
    report_path = run_dir / "agent-report.json"
    candidate_branch = sanitize_branch(f"airlock/doctor/{run_id}/candidate-01")
    temp_root = Path(tempfile.mkdtemp(prefix="airlock-doctor-worker-"))
    worktree = temp_root / "candidate-01"
    add_worktree(repo, worktree, branch=candidate_branch, commit=base)
    git_config_path = repo / ".git" / "config"
    git_config_sha = sha256_file(git_config_path)
    try:
        values = {
            "prompt": prompt,
            "prompt_file": str(prompt_path),
            "candidate_id": "doctor-01",
            "worktree": str(worktree),
            "branch": candidate_branch,
            "budget": f"{budget:.6f}",
        }
        argv = expand(provider["command"], values)
        env = worktree_env(
            worktree,
            scrub_agent_env(
                provider.get("pass_env", []),
                home=temp_root / "home",
                extra={
                    "AIRLOCK_CANDIDATE_ID": "doctor-01",
                    "AIRLOCK_PROMPT_FILE": str(prompt_path),
                    "AIRLOCK_AGENT_REPORT": str(report_path),
                    "AIRLOCK_BUDGET_USD": values["budget"],
                    "AIRLOCK_CI_RECEIPT_SHA256": source_receipt_sha,
                    "AIRLOCK_DOCTOR_MODE": "1",
                },
            ),
        )
        result = agent_runner(argv, worktree, env=env, timeout=int(provider.get("timeout_seconds", 3600)))
        branch_ok = git(worktree, "branch", "--show-current") == candidate_branch
        git_config_ok = git_config_path.is_file() and sha256_file(git_config_path) == git_config_sha
        candidate_commit = commit_all(worktree, "airlock ci doctor candidate") if branch_ok and git_config_ok else base
        paths = changed_paths(repo, base, candidate_commit) if candidate_commit != base else []
    finally:
        remove_worktree(repo, worktree)
        import shutil
        shutil.rmtree(temp_root, ignore_errors=True)

    agent_execution = compact_result(result)
    agent_report = _agent_report(report_path)
    decision = "NO_PATCH_READY"
    reason = "NO_PATCH"
    candidate_checks: list[dict[str, Any]] = []
    ready_branch: str | None = None

    if result.get("exit_code") != 0 or result.get("timed_out"):
        decision, reason = "GENERATOR_FAILED", "GENERATOR_FAILED"
    elif not branch_ok:
        reason = "BRANCH_INTEGRITY"
    elif not git_config_ok:
        reason = "GIT_CONFIG_CHANGED"
    elif candidate_commit == base:
        reason = "NO_PATCH"
    else:
        protected_check = protected_files_check(paths, protected)
        candidate_checks.append(protected_check)
        if protected_check.get("status") != "PASS":
            reason = "PROTECTED_FILES_CHANGED"
        else:
            with WorktreeSandbox(repo, candidate_commit, prefix="airlock-doctor-eval-") as eval_wt:
                candidate_checks.extend(_configured_checks(eval_wt, config))
            if all(row.get("status") == "PASS" for row in candidate_checks):
                decision, reason = "READY_FOR_REVIEW", "REPRODUCED_FAILURE_REPAIRED"
                ready_branch = sanitize_branch(f"airlock/doctor-ready/{run_id}")
                git(repo, "branch", "-f", ready_branch, candidate_commit)
            else:
                reason = "CONFIGURED_CHECKS_FAILED"

    body = {
        **common,
        "decision": decision,
        "reason": reason,
        "worker_started": True,
        "prompt_sha256": sha256_bytes(prompt.encode()),
        "agent_execution": agent_execution,
        "agent_report": agent_report,
        "candidate": {
            "candidate_id": "doctor-01",
            "commit": candidate_commit,
            "branch": candidate_branch,
            "ready_branch": ready_branch,
        },
        "changed_paths": paths,
        "candidate_checks": candidate_checks,
        "what_this_record_means": (
            "A sealed CI receipt authorized one isolated code-repair generation. Airlock reproduced at least one configured failure before spend, "
            "kept protected paths outside the candidate's authority, and independently evaluated the candidate. This record grants no merge, deployment, workflow-repair, or baseline authority."
        ),
    }
    signed = sign(body, key)
    out = run_dir / "doctor.json"
    out.write_bytes(canonical_json_bytes(signed) + b"\n")
    (run_dir / "doctor.sha256").write_text(sha256_file(out) + "\n")
    if not verify_doctor_receipt(out, key).get("valid"):
        raise DoctorEvidenceIncomplete("CI Doctor receipt failed local integrity verification")

    # Candidate branches are implementation scratch. Only an admitted ready branch survives.
    try:
        git(repo, "branch", "-D", candidate_branch)
    except Exception:
        pass

    return {
        "decision": decision,
        "reason": reason,
        "worker_started": True,
        "receipt_path": out,
        "ready_branch": ready_branch,
        "candidate_commit": candidate_commit,
        "changed_paths": paths,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="airlock doctor",
        description="Generate one isolated repair only from a sealed CODE_REPAIR_ALLOWED CI receipt.",
    )
    parser.add_argument("receipt", help="Canonical Airlock CI receipt JSON")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--model", default="hermes")
    parser.add_argument("--budget", type=float, required=True, help="Maximum agent budget for this one repair attempt")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_doctor(Path(args.repo), Path(args.receipt), model=args.model, budget=args.budget)
    except CIDoctorError as exc:
        print(f"ERROR: {ci._safe_error_text(exc)}", file=os.sys.stderr)
        return exc.exit_code
    except Exception as exc:
        print(f"ERROR: {ci._safe_error_text(exc)}", file=os.sys.stderr)
        return 3

    print("Airlock CI Doctor")
    print(f"Decision: {result['decision']}")
    print(f"Worker started: {'YES' if result['worker_started'] else 'NO'}")
    if result.get("ready_branch"):
        print(f"Ready for review: {result['ready_branch']}")
    else:
        print("Ready for review: 0")
    print(f"Doctor receipt: {result['receipt_path']}")
    print("GitHub write authority: NO")
    print("Merge authority: NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
