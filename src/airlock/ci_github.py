from __future__ import annotations

from pathlib import Path
import sys
from typing import Any
import urllib.error
import urllib.request

from . import ci


class _StripAuthorizationOnRedirect(urllib.request.HTTPRedirectHandler):
    """Follow GitHub's signed download redirects without forwarding its bearer token."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected.remove_header("Authorization")
        return redirected


class GitHubActionsReadClient(ci.GitHubActionsReadClient):
    """Post-freeze GitHub transport compatibility for live Recorder reads.

    CI-CODE-PATH-001 froze ``ci.py`` byte-for-byte. Provider transport quirks
    discovered after that proof live here so historical evidence remains intact.
    """

    def __init__(
        self,
        token: str | None = None,
        api_base: str = "https://api.github.com",
        opener: Any | None = None,
    ):
        super().__init__(token=token, api_base=api_base, opener=opener)
        # Tests may inject a deterministic opener. Production uses a redirect
        # handler that strips GitHub authorization before fetching the temporary
        # signed blob URL returned by the job-log API.
        self._job_log_opener = opener or urllib.request.build_opener(
            _StripAuthorizationOnRedirect()
        ).open

    def _job_log_request(self, path: str) -> bytes:
        req = urllib.request.Request(self.api_base + path, method="GET")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "openline-airlock-ci/0.3")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        self.request_methods.append(req.get_method())
        try:
            with self._job_log_opener(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise ci.ProviderFailure(f"GitHub authorization failed ({exc.code})") from exc
            if exc.code >= 500:
                raise ci.ProviderFailure(f"GitHub provider failure ({exc.code})") from exc
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ci.ProviderFailure(f"GitHub network failure: {ci._safe_error_text(exc)}") from exc

    def job_log(self, repo: str, job_id: int) -> dict[str, Any]:
        path = f"/repos/{repo}/actions/jobs/{job_id}/logs"
        try:
            raw = self._job_log_request(path)
            return {"available": True, "bytes": raw}
        except ci.ProviderFailure:
            raise
        except urllib.error.HTTPError as exc:
            if exc.code in {404, 410}:
                return {"available": False, "reason": f"GITHUB_{exc.code}"}
            raise ci.ProviderFailure(
                f"GitHub API {exc.code} while retrieving optional evidence"
            ) from exc


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
