from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Callable

from .util import run, write_json

_TERMINAL_EXIT_CODES = {0, 3}


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {"schema": "airlock.autopilot.v1", "issues": {}}
    try:
        obj = json.loads(path.read_text())
    except Exception as exc:
        raise RuntimeError(f"could not read autopilot state: {path}") from exc
    if not isinstance(obj, dict) or obj.get("schema") != "airlock.autopilot.v1":
        raise RuntimeError(f"unsupported autopilot state: {path}")
    issues = obj.get("issues")
    if not isinstance(issues, dict):
        raise RuntimeError(f"invalid autopilot state: {path}")
    return obj


def _list_labeled_issues(repo: Path, label: str, *, limit: int = 100) -> list[dict]:
    if not shutil.which("gh"):
        raise RuntimeError("`airlock autopilot` needs the GitHub CLI (`gh`) to read its issue queue")
    result = run(
        [
            "gh", "issue", "list",
            "--state", "open",
            "--label", label,
            "--limit", str(limit),
            "--json", "number,title,url,updatedAt",
        ],
        repo,
        timeout=30,
    )
    if result["exit_code"] != 0:
        detail = result.get("stderr", "").strip()[-500:]
        raise RuntimeError(f"could not read GitHub issue queue: {detail or 'gh issue list failed'}")
    try:
        rows = json.loads(result["stdout"])
    except Exception as exc:
        raise RuntimeError("could not parse GitHub issue queue") from exc
    if not isinstance(rows, list):
        raise RuntimeError("GitHub issue queue was not a list")

    clean: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        number = row.get("number")
        title = row.get("title")
        url = row.get("url")
        updated_at = row.get("updatedAt")
        if not isinstance(number, int) or not isinstance(title, str) or not isinstance(url, str):
            continue
        if not url.startswith("https://github.com/") or "/issues/" not in url:
            continue
        clean.append({
            "number": number,
            "title": title,
            "url": url,
            "updated_at": updated_at if isinstance(updated_at, str) else None,
        })
    return sorted(clean, key=lambda row: row["number"])


def _eligible(issue: dict, state: dict, *, retry_unchanged: bool) -> bool:
    if retry_unchanged:
        return True
    previous = state.get("issues", {}).get(issue["url"])
    if not isinstance(previous, dict):
        return True
    if previous.get("updated_at") != issue.get("updated_at"):
        return True
    return previous.get("exit_code") not in _TERMINAL_EXIT_CODES


def run_autopilot(
    repo: Path,
    *,
    label: str,
    max_issues: int,
    budget: float | None,
    retry_unchanged: bool,
    solve_issue: Callable[[str, float | None], int],
    state_path: Path | None = None,
    issue_loader: Callable[[Path, str], list[dict]] | None = None,
    now: Callable[[], str] | None = None,
) -> dict:
    """Process a bounded snapshot of maintainer-labeled issues exactly once per unchanged input."""
    if max_issues < 1:
        raise ValueError("--max-issues must be >= 1")
    if budget is not None and budget < 0:
        raise ValueError("--budget must be >= 0")
    label = label.strip()
    if not label:
        raise ValueError("--label cannot be empty")

    repo = repo.resolve()
    state_path = state_path or repo / ".airlock" / "autopilot" / "state.json"
    state = _load_state(state_path)
    loader = issue_loader or (lambda r, l: _list_labeled_issues(r, l))
    issues = loader(repo, label)
    eligible = [row for row in issues if _eligible(row, state, retry_unchanged=retry_unchanged)]
    batch = eligible[:max_issues]
    per_issue_budget = None if budget is None or not batch else budget / len(batch)
    clock = now or (lambda: datetime.now(timezone.utc).isoformat())

    results: list[dict] = []
    stopped_on_error = False
    for index, issue in enumerate(batch, start=1):
        print(f"\n[{index}/{len(batch)}] #{issue['number']} {issue['title']}")
        exit_code = int(solve_issue(issue["url"], per_issue_budget))
        status = "READY" if exit_code == 0 else "NO_REVIEW_READY" if exit_code == 3 else "ERROR"
        record = {
            "number": issue["number"],
            "title": issue["title"],
            "url": issue["url"],
            "updated_at": issue.get("updated_at"),
            "attempted_at": clock(),
            "exit_code": exit_code,
            "status": status,
        }
        state.setdefault("issues", {})[issue["url"]] = record
        state["label"] = label
        write_json(state_path, state)
        results.append(record)
        if exit_code not in _TERMINAL_EXIT_CODES:
            stopped_on_error = True
            break

    skipped_unchanged = len(issues) - len(eligible)
    report = {
        "schema": "airlock.autopilot.run.v1",
        "label": label,
        "queue_size": len(issues),
        "eligible_size": len(eligible),
        "attempted": len(results),
        "skipped_unchanged": skipped_unchanged,
        "max_issues": max_issues,
        "budget_usd": budget,
        "per_issue_budget_usd": per_issue_budget,
        "stopped_on_error": stopped_on_error,
        "results": results,
        "state_file": str(state_path.relative_to(repo)) if state_path.is_relative_to(repo) else str(state_path),
    }
    return report
