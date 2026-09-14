#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import os
import sys
from typing import Any

USAGE_KEYS = (
    "estimated_cost_usd", "cost_status", "cost_source", "input_tokens", "output_tokens",
    "cache_read_tokens", "cache_write_tokens", "reasoning_tokens", "total_tokens", "api_calls",
    "model", "provider", "session_id", "completed", "failed", "partial", "end_reason",
)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt-file", required=True, type=Path)
    ap.add_argument("--response-file", required=True, type=Path)
    ap.add_argument("--usage-file", required=True, type=Path)
    ap.add_argument("--model", required=True)
    ap.add_argument("--provider", required=True)
    ap.add_argument("--max-iterations", required=True, type=int)
    ap.add_argument("--max-output-tokens", required=True, type=int)
    args = ap.parse_args()
    if args.max_iterations < 1 or args.max_output_tokens < 1:
        raise SystemExit("positive limits required")

    from gateway.session_context import declare_stateless_channel
    from hermes_cli.config import load_config
    from hermes_cli.oneshot import _oneshot_clarify_callback
    from hermes_cli.runtime_provider import resolve_runtime_provider
    from hermes_constants import resolve_reasoning_config
    from run_agent import AIAgent

    os.environ["HERMES_YOLO_MODE"] = "1"
    os.environ["HERMES_ACCEPT_HOOKS"] = "1"
    declare_stateless_channel()
    cfg = load_config()
    runtime = resolve_runtime_provider(requested=args.provider, target_model=args.model)
    reasoning = resolve_reasoning_config(cfg, args.model)
    prompt = args.prompt_file.read_text(encoding="utf-8")

    agent = None
    result: dict[str, Any] = {}
    response = ""
    failure: str | None = None
    try:
        agent = AIAgent(
            api_key=runtime.get("api_key"),
            base_url=runtime.get("base_url"),
            provider=runtime.get("provider"),
            requested_provider=runtime.get("requested_provider"),
            api_mode=runtime.get("api_mode"),
            model=args.model,
            enabled_toolsets=["terminal", "file"],
            quiet_mode=True,
            platform="cli",
            credential_pool=runtime.get("credential_pool"),
            fallback_model=None,
            reasoning_config=reasoning,
            max_iterations=args.max_iterations,
            max_tokens=args.max_output_tokens,
            clarify_callback=_oneshot_clarify_callback,
        )
        agent.suppress_status_output = True
        agent.stream_delta_callback = None
        agent.tool_gen_callback = None
        result = agent.run_conversation(prompt)
        response = str(result.get("final_response") or "")
    except BaseException as exc:
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        if agent is not None:
            try:
                agent.close()
            except Exception:
                pass

    args.response_file.parent.mkdir(parents=True, exist_ok=True)
    args.response_file.write_text(response + ("" if not response or response.endswith("\n") else "\n"), encoding="utf-8")
    usage = {key: result.get(key) for key in USAGE_KEYS}
    usage.update({
        "schema": "openline.ril-rank-live-001.hermes-usage.v1",
        "requested_model": args.model,
        "requested_provider": args.provider,
        "max_iterations": args.max_iterations,
        "max_output_tokens_per_request": args.max_output_tokens,
        "failure": failure,
    })
    write_json(args.usage_file, usage)

    if failure is not None:
        print(failure, file=sys.stderr)
        return 1
    if result.get("failed") or result.get("partial") or result.get("completed") is not True:
        return 2
    if not response.strip():
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
