from __future__ import annotations

from pathlib import Path
import json


_ATTENTION_ACTIONS = {"REVIEW", "CHOOSE", "FIX_BASELINE", "FIX_ENV", "FIX_RECORD"}


def _read_json(path: Path) -> dict:
    try:
        obj = json.loads(path.read_text())
    except Exception as exc:
        raise RuntimeError(f"could not read Airlock record: {path}") from exc
    if not isinstance(obj, dict):
        raise RuntimeError(f"Airlock record is not an object: {path}")
    return obj


def _prompt_source(repo: Path, run_id: str | None) -> str | None:
    if not run_id:
        return None
    path = repo / ".airlock" / "runs" / run_id / "prompt.txt"
    if not path.exists():
        return None
    try:
        text = path.read_text()
    except OSError:
        return None
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped.startswith("Source: https://github.com/") and "/issues/" in stripped:
            return stripped.removeprefix("Source: ").strip()
    token = text.strip()
    if token.startswith("https://github.com/") and "/issues/" in token and "\n" not in token:
        return token
    return None


def _swarm_item(repo: Path, path: Path) -> dict:
    try:
        report = _read_json(path)
    except RuntimeError as exc:
        return {
            "kind": "swarm",
            "action": "FIX_RECORD",
            "status": "INVALID_RECORD",
            "sort_key": path.parent.name,
            "source": None,
            "detail": str(exc),
            "path": str(path.relative_to(repo)),
            "needs_human": True,
        }

    status = str(report.get("status") or "UNKNOWN")
    run_id = report.get("final_run_id")
    source = _prompt_source(repo, run_id if isinstance(run_id, str) else None)
    pr = report.get("pull_request") if isinstance(report.get("pull_request"), dict) else {}
    pr_url = pr.get("url") if pr.get("status") == "CREATED" and isinstance(pr.get("url"), str) else None
    survivor_count = int(report.get("final_survivor_count", 0) or 0)

    if status == "READY":
        action = "REVIEW"
        detail = pr_url or report.get("ready_branch") or "one patch earned review"
    elif status == "MULTIPLE_SURVIVORS":
        action = "CHOOSE"
        detail = f"{survivor_count} patches survived; Airlock did not choose between them"
    elif status == "BASELINE_NOT_GREEN":
        action = "FIX_BASELINE"
        detail = "starting repository did not pass its frozen checks"
    elif status == "NO_PATCH_READY":
        action = "NONE"
        detail = "no patch earned review"
    else:
        action = "FIX_RECORD"
        detail = f"unexpected swarm status: {status}"

    return {
        "kind": "swarm",
        "action": action,
        "status": status,
        "sort_key": str(report.get("swarm_id") or path.parent.name),
        "source": source,
        "detail": detail,
        "path": str(path.relative_to(repo)),
        "pr_url": pr_url,
        "survivor_count": survivor_count,
        "needs_human": action in _ATTENTION_ACTIONS,
    }


def _autopilot_error_items(repo: Path) -> list[dict]:
    path = repo / ".airlock" / "autopilot" / "state.json"
    if not path.exists():
        return []
    try:
        state = _read_json(path)
    except RuntimeError as exc:
        return [{
            "kind": "autopilot",
            "action": "FIX_RECORD",
            "status": "INVALID_RECORD",
            "sort_key": "",
            "source": None,
            "detail": str(exc),
            "path": str(path.relative_to(repo)),
            "needs_human": True,
        }]

    issues = state.get("issues", {})
    if not isinstance(issues, dict):
        return [{
            "kind": "autopilot",
            "action": "FIX_RECORD",
            "status": "INVALID_RECORD",
            "sort_key": "",
            "source": None,
            "detail": f"invalid autopilot issue state: {path}",
            "path": str(path.relative_to(repo)),
            "needs_human": True,
        }]

    rows: list[dict] = []
    for url, record in issues.items():
        if not isinstance(record, dict) or record.get("status") != "ERROR":
            continue
        attempted_at = record.get("attempted_at") if isinstance(record.get("attempted_at"), str) else ""
        title = record.get("title") if isinstance(record.get("title"), str) else "autopilot issue"
        rows.append({
            "kind": "autopilot",
            "action": "FIX_ENV",
            "status": "ERROR",
            "sort_key": attempted_at,
            "source": url if isinstance(url, str) else None,
            "detail": f"autopilot stopped while working: {title}",
            "path": str(path.relative_to(repo)),
            "needs_human": True,
        })
    return rows


def build_inbox(repo: Path, *, include_all: bool = False, limit: int = 20) -> dict:
    """Reduce Airlock run artifacts to the small set of outcomes that need human attention."""
    if limit < 1:
        raise ValueError("--limit must be >= 1")
    repo = repo.resolve()

    swarm_root = repo / ".airlock" / "swarms"
    swarm_items = []
    if swarm_root.exists():
        for path in sorted(swarm_root.glob("*/swarm.json")):
            swarm_items.append(_swarm_item(repo, path))

    items = swarm_items + _autopilot_error_items(repo)
    items.sort(key=lambda row: row.get("sort_key", ""), reverse=True)

    attention = [row for row in items if row.get("needs_human")]
    machine_only = [row for row in items if not row.get("needs_human")]
    visible = items if include_all else attention
    visible = visible[:limit]

    return {
        "schema": "airlock.inbox.v1",
        "needs_human": len(attention),
        "machine_only_results": len(machine_only),
        "total_results": len(items),
        "include_all": include_all,
        "limit": limit,
        "items": visible,
    }
