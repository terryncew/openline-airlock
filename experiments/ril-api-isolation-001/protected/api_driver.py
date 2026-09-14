#!/usr/bin/env python3
"""RIL-API-ISOLATION-001 driver.

Qualifies API-request statelessness for canary isolation: two paired canary
trials against the OpenAI Chat Completions API, one fresh independent request
per invocation, no conversation state anywhere.

Credential handling: the OpenAI API key is NEVER read from files, environment
variables, chat, or logs. It is obtained only as a Sentinel-managed surrogate
via the bundled dynamic_credentials helper (connector `custom.openai`,
bearer_header placement, api.openai.com allowlist). The surrogate is placed in
the Authorization header and replaced with the real key on approved egress;
this process never sees key material.

Usage:
    python3 protected/api_driver.py self-check
    python3 protected/api_driver.py qualify --output /tmp/ril-api-isolation-001

Exit codes: 0 on PASS, 2 on any other terminal verdict (fail closed; do not
retry under this experiment ID).
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
import dynamic_credentials as dc  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import isolation_core as core  # noqa: E402

RECEIPT_SCHEMA = "openline.ril-api-isolation-001.receipt.v1"
HTTP_TIMEOUT = 60


class FailClosed(Exception):
    """Terminal protocol failure. Carries the verdict string."""

    def __init__(self, verdict: str, detail: str = ""):
        super().__init__(detail or verdict)
        self.verdict = verdict


def _authed_request(url: str, payload: dict | None) -> tuple[urllib.request.Request, bytes]:
    """Build a request with the credential surrogate attached.

    Raises FailClosed(FAIL_CREDENTIAL_UNAVAILABLE) if the connector holds no
    credential. Never exposes key material.
    """
    if payload is None:
        req = urllib.request.Request(url, method="GET")
    else:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    try:
        dc.add_surrogate_to_request(
            req, core.CREDENTIAL_NAME, allowed_hosts=[core.API_HOST]
        )
    except dc.DynamicCredentialError as exc:
        raise FailClosed("FAIL_CREDENTIAL_UNAVAILABLE", str(exc)) from exc
    return req, (body if payload is not None else b"")


def _read_json(resp) -> tuple[dict, bytes]:
    raw = dc.read_response_body(resp)
    try:
        return json.loads(raw.decode("utf-8")), raw
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise FailClosed("PROTOCOL_FAILURE_UNCLASSIFIED", f"non-JSON API response: {exc}")


def _assistant_text(body: dict) -> str:
    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise FailClosed("PROTOCOL_FAILURE_UNCLASSIFIED", f"unexpected chat response shape: {exc}")


def verify_model_available() -> tuple[str, str]:
    """Pre-canary gate: GET /v1/models and confirm the pinned model id is listed.

    Returns (verbatim_listed_id, sha256 of sorted id list). Fail closed if the
    pinned id is absent: the frozen model selection no longer resolves.
    """
    req, _ = _authed_request(core.MODELS_URL, None)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            status = resp.status
            body, _ = _read_json(resp)
    except urllib.error.HTTPError as exc:
        raise FailClosed("FAIL_MODEL_UNAVAILABLE", f"GET /v1/models -> HTTP {exc.code}")
    except OSError as exc:
        raise FailClosed("FAIL_MODEL_UNAVAILABLE", f"GET /v1/models transport error: {exc}")
    ids = [m.get("id") for m in body.get("data", []) if isinstance(m, dict)]
    listed = core.pinned_model_listed(ids)
    list_hash = core.sha256_hex("\n".join(sorted(i for i in ids if isinstance(i, str))).encode())
    if listed is None or status != 200:
        raise FailClosed(
            "FAIL_MODEL_UNAVAILABLE",
            f"pinned model id {core.MODEL_ID!r} not listed in /v1/models",
        )
    return listed, list_hash


def api_call(prompt: str, kind: str, forbidden_substrings: tuple[str, ...] = ()) -> tuple[dict, bytes, bytes]:
    """One fresh independent Chat Completions request. Fail closed before
    sending if the serialized payload contains any forbidden substring
    (e.g. the blind payload must not contain the canary)."""
    payload = core.build_payload(prompt)
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    for bad in forbidden_substrings:
        if bad and bad.encode("utf-8") in serialized:
            raise FailClosed(
                "FAIL_PROTOCOL_STATE_PARAM",
                f"{kind} payload contains forbidden cross-request state",
            )
    req, body = _authed_request(core.CHAT_COMPLETIONS_URL, payload)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            status = resp.status
            resp_body, raw = _read_json(resp)
    except urllib.error.HTTPError as exc:
        raise FailClosed("PROTOCOL_FAILURE_UNCLASSIFIED", f"chat completions -> HTTP {exc.code}")
    except OSError as exc:
        raise FailClosed("PROTOCOL_FAILURE_UNCLASSIFIED", f"chat completions transport error: {exc}")
    if status != 200:
        raise FailClosed("PROTOCOL_FAILURE_UNCLASSIFIED", f"chat completions -> HTTP {status}")
    return resp_body, body, raw


def run_pair(pair: int) -> core.PairRecord:
    canary = core.make_canary(pair)

    exp_prompt = core.exposure_prompt(canary)
    exp_body, exp_req_bytes, exp_raw = api_call(exp_prompt, "exposure")
    exposure = core.CallRecord(
        kind="exposure",
        prompt_text=exp_prompt,
        request_sha256=core.sha256_hex(exp_req_bytes),
        response_sha256=core.sha256_hex(exp_raw),
        response_text=_assistant_text(exp_body),
        model=str(exp_body.get("model", "")),
        usage=dict(exp_body.get("usage", {}) or {}),
        http_status=200,
    )

    blind = core.blind_prompt()
    blind_body, blind_req_bytes, blind_raw = api_call(blind, "blind", forbidden_substrings=(canary,))
    blind_rec = core.CallRecord(
        kind="blind",
        prompt_text=blind,
        request_sha256=core.sha256_hex(blind_req_bytes),
        response_sha256=core.sha256_hex(blind_raw),
        response_text=_assistant_text(blind_body),
        model=str(blind_body.get("model", "")),
        usage=dict(blind_body.get("usage", {}) or {}),
        http_status=200,
    )
    return core.PairRecord(pair=pair, canary=canary, exposure=exposure, blind=blind_rec)


def cmd_self_check() -> int:
    """Offline contract check: no network, no credential."""
    c1, c2 = core.make_canary(1), core.make_canary(2)
    assert core.CANARY_RE.fullmatch(c1) and core.CANARY_RE.fullmatch(c2) and c1 != c2
    ep = core.exposure_prompt(c1)
    assert c1 in ep
    bp = core.blind_prompt()
    assert c1 not in bp and c2 not in bp, "blind prompt must not contain any canary"
    p = core.build_payload(ep)
    assert set(p) <= core.ALLOWED_PAYLOAD_KEYS and len(p["messages"]) == 1
    assert core.pinned_model_listed(["gpt-6-astra", "gpt-5.6-sol"]) == "gpt-6-astra"
    assert core.pinned_model_listed(["gpt-5.6-sol"]) is None

    def rec(kind, text):
        return core.CallRecord(kind, "", "r" * 64, "s" * 64, text, core.MODEL_ID, {}, 200)

    good = [
        core.PairRecord(1, c1, rec("exposure", c1), rec("blind", "UNKNOWN")),
        core.PairRecord(2, c2, rec("exposure", c2), rec("blind", "UNKNOWN")),
    ]
    assert core.aggregate(good) == "PASS_RIL_API_ISOLATION_001_STATELESS_CANARY_BOUNDARY"
    leak = [
        core.PairRecord(1, c1, rec("exposure", c1), rec("blind", c1)),
        core.PairRecord(2, c2, rec("exposure", c2), rec("blind", "UNKNOWN")),
    ]
    assert core.aggregate(leak) == "FAIL_CROSS_REQUEST_CANARY_INHERITANCE"
    weak = [
        core.PairRecord(1, c1, rec("exposure", "sorry"), rec("blind", "UNKNOWN")),
        core.PairRecord(2, c2, rec("exposure", c2), rec("blind", "UNKNOWN")),
    ]
    assert core.aggregate(weak) == "FAIL_POSITIVE_CONTROL"
    vague = [
        core.PairRecord(1, c1, rec("exposure", c1), rec("blind", "I cannot recall.")),
        core.PairRecord(2, c2, rec("exposure", c2), rec("blind", "UNKNOWN")),
    ]
    assert core.aggregate(vague) == "INCONCLUSIVE_BLIND_RESPONSE_FORMAT"
    print("SELF_CHECK_PASS")
    return 0


def _record_to_json(r: core.CallRecord) -> dict:
    return {
        "kind": r.kind,
        "prompt_text": r.prompt_text,
        "request_sha256": r.request_sha256,
        "response_sha256": r.response_sha256,
        "response_text": r.response_text,
        "model": r.model,
        "usage": r.usage,
        "http_status": r.http_status,
    }


def cmd_qualify(output: Path) -> int:
    output.mkdir(parents=True, exist_ok=True)
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    receipt: dict = {
        "schema": RECEIPT_SCHEMA,
        "experiment": core.EXPERIMENT,
        "started_at": started,
        "credential": {
            "connector": core.CREDENTIAL_NAME,
            "mechanism": "sentinel surrogate via dynamic_credentials helper; bearer_header placement",
            "key_material_in_receipt": False,
        },
    }
    verdict = "PROTOCOL_FAILURE_UNCLASSIFIED"
    try:
        # Pre-canary gate: no canary is generated until the pinned model id is
        # confirmed listed by the provider.
        listed_id, list_hash = verify_model_available()
        receipt["model_selection"] = {
            "pinned_model_id": core.MODEL_ID,
            "listed_id_verbatim": listed_id,
            "models_list_sha256": list_hash,
            "rule": "pinned id must be listed by GET /v1/models at run start; fail closed otherwise",
        }
        pairs = [run_pair(1), run_pair(2)]
        verdict = core.aggregate(pairs)
        receipt["pairs"] = [
            {
                "pair": pr.pair,
                "canary_sha256": core.sha256_hex(pr.canary.encode()),
                "exposure": _record_to_json(pr.exposure),
                "blind": _record_to_json(pr.blind),
            }
            for pr in pairs
        ]
    except FailClosed as exc:
        verdict = exc.verdict
        receipt["failure_detail"] = str(exc)
    receipt["verdict"] = verdict
    receipt["ended_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    out_path = output / "RIL_API_ISOLATION_001_RECEIPT.json"
    out_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(f"verdict={verdict}")
    print(f"receipt={out_path}")
    return 0 if verdict == "PASS_RIL_API_ISOLATION_001_STATELESS_CANARY_BOUNDARY" else 2


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="api_driver.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("self-check", help="offline contract check (no network, no credential)")
    q = sub.add_parser("qualify", help="run the two paired canary trials")
    q.add_argument("--output", required=True, help="directory for the receipt JSON")
    args = ap.parse_args(argv)
    if args.cmd == "self-check":
        return cmd_self_check()
    return cmd_qualify(Path(args.output))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
