from __future__ import annotations

import sys

from . import __version__


PUBLIC_COMMANDS = (
    ("init", "Inspect the repo and create editable Starter Rules."),
    ("solve", "Work one issue or prompt and expose only a surviving patch."),
    ("autopilot", "Work a bounded queue selected by a maintainer label."),
    ("inbox", "Show only outcomes that need human attention."),
    ("review", "Re-verify and summarize why a survivor earned review."),
    ("install-github", "Install the Actions-only public contribution gate."),
)

ADVANCED_COMMANDS = (
    ("swarm", "Run explicit multi-round autonomous search."),
    ("run", "Run one independent best-of-N tournament."),
    ("verify", "Verify a saved Airlock survivor receipt offline."),
)


def _help_text() -> str:
    lines = [
        f"OpenLine Airlock {__version__}",
        "",
        "Usage: airlock <command> [options]",
        "",
        "The normal loop",
    ]
    for name, description in PUBLIC_COMMANDS:
        lines.append(f"  {name:<14} {description}")
    lines.extend(["", "Advanced"])
    for name, description in ADVANCED_COMMANDS:
        lines.append(f"  {name:<14} {description}")
    lines.extend([
        "",
        "Start here:",
        "  airlock init",
        "  airlock solve 417",
        "  airlock autopilot --label airlock",
        "  airlock inbox",
        "  airlock review",
        "",
        "Run `airlock <command> --help` for command-specific options.",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Public CLI router. Keep the common workflow visible without changing command semantics."""
    raw = list(sys.argv[1:] if argv is None else argv)

    if not raw or raw[0] in {"-h", "--help"}:
        print(_help_text())
        return 0

    if raw[0] == "--version":
        print(__version__)
        return 0

    if raw[0] == "review":
        from .review import main as review_main
        return review_main(raw[1:])

    from .cli import main as cli_main
    return cli_main(raw)


if __name__ == "__main__":
    raise SystemExit(main())
