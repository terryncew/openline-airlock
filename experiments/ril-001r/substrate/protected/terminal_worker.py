#!/usr/bin/env python3
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
from protected.benchmark import load_policy, normalize_tactics, validate_policy_source  # noqa: E402

EXPECTED_MODEL = "gpt-5.6-sol"
EXPECTED_PROVIDER = "openai-api"
MAX_ITERATIONS = 18
MAX_OUTPUT_TOKENS_PER_REQUEST = 4096
MAX_REPORTED_TOTAL_TOKENS = 240000
MAX_ESTIMATED_USD = Decimal("0.75")
POLICY = ROOT / "mutable" / "generator.py"
MEMORY = ROOT / "context" / "verified_memory.md"
FEEDBACK = ROOT / "context" / "opportunity_feedback.json"
DRIVER = ROOT / "protected" / "live_agent_driver.py"
FORBIDDEN = {"GITHUB_TOKEN", "GH_TOKEN", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"}
EVIDENCE_BY_TACTIC = {
    "inspect_repo": (),
    "run_baseline": ("baseline.txt",),
    "read_tests": ("tests.txt",),
    "trace_failure": ("trace.txt",),
    "small_patch": (),
    "measure_hotspot": ("profile.txt",),
    "adversarial_check": ("adversarial.txt",),
    "preserve_invariants": ("constraints.txt",),
    "read_docs": ("docs.txt", "constraints.txt"),
    "compare_history": ("history.txt",),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                value = json.loads(text[start:end + 1])
                return value if isinstance(value, dict) else {}
            except Exception:
                return {}
    return {}


def hermes_python() -> Path:
    exe = shutil.which("hermes")
    if not exe:
        raise RuntimeError("pinned hermes executable not found on PATH")
    resolved = Path(exe).resolve()
    python = resolved.parent / "python"
    if not python.is_file():
        raise RuntimeError(f"could not resolve pinned Hermes venv python beside {resolved}")
    return python


def accounting(parsed: dict) -> dict:
    required_ints = ("input_tokens", "output_tokens", "total_tokens", "api_calls")
    numeric = all(isinstance(parsed.get(name), int) and not isinstance(parsed.get(name), bool) and parsed[name] >= 0 for name in required_ints)
    try:
        cost = Decimal(str(parsed.get("estimated_cost_usd")))
        cost_valid = cost > 0
    except (InvalidOperation, TypeError):
        cost = Decimal("0")
        cost_valid = False
    status = str(parsed.get("cost_status") or "").strip().lower()
    source = str(parsed.get("cost_source") or "").strip().lower()
    priced = status not in {"", "unknown", "unavailable", "none"} and source not in {"", "unknown", "none"}
    identity = parsed.get("model") == EXPECTED_MODEL and parsed.get("provider") == EXPECTED_PROVIDER
    complete = numeric and cost_valid and priced and identity
    within = bool(complete and int(parsed["total_tokens"]) <= MAX_REPORTED_TOTAL_TOKENS and cost <= MAX_ESTIMATED_USD)
    return {
        "telemetry_complete": complete,
        "within_preregistered_limits": within,
        "estimated_cost_usd": str(cost),
        "reported_total_tokens": parsed.get("total_tokens"),
        "reported_api_calls": parsed.get("api_calls"),
        "cost_status": parsed.get("cost_status"),
        "cost_source": parsed.get("cost_source"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--answers", required=True, type=Path)
    ap.add_argument("--receipt", required=True, type=Path)
    args = ap.parse_args()

    home_raw = os.environ.get("HERMES_HOME")
    if not home_raw:
        raise SystemExit("HERMES_HOME required")
    leaked = sorted(name for name in os.environ if name in FORBIDDEN)
    if leaked:
        raise SystemExit("forbidden credential environment reached terminal worker: " + ",".join(leaked))

    guard = validate_policy_source(POLICY)
    choose = load_policy(POLICY)
    memory = MEMORY.read_text(encoding="utf-8", errors="replace")[:7000] if MEMORY.is_file() else ""
    feedback = FEEDBACK.read_text(encoding="utf-8", errors="replace")[:12000] if FEEDBACK.is_file() else ""
    case_sections = []
    tactic_receipts = {}
    for task_path in sorted((ROOT / "cases").glob("*/TASK.json")):
        task = json.loads(task_path.read_text(encoding="utf-8"))
        case_id = str(task["case_id"])
        context = str(task["context"])
        tactics = normalize_tactics(choose(context))
        tactic_receipts[case_id] = tactics
        cdir = task_path.parent
        evidence = []
        if "inspect_repo" in tactics:
            evidence.append("visible files: " + ", ".join(sorted(p.name for p in cdir.iterdir() if p.is_file())))
        for tactic in tactics:
            for name in EVIDENCE_BY_TACTIC[tactic]:
                path = cdir / name
                if path.is_file():
                    evidence.append(f"[{name}] {path.read_text(encoding='utf-8', errors='replace').strip()}")
        case_sections.append(
            json.dumps(task, sort_keys=True)
            + "\nPolicy-selected evidence:\n"
            + ("\n".join(dict.fromkeys(evidence)) if evidence else "(none preloaded; inspect the case directory if needed)")
        )

    prompt = (
        "RIL-001 terminal maintenance search. Solve every case using the task options and repository evidence. "
        "You may inspect files under cases/ with terminal tools when preloaded evidence is insufficient. "
        "Return ONLY one JSON object mapping every case_id to exactly one option ID A/B/C/D.\n\n"
        "Arm-local receiver feedback from the three improvement opportunities (same channel exists in both arms):\n"
        + (feedback or '{"history": []}')
        + "\n\nReceiver-verified inherited memory (may be empty):\n"
        + (memory or "No established memory.\n")
        + "\nTerminal cases:\n\n"
        + "\n\n".join(case_sections)
    )

    home = Path(home_raw)
    usage = home / "ril001-terminal-usage.json"
    prompt_file = home / "ril001-terminal-prompt.txt"
    response_file = home / "ril001-terminal-response.txt"
    for path in (usage, prompt_file, response_file):
        path.unlink(missing_ok=True)
    prompt_file.write_text(prompt, encoding="utf-8")
    cp = subprocess.run(
        [
            str(hermes_python()), str(DRIVER),
            "--prompt-file", str(prompt_file),
            "--response-file", str(response_file),
            "--usage-file", str(usage),
            "--model", EXPECTED_MODEL,
            "--provider", EXPECTED_PROVIDER,
            "--max-iterations", str(MAX_ITERATIONS),
            "--max-output-tokens", str(MAX_OUTPUT_TOKENS_PER_REQUEST),
        ],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if cp.stderr:
        print(cp.stderr, file=sys.stderr, end="" if cp.stderr.endswith("\n") else "\n")
    response_text = response_file.read_text(encoding="utf-8", errors="replace") if response_file.is_file() else ""
    answers = parse_json_object(response_text)
    args.answers.parent.mkdir(parents=True, exist_ok=True)
    args.answers.write_text(json.dumps(answers, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    usage_obj = {}
    if usage.is_file():
        try:
            usage_obj = json.loads(usage.read_text(encoding="utf-8"))
        except Exception:
            usage_obj = {}
    acct = accounting(usage_obj)
    execution_completed = cp.returncode == 0 and usage_obj.get("completed") is True and not bool(usage_obj.get("failed"))
    receipt = {
        "schema": "openline.ril-001.terminal-worker.v2",
        "policy_sha256": guard["sha256"],
        "memory_sha256": sha(MEMORY) if MEMORY.is_file() else None,
        "opportunity_feedback_sha256": sha(FEEDBACK) if FEEDBACK.is_file() else None,
        "selected_tactics": tactic_receipts,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "answers_sha256": sha(args.answers),
        "usage_sha256": sha(usage) if usage.is_file() else None,
        "usage": usage_obj,
        "accounting": acct,
        "execution_completed": execution_completed,
        "exit_code": cp.returncode,
        "limits": {
            "max_iterations": MAX_ITERATIONS,
            "max_output_tokens_per_request": MAX_OUTPUT_TOKENS_PER_REQUEST,
            "max_reported_total_tokens": MAX_REPORTED_TOTAL_TOKENS,
            "max_estimated_usd": str(MAX_ESTIMATED_USD),
        },
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # A failed terminal call is preserved for controller classification; no synthetic success is invented.
    if cp.returncode != 0:
        return cp.returncode
    if not answers:
        return 23
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
