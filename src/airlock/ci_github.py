from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from . import ci


class GitHubActionsReadClient(ci.GitHubActionsReadClient):
    """Post-freeze GitHub transport compatibility for live Recorder reads.

    CI-CODE-PATH-001 froze ``ci.py`` byte-for-byte.  Provider transport quirks
    discovered after that proof live here so historical evidence remains intact.
    """

    def job_log(self, repo: str, job_id: int) -> dict[str, Any]:
        # GitHub's job-log endpoint expects the normal REST media type on the
        # API request.  urllib follows the provider redirect and returns the
        # resulting plain-text bytes.  Asking the API endpoint for text/plain
        # can be rejected with HTTP 415 before the redirect is issued.
        return self._optional_bytes(
            f"/repos/{repo}/actions/jobs/{job_id}/logs",
            accept="application/vnd.github+json",
        )


def record_run(
    run: str,
    *,
    repo_arg: str | None = None,
    cwd: Path | None = None,
    out: str | Path | None = None,
    client: ci.GitHubActionsReadClient | None = None,
) -> dict[str, Any]:
    """Run the frozen Recorder with the live GitHub transport adapter."""
    if client is None:
        target = ci.resolve_target(run, repo_arg, cwd=cwd)
        client = GitHubActionsReadClient(token=ci._token_from_environment(target.local_repo))
    return ci.record_run(run, repo_arg=repo_arg, cwd=cwd, out=out, client=client)


def main(argv: list[str] | None = None) -> int:
    """Public ``airlock ci`` entry using the post-freeze live adapter."""
    args = ci.build_parser().parse_args(argv)
    try:
        recorded = record_run(args.run, repo_arg=args.repo, out=args.out)
        receipt = recorded["receipt"]
        encoded = ci.canonical_json_bytes(receipt) + b"\n"
        if args.format == "json":
            sys.stdout.buffer.write(encoded)
        else:
            print(ci.render_text(receipt))
            print(f"Canonical JSON: {recorded['receipt_path']}")
        return 0
    except ci.CIRecorderError as exc:
        print(f"ERROR: {ci._safe_error_text(exc)}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        print(f"ERROR: {ci._safe_error_text(exc)}", file=sys.stderr)
        return 3
