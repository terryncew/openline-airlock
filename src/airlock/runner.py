from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, InvalidOperation
import json
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from .blackboard import coordination_prompt, normalize_findings
from .config import load as load_config
from .discovery import protected_fingerprint, run_baseline
from .gitops import (
    add_worktree,
    changed_paths,
    commit_all,
    ensure_clean,
    git,
    head,
    remove_worktree,
    sanitize_branch,
    tracked_files,
)
from .index import add as index_add
from .providers import resolve_provider
from .verification import ensure_key, sign
from .sandbox import WorktreeSandbox
from .sieve import protected_files_check, run_checks, sufficiency_check
from .util import (
    canonical_json_bytes,
    compact_result,
    expand,
    matches_any,
    run,
    scrub_agent_env,
    sha256_bytes,
    sha256_file,
    worktree_env,
    write_json,
)


def _resolve_prompt(repo: Path, issue_or_prompt: str) -> str:
    try:
        candidate = Path(issue_or_prompt)
        if candidate.exists() and candidate.is_file():
            return candidate.read_text()
    except OSError:
        pass
    if issue_or_prompt.startswith("https://github.com/") and "/issues/" in issue_or_prompt and shutil.which("gh"):
        result = run(["gh", "issue", "view", issue_or_prompt, "--json", "title,body"], repo, timeout=30)
        if result["exit_code"] == 0:
            try:
                obj = json.loads(result["stdout"])
                return f"{obj.get('title','')}\n\n{obj.get('body','')}\n\nSource: {issue_or_prompt}"
            except Exception:
                pass
    return issue_or_prompt


def _agent_report(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text())
    except Exception:
        return {}
    if not isinstance(obj, dict):
        return {}
    keep = {}
    for key in ("reported_cost_usd", "local_checks_passed", "provider", "model"):
        if key in obj:
            keep[key] = obj[key]
    if "local_checks_passed" in keep:
        keep["local_checks_passed"] = bool(keep["local_checks_passed"])
    audit = obj.get("authority_audit")
    if isinstance(audit, dict) and audit.get("schema") == "airlock.hermes-live-001.authority.v1":
        filtered = {
            "schema": audit.get("schema"),
            "worker": audit.get("worker"),
            "exec_interface": audit.get("exec_interface"),
            "forbidden_environment_names_present": list(audit.get("forbidden_environment_names_present") or []),
            "release_authority": audit.get("release_authority"),
            "hermes_home_present": bool(audit.get("hermes_home_present")),
            "hermes_home_path_sha256": audit.get("hermes_home_path_sha256"),
            "github_credential_present": bool(audit.get("github_credential_present")),
            "claim_boundary": audit.get("claim_boundary"),
        }
        keep["authority_audit"] = filtered
        keep["authority_audit_sha256"] = sha256_bytes(canonical_json_bytes(filtered))
    findings = normalize_findings(obj.get("findings"))
    if findings:
        keep["findings"] = findings
    return keep


def _cost_summary(candidates: list[dict]) -> dict:
    total = Decimal("0")
    known = 0
    unknown = 0
    for row in candidates:
        raw = row.get("agent_report", {}).get("reported_cost_usd")
        if raw is None:
            unknown += 1
            continue
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            unknown += 1
            continue
        if value < 0:
            unknown += 1
            continue
        total += value
        known += 1
    return {
        "reported_cost_usd_total": format(total, "f"),
        "known_candidates": known,
        "unknown_candidates": unknown,
        "complete": unknown == 0,
    }


def _test_files(repo: Path, base: str, protected: list[str]) -> list[str]:
    test_patterns = [p for p in protected if p.startswith(("tests/", "test/", "spec/", "__tests__/"))]
    return [path for path in tracked_files(repo, base) if matches_any(path, test_patterns)]


def _create_pr(repo: Path, branch: str, run_id: str, verification_path: Path) -> dict:
    if not shutil.which("gh"):
        return {"status": "NOT_CREATED", "reason": "gh_cli_unavailable"}
    remote = run(["git", "remote", "get-url", "origin"], repo)
    if remote["exit_code"] != 0 or "github.com" not in remote["stdout"]:
        return {"status": "NOT_CREATED", "reason": "origin_is_not_github"}
    push = run(["git", "push", "-u", "origin", branch], repo, env=os.environ.copy(), timeout=120)
    if push["exit_code"] != 0:
        return {"status": "NOT_CREATED", "reason": "push_failed", "stderr_tail": push["stderr"][-1000:]}
    base_branch = run(["git", "symbolic-ref", "refs/remotes/origin/HEAD"], repo)
    base = "main"
    if base_branch["exit_code"] == 0 and "/" in base_branch["stdout"]:
        base = base_branch["stdout"].strip().split("/")[-1]
    body = (
        "Verified by OpenLine Airlock and ready for review.\n\n"
        f"Run: `{run_id}`\n"
        f"Verification: `{verification_path.as_posix()}`\n\n"
        "The verification file records the exact repository checks Airlock observed. "
        "It only covers the checks listed here."
    )
    pr = run([
        "gh", "pr", "create", "--head", branch, "--base", base,
        "--title", f"Airlock ready: {run_id}", "--body", body,
    ], repo, env=os.environ.copy(), timeout=120)
    if pr["exit_code"] != 0:
        return {"status": "NOT_CREATED", "reason": "gh_pr_create_failed", "stderr_tail": pr["stderr"][-1000:]}
    return {"status": "CREATED", "url": pr["stdout"].strip()}


def run_tournament(
    repo: Path,
    issue_or_prompt: str,
    *,
    agents: int,
    models: list[str],
    budget: float | None,
    open_pr: bool,
    config_path: Path,
    coordination: dict | None = None,
) -> dict:
    repo = repo.resolve()
    ensure_clean(repo)
    config = load_config(config_path)
    if agents < 1:
        raise ValueError("--agents must be >= 1")
    if not models:
        models = list(config.get("providers", {}).keys())
    if not models:
        raise RuntimeError("no agent adapters available; configure providers in .airlock/config.json or pass --models")

    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    run_dir = repo / ".airlock" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    prompt = _resolve_prompt(repo, issue_or_prompt)
    prompt_path = run_dir / "prompt.txt"
    prompt_path.write_text(prompt)

    base = head(repo)
    verification = config["verification"]
    baseline = run_baseline(repo, {
        "static": verification.get("static_commands", []),
        "tests": verification.get("test_commands", []),
    }, timeout=int(verification.get("timeout_seconds", 1200)))
    if not baseline["green"]:
        report = {"status": "BASELINE_NOT_GREEN", "baseline": baseline, "run_id": run_id}
        write_json(run_dir / "run.json", report)
        return report

    protected = config["protected_paths"]
    baseline["protected_fingerprint"] = protected_fingerprint(repo, base, protected)
    baseline["config_sha256"] = sha256_file(config_path)
    started = time.monotonic()

    print(f"Agents started: {agents}")
    temp_root = Path(tempfile.mkdtemp(prefix=f"airlock-{run_id}-"))
    entries = []
    roles = list((coordination or {}).get("roles") or [])
    for i in range(agents):
        candidate_id = f"candidate-{i+1:02d}"
        model = models[i % len(models)]
        role = roles[i % len(roles)] if roles else None
        branch = sanitize_branch(f"airlock/{run_id}/{candidate_id}")
        worktree = temp_root / candidate_id
        add_worktree(repo, worktree, branch=branch, commit=base)
        entries.append((candidate_id, model, branch, worktree, role))

    per_agent_budget = None if budget is None else budget / agents

    def generate(entry: tuple[str, str, str, Path, str | None]) -> dict:
        candidate_id, model, branch, worktree, role = entry
        provider = resolve_provider(config, model)
        report_path = run_dir / "agent-reports" / f"{candidate_id}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        candidate_prompt = prompt
        candidate_prompt_path = prompt_path
        if coordination is not None:
            candidate_prompt = coordination_prompt(
                prompt,
                candidate_id=candidate_id,
                role=role or "builder",
                round_number=int(coordination.get("round", 1)),
                total_rounds=int(coordination.get("rounds", 1)),
                blackboard_text=str(coordination.get("blackboard") or "No prior round notes are available."),
            )
            candidate_prompt_path = run_dir / "prompts" / f"{candidate_id}.txt"
            candidate_prompt_path.parent.mkdir(parents=True, exist_ok=True)
            candidate_prompt_path.write_text(candidate_prompt)
        values = {
            "prompt": candidate_prompt,
            "prompt_file": str(candidate_prompt_path),
            "candidate_id": candidate_id,
            "worktree": str(worktree),
            "branch": branch,
            "budget": "" if per_agent_budget is None else f"{per_agent_budget:.6f}",
        }
        argv = expand(provider["command"], values)
        env = worktree_env(
            worktree,
            scrub_agent_env(
                provider.get("pass_env", []),
                home=temp_root / f"{candidate_id}-home",
                extra={
                    "AIRLOCK_CANDIDATE_ID": candidate_id,
                    "AIRLOCK_PROMPT_FILE": str(candidate_prompt_path),
                    "AIRLOCK_AGENT_REPORT": str(report_path),
                    "AIRLOCK_BUDGET_USD": values["budget"],
                    "AIRLOCK_SWARM_ROLE": role or "",
                    "AIRLOCK_SWARM_ROUND": "" if coordination is None else str(coordination.get("round", "")),
                },
            ),
        )
        result = run(argv, worktree, env=env, timeout=int(provider.get("timeout_seconds", 3600)))
        current_branch = run(["git", "branch", "--show-current"], worktree)
        branch_ok = current_branch["exit_code"] == 0 and current_branch["stdout"].strip() == branch
        commit = commit_all(worktree, f"airlock candidate {candidate_id}")
        paths = changed_paths(repo, base, commit) if commit != base else []
        return {
            "candidate_id": candidate_id,
            "model": model,
            "role": role,
            "branch": branch,
            "commit": commit,
            "changed_paths": paths,
            "prompt_sha256": sha256_bytes(candidate_prompt.encode()),
            "branch_integrity": branch_ok,
            "agent_execution": compact_result(result),
            "agent_report": _agent_report(report_path),
        }

    generated = []
    try:
        workers = min(agents, int(config.get("parallelism", min(agents, 4))))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(generate, entry): entry for entry in entries}
            for future in as_completed(futures):
                generated.append(future.result())
        generated.sort(key=lambda row: row["candidate_id"])
    finally:
        for _, _, _, worktree, _ in entries:
            remove_worktree(repo, worktree)
        shutil.rmtree(temp_root, ignore_errors=True)

    test_files = _test_files(repo, base, protected)
    target_commands = verification.get("target_commands", [])
    static_commands = verification.get("static_commands", [])
    test_commands = verification.get("test_commands", [])
    timeout = int(verification.get("timeout_seconds", 1200))

    evaluated = []
    for row in generated:
        item = dict(row)
        item["checks"] = []
        if not row["branch_integrity"]:
            item.update({"disposition": "BLOCKED", "reason": "BRANCH_INTEGRITY"})
            evaluated.append(item); continue
        if row["commit"] == base:
            item.update({"disposition": "BLOCKED", "reason": "NO_PATCH"})
            evaluated.append(item); continue

        protected_check = protected_files_check(row["changed_paths"], protected)
        item["checks"].append(protected_check)
        if protected_check["status"] != "PASS":
            item.update({"disposition": "BLOCKED", "reason": "PROTECTED_FILES_CHANGED"})
            evaluated.append(item); continue

        with WorktreeSandbox(repo, row["commit"], prefix=f"airlock-eval-{row['candidate_id']}-") as wt:
            if target_commands:
                target = run_checks(wt, target_commands, timeout=timeout, kind="target")
                item["checks"].append(target)
                if target["status"] != "PASS":
                    item.update({"disposition": "BLOCKED", "reason": "TARGET_FAILED"})
                    evaluated.append(item); continue

            static = run_checks(wt, static_commands, timeout=timeout, kind="static")
            item["checks"].append(static)
            if static["status"] != "PASS":
                item.update({"disposition": "BLOCKED", "reason": "LINT_OR_TYPECHECK"})
                evaluated.append(item); continue

            regression = run_checks(wt, test_commands, timeout=timeout, kind="regression")
            item["checks"].append(regression)
            if regression["status"] != "PASS":
                item.update({"disposition": "BLOCKED", "reason": "TESTS_FAILED"})
                evaluated.append(item); continue

        sufficiency = sufficiency_check(repo, base, row["changed_paths"], test_files, target_commands)
        item["checks"].append(sufficiency)
        if sufficiency["status"] != "PASS":
            item.update({"disposition": "NEEDS_EVIDENCE", "reason": sufficiency["basis"]})
        else:
            item.update({"disposition": "SURVIVED", "reason": "ALL_CONFIGURED_CHECKS_PASSED"})
        evaluated.append(item)

    survivors = [row for row in evaluated if row["disposition"] == "SURVIVED"]
    ready = survivors[0] if len(survivors) == 1 else None
    if len(survivors) > 1:
        final_status = "MULTIPLE_SURVIVORS"
    elif len(survivors) == 1:
        final_status = "READY"
    else:
        final_status = "NO_PATCH_READY"

    cost = _cost_summary(generated)
    report = {
        "schema": "airlock.run.v1",
        "run_id": run_id,
        "status": final_status,
        "base_commit": base,
        "prompt_sha256": sha256_bytes(prompt.encode()),
        "coordination": None if coordination is None else {
            "schema": coordination.get("schema"),
            "swarm_id": coordination.get("swarm_id"),
            "round": coordination.get("round"),
            "rounds": coordination.get("rounds"),
            "roles": roles,
            "blackboard_sha256": sha256_bytes(str(coordination.get("blackboard") or "").encode()),
        },
        "requested_agents": agents,
        "models": models,
        "budget_usd": budget,
        "baseline": baseline,
        "protected_paths": protected,
        "candidates": evaluated,
        "survivor_count": len(survivors),
        "ready_candidate_id": ready["candidate_id"] if ready else None,
        "cost": cost,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }

    verification_path = None
    pr = None
    if ready:
        ready_branch = sanitize_branch(f"airlock/ready/{run_id}")
        git(repo, "branch", "-f", ready_branch, ready["commit"])
        commands = []
        for check in ready["checks"]:
            commands.extend(check.get("commands", []))
        payload = {
            "schema": "airlock.verification.v1",
            "decision": "READY_FOR_REVIEW",
            "run_id": run_id,
            "base_commit": base,
            "candidate_commit": ready["commit"],
            "candidate_branch": ready_branch,
            "source_candidate_id": ready["candidate_id"],
            "model": ready["model"],
            "changed_paths": ready["changed_paths"],
            "protected_patterns": protected,
            "baseline": baseline,
            "evidence": {
                "commands": commands,
                "coverage_check": next((c for c in ready["checks"] if c.get("rule") == "evidence_sufficiency"), None),
            },
            "config_sha256": sha256_file(config_path),
            "prompt_sha256": ready.get("prompt_sha256", sha256_bytes(prompt.encode())),
            "reported_cost": ready.get("agent_report", {}).get("reported_cost_usd"),
            "what_this_record_means": (
                "This record confirms the exact candidate passed the checks listed here and did not change protected paths. "
                "It only covers the checks listed here."
            ),
        }
        key_path = repo / ".airlock" / "verification.key"
        signed = sign(payload, ensure_key(key_path))
        verification_path = repo / ".airlock" / "records" / f"{run_id}.json"
        write_json(verification_path, signed)
        evidence_hashes = [
            baseline["protected_fingerprint"]["root_sha256"],
            sha256_file(config_path),
            ready.get("prompt_sha256", sha256_bytes(prompt.encode())),
        ] + [r["stdout_sha256"] for r in commands] + [r["stderr_sha256"] for r in commands]
        index_add(repo / ".airlock" / "index.json", str(verification_path.relative_to(repo)), evidence_hashes)
        report["verification_file"] = str(verification_path.relative_to(repo))
        report["ready_branch"] = ready_branch
        if open_pr:
            pr = _create_pr(repo, ready_branch, run_id, verification_path.relative_to(repo))
            report["pull_request"] = pr

    write_json(run_dir / "run.json", report)
    (run_dir / "run.sha256").write_text(sha256_file(run_dir / "run.json") + "\n")

    print(f"Blocked: {sum(r['disposition']=='BLOCKED' for r in evaluated)}")
    print(f"Needs evidence: {sum(r['disposition']=='NEEDS_EVIDENCE' for r in evaluated)}")
    print(f"Survived: {len(survivors)}")
    if ready:
        print(f"Ready for review: {ready['candidate_id']} -> {report['ready_branch']}")
        print(f"Verification record: {report['verification_file']}")
        if pr and pr.get("status") == "CREATED":
            print(f"PR: {pr['url']}")
    elif len(survivors) > 1:
        print("Multiple patches survived. No automatic choice was made.")
    else:
        print("Ready for review: 0")

    if cost["complete"]:
        print(f"Reported spend: ${cost['reported_cost_usd_total']}")
    else:
        print(f"Known reported spend: ${cost['reported_cost_usd_total']} ({cost['unknown_candidates']} candidate(s) unknown)")
    print(f"Elapsed: {report['elapsed_seconds']}s")
    return report
