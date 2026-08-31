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
from .receipt import ensure_key, sign
from .sandbox import WorktreeSandbox
from .sieve import protected_surface_check, run_checks, sufficiency_check
from .util import compact_result, expand, matches_any, run, scrub_agent_env, sha256_bytes, sha256_file, write_json


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


def _create_pr(repo: Path, branch: str, run_id: str, proof_path: Path) -> dict:
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
        "Admitted by OpenLine Airlock.\n\n"
        f"Run: `{run_id}`\n"
        f"Proof: `{proof_path.as_posix()}`\n\n"
        "The proof records the exact repository checks Airlock observed. "
        "It does not claim semantic correctness outside those checks."
    )
    pr = run([
        "gh", "pr", "create", "--head", branch, "--base", base,
        "--title", f"Airlock survivor: {run_id}", "--body", body,
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

    print(f"[outer chamber]  {agents} agents dispatched")
    temp_root = Path(tempfile.mkdtemp(prefix=f"airlock-{run_id}-"))
    entries = []
    for i in range(agents):
        candidate_id = f"candidate-{i+1:02d}"
        model = models[i % len(models)]
        branch = sanitize_branch(f"airlock/{run_id}/{candidate_id}")
        worktree = temp_root / candidate_id
        add_worktree(repo, worktree, branch=branch, commit=base)
        entries.append((candidate_id, model, branch, worktree))

    per_agent_budget = None if budget is None else budget / agents

    def generate(entry: tuple[str, str, str, Path]) -> dict:
        candidate_id, model, branch, worktree = entry
        provider = resolve_provider(config, model)
        report_path = run_dir / "agent-reports" / f"{candidate_id}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        values = {
            "prompt": prompt,
            "prompt_file": str(prompt_path),
            "candidate_id": candidate_id,
            "worktree": str(worktree),
            "branch": branch,
            "budget": "" if per_agent_budget is None else f"{per_agent_budget:.6f}",
        }
        argv = expand(provider["command"], values)
        env = scrub_agent_env(
            provider.get("pass_env", []),
            home=temp_root / f"{candidate_id}-home",
            extra={
                "AIRLOCK_CANDIDATE_ID": candidate_id,
                "AIRLOCK_PROMPT_FILE": str(prompt_path),
                "AIRLOCK_AGENT_REPORT": str(report_path),
                "AIRLOCK_BUDGET_USD": values["budget"],
            },
        )
        result = run(argv, worktree, env=env, timeout=int(provider.get("timeout_seconds", 3600)))
        current_branch = run(["git", "branch", "--show-current"], worktree)
        branch_ok = current_branch["exit_code"] == 0 and current_branch["stdout"].strip() == branch
        commit = commit_all(worktree, f"airlock candidate {candidate_id}")
        paths = changed_paths(repo, base, commit) if commit != base else []
        return {
            "candidate_id": candidate_id,
            "model": model,
            "branch": branch,
            "commit": commit,
            "changed_paths": paths,
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
        for _, _, _, worktree in entries:
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
            item.update({"disposition": "PURGED", "reason": "BRANCH_INTEGRITY"})
            evaluated.append(item); continue
        if row["commit"] == base:
            item.update({"disposition": "PURGED", "reason": "NO_PATCH"})
            evaluated.append(item); continue

        protected_check = protected_surface_check(row["changed_paths"], protected)
        item["checks"].append(protected_check)
        if protected_check["status"] != "PASS":
            item.update({"disposition": "PURGED", "reason": "PROTECTED_SURFACE"})
            evaluated.append(item); continue

        with WorktreeSandbox(repo, row["commit"], prefix=f"airlock-eval-{row['candidate_id']}-") as wt:
            if target_commands:
                target = run_checks(wt, target_commands, timeout=timeout, kind="target")
                item["checks"].append(target)
                if target["status"] != "PASS":
                    item.update({"disposition": "PURGED", "reason": "TARGET_FAILED"})
                    evaluated.append(item); continue

            static = run_checks(wt, static_commands, timeout=timeout, kind="static")
            item["checks"].append(static)
            if static["status"] != "PASS":
                item.update({"disposition": "PURGED", "reason": "STATIC_INVARIANT"})
                evaluated.append(item); continue

            regression = run_checks(wt, test_commands, timeout=timeout, kind="regression")
            item["checks"].append(regression)
            if regression["status"] != "PASS":
                item.update({"disposition": "PURGED", "reason": "REGRESSION"})
                evaluated.append(item); continue

        sufficiency = sufficiency_check(repo, base, row["changed_paths"], test_files, target_commands)
        item["checks"].append(sufficiency)
        if sufficiency["status"] != "PASS":
            item.update({"disposition": "INSUFFICIENT_EVIDENCE", "reason": sufficiency["basis"]})
        else:
            item.update({"disposition": "SURVIVED", "reason": "ALL_DECLARED_INVARIANTS_PASSED"})
        evaluated.append(item)

    survivors = [row for row in evaluated if row["disposition"] == "SURVIVED"]
    admitted = survivors[0] if len(survivors) == 1 else None
    if len(survivors) > 1:
        final_status = "MULTIPLE_SURVIVORS"
    elif len(survivors) == 1:
        final_status = "ADMITTED"
    else:
        final_status = "NO_PATCH_ADMITTED"

    cost = _cost_summary(generated)
    report = {
        "schema": "airlock.run.v1",
        "run_id": run_id,
        "status": final_status,
        "base_commit": base,
        "prompt_sha256": sha256_bytes(prompt.encode()),
        "requested_agents": agents,
        "models": models,
        "budget_usd": budget,
        "baseline": baseline,
        "protected_paths": protected,
        "candidates": evaluated,
        "survivor_count": len(survivors),
        "admitted_candidate_id": admitted["candidate_id"] if admitted else None,
        "cost": cost,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }

    proof_path = None
    pr = None
    if admitted:
        admitted_branch = sanitize_branch(f"airlock/admitted/{run_id}")
        git(repo, "branch", "-f", admitted_branch, admitted["commit"])
        commands = []
        for check in admitted["checks"]:
            commands.extend(check.get("commands", []))
        payload = {
            "schema": "airlock.proof.v1",
            "decision": "ADMITTED",
            "run_id": run_id,
            "base_commit": base,
            "candidate_commit": admitted["commit"],
            "candidate_branch": admitted_branch,
            "source_candidate_id": admitted["candidate_id"],
            "model": admitted["model"],
            "changed_paths": admitted["changed_paths"],
            "protected_patterns": protected,
            "baseline": baseline,
            "evidence": {
                "commands": commands,
                "sufficiency": next((c for c in admitted["checks"] if c.get("rule") == "evidence_sufficiency"), None),
            },
            "config_sha256": sha256_file(config_path),
            "prompt_sha256": sha256_bytes(prompt.encode()),
            "reported_cost": admitted.get("agent_report", {}).get("reported_cost_usd"),
            "claim_boundary": (
                "This receipt proves the exact candidate passed the recorded frozen checks and protected-path boundary. "
                "It does not prove behavior outside those checks."
            ),
        }
        key_path = repo / ".airlock" / "receipt.key"
        signed = sign(payload, ensure_key(key_path))
        proof_path = repo / ".airlock" / "proofs" / f"{run_id}.json"
        write_json(proof_path, signed)
        evidence_hashes = [
            baseline["protected_fingerprint"]["root_sha256"],
            sha256_file(config_path),
            sha256_bytes(prompt.encode()),
        ] + [r["stdout_sha256"] for r in commands] + [r["stderr_sha256"] for r in commands]
        index_add(repo / ".airlock" / "index.json", str(proof_path.relative_to(repo)), evidence_hashes)
        report["proof"] = str(proof_path.relative_to(repo))
        report["admitted_branch"] = admitted_branch
        if open_pr:
            pr = _create_pr(repo, admitted_branch, run_id, proof_path.relative_to(repo))
            report["pull_request"] = pr

    write_json(run_dir / "run.json", report)
    (run_dir / "run.sha256").write_text(sha256_file(run_dir / "run.json") + "\n")

    print(f"[decontaminate]  {sum(r['disposition']=='PURGED' for r in evaluated)} candidates purged")
    print(f"[decontaminate]  {sum(r['disposition']=='INSUFFICIENT_EVIDENCE' for r in evaluated)} candidates held for insufficient evidence")
    print(f"[inner chamber]  {len(survivors)} candidate(s) cleared declared invariants")
    if admitted:
        print(f"[inner chamber]  admitted {admitted['candidate_id']} -> {report['admitted_branch']}")
        print(f"Proof: {report['proof']}")
        if pr and pr.get("status") == "CREATED":
            print(f"PR: {pr['url']}")
    elif len(survivors) > 1:
        print("[inner chamber]  no automatic admission: multiple survivors require human choice")
    else:
        print("[inner chamber]  0 patches admitted")

    if cost["complete"]:
        print(f"Reported spend: ${cost['reported_cost_usd_total']}")
    else:
        print(f"Known reported spend: ${cost['reported_cost_usd_total']} ({cost['unknown_candidates']} candidate(s) unknown)")
    print(f"Elapsed: {report['elapsed_seconds']}s")
    return report
