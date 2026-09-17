"""Token counting with the provider's tokenizer.

encoding_for_model('gpt-5.6-sol') -> o200k_base (verified 2026-09-16,
tiktoken 0.14.0). All structural caps are counted with this encoding.
Provider usage.input_tokens is settlement truth; calibration asserts the
local count tracks it within 2%.
"""
from __future__ import annotations

import tiktoken

ENCODING_NAME = "o200k_base"


def _enc():
    return tiktoken.get_encoding(ENCODING_NAME)


class CapExceeded(Exception):
    pass


def count(text: str) -> int:
    return len(_enc().encode(text))


def enforce_cap(text: str, cap: int, name: str) -> str:
    n = count(text)
    if n > cap:
        raise CapExceeded(f"{name}: {n} tokens exceeds cap {cap}")
    return text


def truncate_to(text: str, cap: int) -> str:
    """Hard truncate to at most `cap` tokens (used only for explicitly
    bounded feedback fields, never for task packets or method text)."""
    ids = _enc().encode(text)
    if len(ids) <= cap:
        return text
    return _enc().decode(ids[:cap])
