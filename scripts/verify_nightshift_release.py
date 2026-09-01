from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


REQUIRED = (
    "AIRLOCK_NIGHTSHIFT_001_HANDOFF.json",
    "src/airlock/nightshift.py",
    "src/airlock/providers/registry.py",
    "docs/NIGHTSHIFT.md",
    "docs/AIRLOCK_HERMES_WORKER_001.md",
    "schemas/nightshift-context-v1.schema.json",
    "tests/test_nightshift.py",
    "tests/test_hermes_provider.py",
)


def verify(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    for relative in REQUIRED:
        if not (root / relative).is_file():
            errors.append(f"missing {relative}")

    registry = (root / "src/airlock/providers/registry.py").read_text()
    if '"hermes", "-z", "{prompt}"' not in registry:
        errors.append("Hermes preset lost scripted -z interface")
    if '"pass_env": ["HERMES_HOME"]' not in registry:
        errors.append("Hermes preset lost HERMES_HOME-only ambient forwarding")
    if "at most one explicitly named provider credential" not in registry:
        errors.append("Hermes credential-buffet guard is missing")

    nightshift = (root / "src/airlock/nightshift.py").read_text()
    if "parallel Hermes competition requires one explicitly isolated profile per attempt" not in nightshift:
        errors.append("Nightshift lost parallel profile-isolation guard")
    if '"worker_state_controls_promotion": False' not in nightshift:
        errors.append("Nightshift lost worker/promotion separation")

    entry = (root / "src/airlock/entry.py").read_text()
    cli = (root / "src/airlock/cli.py").read_text()
    if '("nightshift",' not in entry or 'raw[0] == "nightshift"' not in cli:
        errors.append("public CLI does not expose airlock nightshift")

    try:
        schema = json.loads((root / "schemas/nightshift-context-v1.schema.json").read_text())
    except Exception as exc:
        errors.append(f"invalid Nightshift schema JSON: {exc}")
        schema = {}
    if schema.get("properties", {}).get("schema", {}).get("const") != "airlock.nightshift.context.v1":
        errors.append("Nightshift context schema lost its frozen name")

    readme = (root / "README.md").read_text()
    for phrase in (
        "airlock nightshift",
        "Parallel Hermes attempts require one distinct profile per candidate",
        "cannot redefine the protected objective",
    ):
        if phrase not in readme:
            errors.append(f"README lost Nightshift boundary: {phrase}")

    docs = (root / "docs/NIGHTSHIFT.md").read_text()
    if "not a sub-second live feasibility controller" not in docs:
        errors.append("Nightshift docs lost the dynamical-clock claim boundary")
    if "fake executable named `hermes`" not in docs:
        errors.append("Nightshift docs lost the external-process proof boundary")

    workflow = (root / ".github/workflows/ci.yml").read_text()
    if "verify_nightshift_release.py" not in workflow or "airlock nightshift --help" not in workflow:
        errors.append("CI does not exercise Nightshift release/help surfaces")

    try:
        handoff = json.loads((root / "AIRLOCK_NIGHTSHIFT_001_HANDOFF.json").read_text())
    except Exception as exc:
        errors.append(f"invalid Nightshift handoff JSON: {exc}")
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
        print("Airlock Nightshift release check: FAIL", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Airlock Nightshift release check: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
