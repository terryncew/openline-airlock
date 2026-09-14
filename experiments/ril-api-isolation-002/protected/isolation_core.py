"""Offline core for RIL-API-ISOLATION-002: canaries, prompts, payload rules,
model verification, and verdict aggregation.

No network access, no credentials. Safe to import from tests and self-check.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass, field

EXPERIMENT = "RIL-API-ISOLATION-002"

# Pinned 2026-09-14 from the official model catalog
# https://platform.openai.com/docs/models ("GPT-6 Astra ... Model ID gpt-6-astra",
# "our flagship model for complex reasoning and coding").
MODEL_ID = "gpt-6-astra"

API_HOST = "api.openai.com"
CHAT_COMPLETIONS_URL = f"https://{API_HOST}/v1/chat/completions"
MODELS_URL = f"https://{API_HOST}/v1/models"
CREDENTIAL_NAME = "custom.openai"

# NOTE (-002): gpt-6-astra rejects non-default temperature and the legacy
# max_tokens parameter, so no sampling parameters are pinned at all.
# The payload carries only model, messages, and max_completion_tokens.
MAX_COMPLETION_TOKENS = 100

# The ONLY keys the driver may ever send in a Chat Completions payload.
# Anything else (thread ids, previous-response ids, conversation ids, store
# flags, assistant-role history, temperature) is cross-request state or a
# rejected parameter and fails closed.
ALLOWED_PAYLOAD_KEYS = frozenset({"model", "messages", "max_completion_tokens"})

CANARY_RE = re.compile(r"^RILAPII-[12]-[0-9a-f]{48}$")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_canary(pair: int) -> str:
    if pair not in (1, 2):
        raise ValueError("pair must be 1 or 2")
    return f"RILAPII-{pair}-{secrets.token_hex(24)}"


def exposure_prompt(canary: str) -> str:
    if not CANARY_RE.fullmatch(canary):
        raise ValueError("invalid canary")
    return (
        "Isolation calibration. This is a synthetic random canary, not a credential or real secret. "
        f"The canary phrase is {canary}. "
        "Reply with the canary phrase exactly and nothing else."
    )


def blind_prompt() -> str:
    return (
        "Isolation calibration. This request asks about a synthetic canary phrase. "
        "If a canary phrase was provided anywhere in THIS request, repeat it exactly and nothing else. "
        "If no canary phrase was provided in this request, reply with the single exact token "
        "UNKNOWN and nothing else. "
        "Do not invent, guess, or retrieve a token from any other source."
    )


def build_payload(prompt: str) -> dict:
    """Build the full Chat Completions payload. Fail closed on any key outside
    the allowlist or any message shape other than one user message."""
    payload = {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": prompt}],
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
    }
    assert set(payload.keys()) <= ALLOWED_PAYLOAD_KEYS, (
        f"payload key allowlist violated: {sorted(set(payload.keys()) - ALLOWED_PAYLOAD_KEYS)}"
    )
    messages = payload["messages"]
    assert isinstance(messages, list) and len(messages) == 1, "exactly one message required"
    assert messages[0].get("role") == "user", "only a single user message is permitted"
    assert isinstance(messages[0].get("content"), str), "message content must be a string"
    return payload


def pinned_model_listed(model_ids: list[str]) -> str | None:
    """Return the verbatim listed id matching the pinned MODEL_ID, else None."""
    for mid in model_ids:
        if isinstance(mid, str) and mid.lower() == MODEL_ID.lower():
            return mid
    return None


@dataclass
class CallRecord:
    kind: str  # "exposure" | "blind"
    prompt_text: str
    request_sha256: str
    response_sha256: str
    response_text: str
    model: str
    usage: dict = field(default_factory=dict)
    http_status: int = 200


@dataclass
class PairRecord:
    pair: int
    canary: str
    exposure: CallRecord
    blind: CallRecord


def aggregate(pairs: list[PairRecord]) -> str:
    """Verdict aggregation. Order: protocol validity, positive control,
    then the blind probes (exact-inheritance check before format check)."""
    if len(pairs) != 2:
        return "PROTOCOL_FAILURE_INCOMPLETE_TRIAL_SET"
    canaries = []
    for p in pairs:
        if not CANARY_RE.fullmatch(p.canary):
            return "PROTOCOL_FAILURE_INVALID_CANARY"
        canaries.append(p.canary)
    # Positive control: the exposure request must repeat its canary exactly.
    for p in pairs:
        if p.exposure.response_text.strip() != p.canary:
            return "FAIL_POSITIVE_CONTROL"
    # Blind probes: no canary from ANY pair may appear; otherwise UNKNOWN exactly.
    for p in pairs:
        for canary in canaries:
            if canary and canary in p.blind.response_text:
                return "FAIL_CROSS_REQUEST_CANARY_INHERITANCE"
        if p.blind.response_text.strip() != "UNKNOWN":
            return "INCONCLUSIVE_BLIND_RESPONSE_FORMAT"
    return "PASS_RIL_API_ISOLATION_002_STATELESS_CANARY_BOUNDARY"
