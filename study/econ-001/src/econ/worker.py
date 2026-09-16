"""Fixed-request worker: one billable request per invocation, no retries.

- Reservation posted to the ledger BEFORE contact; refused pre-contact if
  the input exceeds the envelope or the ledger lacks headroom.
- Exactly one HTTP POST to /v1/responses via urllib. No SDK, so there is
  no retry layer to audit: a second request is structurally impossible in
  this code path (asserted by the offline no-retry test).
- Settlement from the response usage object. Missing usage (including
  timeouts) -> unresolved exposure: the reservation is RETAINED, never
  treated as a free failure.
- Actual > reservation -> cost overrun abort (fail closed).
- Raw provider responses (status + full payload, which carries usage) are
  persisted to raw_dir BEFORE any parsing, so a later crash can never
  destroy the evidence of what the provider returned.
- Operator stop: if stop_file exists when invoke() is entered, the call
  is NOT issued (no reservation, no provider contact); status "stopped".
  Callers propagate via OperatorStop so the study halts before the next
  paid invocation. A stop placed mid-flight takes effect on the next
  invoke(): the in-flight call settles normally, then the loop halts.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
import urllib.request
import uuid
from dataclasses import dataclass, field

from . import tokens

RESPONSES_URL = "https://api.openai.com/v1/responses"

# Frozen pricing, USD per 1M tokens (CONFIG.json).
P_IN, P_CACHED, P_CACHE_WRITE, P_OUT = 4.00, 0.40, 5.00, 20.00

# The Responses API adds a constant framing overhead on top of the raw
# instructions+input token count. Measured 2026-09-16 (dev-002, n=42):
# provider input_tokens = local count + 10 on every call, zero variance.
# Added to the local pre-contact count so envelope gating sees what the
# provider will bill. Re-verified at study calibration; drift beyond the
# 2% rule aborts the study.
PROVIDER_FRAMING_TOKENS = 10


class OverrunAbort(Exception):
    pass


class OperatorStop(Exception):
    """Raised by callers when the worker reports status "stopped".

    Means: the operator stop file was present before a paid invocation,
    so the call was never issued. Propagates to run_study, which halts
    the loop cleanly before any further paid invocation.
    """


@dataclass
class InvocationResult:
    invocation_id: str
    envelope: str
    status: str  # ok | refused_precontact | failed | unresolved | overrun_abort | stopped
    reservation_usd: float
    actual_usd: float | None
    usage: dict | None
    text: str | None
    request_id: str | None
    error: str | None = None
    local_input_tokens: int = 0
    raw_path: str | None = None  # raw provider response persisted pre-parse


class Provider:
    def post(self, body: dict, headers: dict, timeout: float):
        """Return (status_code, response_dict). Exactly one request."""
        raise NotImplementedError


class RealProvider(Provider):
    """Live provider via urllib + authd surrogate. No retries, one shot."""

    def __init__(self, credential_name: str = "custom.openai"):
        self.credential_name = credential_name

    def post(self, body: dict, headers: dict, timeout: float):
        sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
        import dynamic_credentials as dc
        dc.ensure_allowed_url(RESPONSES_URL, ("api.openai.com",))
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            RESPONSES_URL, data=data,
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        dc.add_surrogate_to_request(req, self.credential_name,
                                    allowed_hosts=("api.openai.com",))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, dc.read_json_response(resp)
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read().decode("utf-8", errors="replace"))
            except Exception:
                payload = {"error": f"http_{e.code}"}
            return e.code, payload


class FakeProvider(Provider):
    """Scripted provider for offline fixtures. Counts requests."""

    def __init__(self, script):
        # script: list of ("ok", response_dict) | ("http_error", code, dict)
        #         | ("timeout",) | ("no_usage", response_dict)
        self.script = list(script)
        self.requests = 0

    def post(self, body: dict, headers: dict, timeout: float):
        self.requests += 1
        if self.requests > 1:
            raise AssertionError("second request attempted: retry path exists")
        kind = self.script[0][0]
        if kind == "timeout":
            raise socket.timeout("scripted timeout")
        if kind == "http_error":
            _, code, payload = self.script[0]
            return code, payload
        _, payload = self.script[0]
        return 200, payload


def settle_cost(usage: dict) -> float:
    inp = int(usage["input_tokens"])
    det = usage.get("input_tokens_details") or {}
    cached = int(det.get("cached_tokens") or 0)
    cw = int(det.get("cache_write_tokens") or 0)
    out = int(usage["output_tokens"])
    base = max(inp - cached - cw, 0)
    return (base * P_IN + cached * P_CACHED + cw * P_CACHE_WRITE
            + out * P_OUT) / 1e6


def extract_text(response: dict) -> str | None:
    for item in response.get("output", []) or []:
        if item.get("type") == "message":
            for part in item.get("content", []) or []:
                if part.get("type") == "output_text":
                    return part.get("text")
    return None


def _persist_raw(raw_dir: str, invocation_id: str, envelope: str,
                 status_code, request_body: dict, payload) -> str:
    """Write the raw provider response before any parsing.

    Returns the path written. Never raises: persistence failure is
    recorded in the returned marker, never allowed to break accounting.
    """
    os.makedirs(raw_dir, exist_ok=True)
    path = os.path.join(raw_dir, f"{invocation_id}.json")
    doc = {
        "invocation_id": invocation_id,
        "envelope": envelope,
        "t": time.time(),
        "http_status": status_code,
        "request": request_body,
        "response": payload,
    }
    try:
        with open(path, "w") as f:
            json.dump(doc, f, indent=1, sort_keys=True, default=str)
        return path
    except Exception as e:  # disk full etc: do not break the money path
        return f"<raw-persist-failed: {e}>"


def invoke(*, instructions: str, input_text: str, envelope: dict,
           ledger, provider: Provider, invocation_id: str | None = None,
           timeout_s: float = 300.0,
           request_params: dict | None = None,
           clock=None, stop_file: str | None = None,
           raw_dir: str | None = None) -> InvocationResult:
    inv = invocation_id or ("inv_" + uuid.uuid4().hex[:12])
    env_name = envelope["name"]
    R = float(envelope["reservation_usd"])
    now = (clock or time.time)()

    # Operator stop: checked BEFORE any reservation or provider contact.
    # This is the stop-before-next-call control: placing stop_file halts
    # the study loop with zero further paid invocations, demonstrably.
    if stop_file and os.path.exists(stop_file):
        ledger.note("stopped_before_contact", invocation_id=inv,
                    envelope=env_name, stop_file=stop_file, t=now)
        return InvocationResult(inv, env_name, "stopped", R, None, None,
                                None, None,
                                error=f"operator stop file present: {stop_file}")


    local_in = (tokens.count(instructions) + tokens.count(input_text)
                + PROVIDER_FRAMING_TOKENS)
    res = InvocationResult(inv, env_name, "failed", R, None, None, None, None,
                           local_input_tokens=local_in)

    # Pre-contact gate 1: envelope input bound.
    if local_in > int(envelope["max_input_tokens"]):
        res.status = "refused_precontact"
        res.error = (f"input {local_in} tokens exceeds envelope "
                     f"{envelope['max_input_tokens']}")
        ledger.note("refused_precontact", invocation_id=inv, envelope=env_name,
                    local_input_tokens=local_in, reason=res.error)
        return res

    # Pre-contact gate 2: budget headroom.
    try:
        rsv = ledger.reserve(R, inv, env_name)
    except Exception as e:  # InsufficientBudget
        res.status = "refused_precontact"
        res.error = f"budget: {e}"
        ledger.note("refused_precontact", invocation_id=inv, envelope=env_name,
                    reason=res.error)
        return res
    rsv_id = rsv["reservation_id"]

    body = {
        "model": (request_params or {}).get("model", "gpt-5.6-sol"),
        "instructions": instructions,
        "input": input_text,
        "max_output_tokens": int(envelope["max_output_tokens"]),
        "reasoning": {"effort": "medium"},
        # temperature OMITTED: gpt-5.6-sol rejects non-default temperature
        # with HTTP 400 (verified empirically 2026-09-16).
        "store": False,
        "stream": False,
        "tools": [],
        "tool_choice": "none",
    }
    headers = {"X-Client-Request-Id": inv}

    try:
        status, payload = provider.post(body, headers, timeout_s)
    except (socket.timeout, TimeoutError) as e:
        ledger.unresolved(rsv_id, inv, R, reason=f"timeout_no_usage: {e}")
        res.status = "unresolved"
        res.error = f"timeout without usage; reservation ${R:.4f} retained"
        return res
    except Exception as e:
        ledger.unresolved(rsv_id, inv, R, reason=f"transport_no_usage: {e}")
        res.status = "unresolved"
        res.error = f"transport failure without usage; reservation ${R:.4f} retained"
        return res

    # Raw response persisted BEFORE any parsing or settlement, so a later
    # crash (extract, delta, evaluate) can never destroy what the provider
    # actually returned. This closes the launch-1 gap where the malformed
    # proposal's text was lost.
    raw_path = (_persist_raw(raw_dir, inv, env_name, status, body, payload)
                if raw_dir else None)
    res.raw_path = raw_path

    if status != 200 or not isinstance(payload, dict) or payload.get("object") == "error":
        ledger.unresolved(rsv_id, inv, R,
                          reason=f"http_{status}_no_usage: {str(payload)[:200]}")
        res.status = "unresolved"
        res.error = f"HTTP {status} without usable usage; reservation retained"
        return res

    usage = payload.get("usage")
    if not usage or "input_tokens" not in usage or "output_tokens" not in usage:
        ledger.unresolved(rsv_id, inv, R, reason="missing_usage_object")
        res.status = "unresolved"
        res.error = "200 without a usable usage object; reservation retained"
        return res

    actual = settle_cost(usage)
    if actual > R + 1e-9:
        ledger.note("overrun_abort", invocation_id=inv, envelope=env_name,
                    reservation=R, actual=actual, usage=usage,
                    request_id=payload.get("id"))
        res.status = "overrun_abort"
        res.actual_usd = actual
        res.usage = usage
        res.request_id = payload.get("id")
        res.error = f"actual ${actual:.6f} exceeded reservation ${R:.4f}"
        raise OverrunAbort(res.error)

    ledger.settle(rsv_id, inv, R, actual, usage, status="ok")
    res.status = "ok"
    res.actual_usd = actual
    res.usage = usage
    res.text = extract_text(payload)
    res.request_id = payload.get("id")
    return res
