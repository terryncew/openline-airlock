"""Prompt construction and method-delta application.

The method text is a procedure the worker model follows. The COMPLETE
rendered inherited method (all retained instructions + deltas) is capped
at 1,500 counted tokens -- enforced in apply_delta, never truncated.
"""
from __future__ import annotations

from . import tokens

METHOD_TOKEN_CAP = 1500

BASE_METHOD = """\
You fix one small Python module. Follow this procedure exactly.

1. READ. Read the task statement, the target file, and the visible tests
   once. Do not invent requirements beyond the statement.
2. REPRODUCE. Before changing anything, write down the smallest input
   that exposes the defect, using the visible tests as examples.
3. DIAGNOSE. Name the single root cause: one wrong expression, one
   missing case, one wrong boundary. If you cannot name it, say so and
   make the most conservative change consistent with the statement.
4. FIX. Change the target file minimally so the root cause is gone.
   Do not refactor, rename, or add features. Keep every public name
   and signature the target file already has.
5. CHECK. Walk the visible tests against your fixed file by hand.
   Cover the edge case from step 2 explicitly.
6. OUTPUT. Emit ONLY the complete corrected target file inside one
   fenced block marked ```python. No commentary before or after.
   The file must be runnable as-is.
"""

SOLVING_FORMAT_SPEC = """\
Output contract: exactly one fenced block (```python ... ```) containing
the complete corrected target file. Nothing outside the block is read.
"""

PROPOSAL_INSTRUCTIONS = """\
You improve a bug-fixing procedure. You are given the current method and
the outcomes of 3 discovery tasks attempted with it (task, attempted
patch, verdict).

Write ONE method delta that would have helped on the failed cases without
hurting the passed ones. The delta is applied to the current method; the
complete rendered method must stay within 1500 tokens, so keep the delta
tight: replace or add at most a few steps.

Delta format inside one ```delta fenced block, one directive per line:
  REPLACE_STEP <n>: <new step text>
  ADD_STEP: <new step text>
  REMOVE_STEP <n>
Step numbers refer to the numbered steps of the current method.
Emit ONLY the fenced block. No commentary.
"""

PREFLIGHT_INPUT = "Return the exact string OK and nothing else."


def build_solving_prompt(method_text: str, task_packet: str) -> tuple[str, str]:
    tokens.enforce_cap(method_text, METHOD_TOKEN_CAP, "method_text")
    tokens.enforce_cap(task_packet, 3000, "task_packet")
    instructions = method_text.rstrip() + "\n\n" + SOLVING_FORMAT_SPEC
    return instructions, task_packet


def build_proposal_prompt(method_text: str, discovery_feedback: list[str]) -> tuple[str, str]:
    tokens.enforce_cap(method_text, METHOD_TOKEN_CAP, "method_text")
    parts = []
    for i, fb in enumerate(discovery_feedback):
        parts.append(f"--- DISCOVERY {i+1} ---\n" + tokens.truncate_to(fb, 1500))
    body = ("CURRENT METHOD:\n" + method_text + "\n\n"
            + "\n\n".join(parts))
    tokens.enforce_cap(body, 7000, "proposal_input")
    return PROPOSAL_INSTRUCTIONS, body


def build_preflight_prompt() -> tuple[str, str]:
    return "You are a connectivity check.", PREFLIGHT_INPUT


def _digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


def apply_delta(method_text: str, delta_text: str) -> str:
    """Apply a delta to the parent method; return the COMPLETE rendered
    method. Raises tokens.CapExceeded if the rendered result exceeds
    1,500 tokens (no truncation -- the proposal is then rejected).
    Raises ValueError if a directive line is malformed (the proposal
    is then rejected, not crashed)."""
    lines = [l for l in method_text.splitlines()]
    # Split into step blocks: lines starting with "<n>." begin a step.
    steps: list[list[str]] = []
    cur: list[str] = []
    for ln in lines:
        s = ln.strip()
        if s and s[0].isdigit() and len(s) > 1 and s[1] == "." and (len(s) == 2 or s[2] == " "):
            if cur:
                steps.append(cur)
            cur = [ln]
        else:
            cur.append(ln)
    if cur:
        steps.append(cur)

    for raw in delta_text.splitlines():
        ln = raw.strip()
        if not ln:
            continue
        up = ln.upper()
        if up.startswith("REPLACE_STEP"):
            body = ln[len("REPLACE_STEP"):].strip()
            if ":" not in body:
                raise ValueError(f"malformed REPLACE_STEP (no colon): {ln!r}")
            before, after = body.split(":", 1)
            d = _digits(before)
            if d:
                num, new = int(d), after.strip()
            else:
                # tolerate "REPLACE_STEP: <n> <text>"
                toks = after.strip().split(" ", 1)
                d2 = _digits(toks[0]) if toks and toks[0] else ""
                if not d2:
                    raise ValueError(
                        f"malformed REPLACE_STEP (no step number): {ln!r}")
                num = int(d2)
                new = toks[1].strip() if len(toks) > 1 else ""
            if 1 <= num <= len(steps):
                steps[num - 1] = [f"{num}. {new}"]
        elif up.startswith("ADD_STEP"):
            body = ln[len("ADD_STEP"):].strip()
            if not body.startswith(":"):
                raise ValueError(f"malformed ADD_STEP (need ': <text>'): {ln!r}")
            steps.append([f"{len(steps)+1}. {body[1:].strip()}"])
        elif up.startswith("REMOVE_STEP"):
            body = ln[len("REMOVE_STEP"):].strip()
            if body.startswith(":"):
                body = body[1:].strip()
            first = body.split(" ", 1)[0] if body else ""
            d = _digits(first)
            if not d:
                raise ValueError(
                    f"malformed REMOVE_STEP (no step number): {ln!r}")
            num = int(d)
            if 1 <= num <= len(steps):
                del steps[num - 1]
    # Renumber.
    out: list[str] = []
    n = 0
    for st in steps:
        first = st[0].strip()
        # replace leading "<k>." with new number
        dot = first.find(".")
        body = first[dot + 1:].strip() if dot != -1 else first
        n += 1
        out.append(f"{n}. {body}")
        out.extend(st[1:])
    rendered = "\n".join(out)
    tokens.enforce_cap(rendered, METHOD_TOKEN_CAP, "rendered_method")
    return rendered
