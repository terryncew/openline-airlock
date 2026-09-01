from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


REQUIRED = (
    "AIRLOCK_CONTINUOUS_IMPROVEMENT_001_HANDOFF.json",
    "src/airlock/improvement.py",
    "docs/CONTINUOUS_IMPROVEMENT.md",
    "examples/objective-test-runtime.json",
    "examples/measure-test-runtime.py",
    "schemas/objective-v1.schema.json",
    "schemas/improvement-generation-v1.schema.json",
    "schemas/improvement-v1.schema.json",
    "tests/test_improvement.py",
)


def verify(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    for relative in REQUIRED:
        if not (root / relative).is_file():
            errors.append(f"missing {relative}")

    for relative in (
        "examples/objective-test-runtime.json",
        "schemas/objective-v1.schema.json",
        "schemas/improvement-generation-v1.schema.json",
        "schemas/improvement-v1.schema.json",
    ):
        try:
            json.loads((root / relative).read_text())
        except Exception as exc:
            errors.append(f"invalid JSON in {relative}: {exc}")

    example = json.loads((root / "examples/objective-test-runtime.json").read_text())
    if example.get("schema") != "airlock.objective.v1":
        errors.append("objective example lost airlock.objective.v1")
    if int(example.get("bounds", {}).get("max_generations", 0)) != 10:
        errors.append("objective example no longer demonstrates ten bounded generations")

    entry = (root / "src" / "airlock" / "entry.py").read_text()
    cli = (root / "src" / "airlock" / "cli.py").read_text()
    if '("improve",' not in entry or 'raw[0] == "improve"' not in cli:
        errors.append("public CLI does not expose airlock improve")

    readme = (root / "README.md").read_text()
    if "Software that can earn its own improvements." not in readme:
        errors.append("README lost the public product promise")
    if "It cannot change what counts as an improvement." not in readme:
        errors.append("README lost the operator-owned objective boundary")
    if "`main` never moves" not in readme:
        errors.append("README lost the isolated-promotion boundary")

    gitignore = (root / ".gitignore").read_text().splitlines()
    if ".airlock/improvements/" not in gitignore:
        errors.append("local improvement receipts are not ignored")

    try:
        handoff = json.loads((root / "AIRLOCK_CONTINUOUS_IMPROVEMENT_001_HANDOFF.json").read_text())
    except Exception as exc:
        errors.append(f"invalid handoff JSON: {exc}")
        handoff = {}
    for relative, expected in handoff.get("files", {}).items():
        path = root / relative
        if not path.is_file():
            errors.append(f"handoff hash target is missing: {relative}")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            errors.append(f"handoff hash mismatch: {relative}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    errors = verify(Path(args.repo))
    if errors:
        print("Airlock continuous-improvement release check: FAIL", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Airlock continuous-improvement release check: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
