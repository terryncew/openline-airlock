from __future__ import annotations

import sys

from . import entry


CI_HELP_LINE = "  ci             Classify failed GitHub Actions evidence before anyone repairs it."
CI_START_LINE = "  airlock ci <github-actions-run-url-or-id>"


def _help_text() -> str:
    """Extend the frozen v0.3 router help without rewriting its historical handoff."""
    base = entry._help_text()
    lines = base.splitlines()

    # Keep CI beside the normal read/review surfaces without changing entry.py,
    # whose bytes are frozen by prior product receipts.
    try:
        install_index = next(i for i, line in enumerate(lines) if line.lstrip().startswith("install-github"))
    except StopIteration:
        install_index = len(lines)
    lines.insert(install_index, CI_HELP_LINE)

    try:
        review_index = next(i for i, line in enumerate(lines) if line.strip() == "airlock review")
        lines.insert(review_index + 1, CI_START_LINE)
    except StopIteration:
        lines.extend(["", "CI evidence", CI_START_LINE])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Add the post-v0.3 CI Recorder while delegating every frozen command unchanged."""
    raw = list(sys.argv[1:] if argv is None else argv)

    if not raw or raw[0] in {"-h", "--help"}:
        print(_help_text())
        return 0

    if raw[0] == "ci":
        from .ci import main as ci_main
        return ci_main(raw[1:])

    return entry.main(raw)


if __name__ == "__main__":
    raise SystemExit(main())
