"""Q6 static checks: syntax, line budgets, importability."""

import ast
from pathlib import Path

Q6_DIR = Path(__file__).resolve().parent.parent

FILES = {
    "q6_recorder.py": 200,
    "q6_adapter.py": 200,
    "q6_runner.py": 80,
    # Q6 binding layer: full receipt shape + 12-check verifier +
    # production verifier.
    "q6_receipt.py": 500,
    # Q6 Stage-1 qualification wrapper: Q6 preflight, qualifier
    # binding, arm, qualify orchestration, verifier factory, CLI.
    "q6_stage1.py": 500,
}


def test_syntax_and_line_budgets():
    for name, budget in FILES.items():
        src = (Q6_DIR / name).read_text()
        ast.parse(src)  # raises on syntax error
        lines = src.splitlines()
        assert len(lines) <= budget, f"{name}: {len(lines)} > {budget}"
        long = [i + 1 for i, l in enumerate(lines) if len(l) > 79]
        assert not long, f"{name}: lines over 79 chars: {long}"


def test_manifest_is_valid_json():
    import json
    m = json.loads((Q6_DIR / "execution_manifest.json").read_text())
    assert m["schema"] == "airlock.rsi-006-q6.execution-manifest.v1"
    assert isinstance(m["code_files"], list) and m["code_files"]


def test_modules_import():
    import q6_testkit  # noqa: F401  (sets up sys.path)
    import q6_recorder
    import q6_adapter
    import q6_runner
    import q6_receipt
    assert q6_recorder.CONFIG_SCHEMA.startswith("airlock.rsi-006-q6.")
    assert q6_adapter.SEAL_SCHEMA.startswith("airlock.rsi-006-q6.")
    assert q6_receipt.RECEIPT_SCHEMA.startswith("airlock.rsi-006-q6.")
    assert issubclass(q6_adapter.Q6Coordinator,
                      __import__("q5_adapter").Coordinator)
