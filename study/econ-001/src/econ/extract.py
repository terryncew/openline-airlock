"""Extract machine-usable artifacts from model output.

Solving: exactly one ```python fenced block holding the complete corrected
file. Anything else -> extraction failure (recorded, never repaired).
Proposal: exactly one ```delta fenced block holding the delta directives.
"""
from __future__ import annotations

import re

_FENCE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)


def _blocks(text: str) -> list[tuple[str, str]]:
    return [(m.group(1).strip().lower(), m.group(2)) for m in _FENCE.finditer(text or "")]


def extract_file_block(text: str) -> str | None:
    cands = [body for lang, body in _blocks(text) if lang in ("python", "py", "")]
    if len(cands) != 1:
        return None
    body = cands[0].strip("\n")
    return body if body else None


def extract_delta(text: str) -> str | None:
    cands = [body for lang, body in _blocks(text) if lang == "delta"]
    if len(cands) != 1:
        return None
    body = cands[0].strip("\n")
    return body if body else None
