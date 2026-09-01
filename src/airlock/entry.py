from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """Small public router that keeps review-side commands out of the execution CLI."""
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == "review":
        from .review import main as review_main

        return review_main(raw[1:])

    from .cli import main as cli_main

    return cli_main(raw)


if __name__ == "__main__":
    raise SystemExit(main())
