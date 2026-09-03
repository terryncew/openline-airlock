from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
import tomllib


FROZEN_VERSION = (0, 3, 0)
CANONICAL = ("init", "solve", "autopilot", "inbox", "review")
SCHEMAS = (
    "airlock.config.v1",
    "airlock.run.v1",
    "airlock.verification.v1",
    "airlock.swarm.v1",
    "airlock.autopilot.v1",
    "airlock.autopilot.run.v1",
    "airlock.inbox.v1",
    "airlock.review.v1",
)


def _version_tuple(value: str | None) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def verify(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []

    pyproject = tomllib.loads((root / "pyproject.toml").read_text())
    package_version = pyproject.get("project", {}).get("version")

    init_text = (root / "src" / "airlock" / "__init__.py").read_text()
    match = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)
    init_version = match.group(1) if match else None

    if package_version != init_version:
        errors.append(
            f"package version {package_version!r} does not match "
            f"airlock.__version__ {init_version!r}"
        )

    parsed = _version_tuple(package_version)
    if parsed is None:
        errors.append(f"package version is not a simple semantic version: {package_version!r}")
    elif parsed < FROZEN_VERSION:
        errors.append(
            f"package version {package_version!r} predates frozen v0.3.0 contract"
        )

    entry = (root / "src" / "airlock" / "entry.py").read_text()
    for command in CANONICAL:
        if f'("{command}",' not in entry:
            errors.append(f"public router does not advertise canonical command {command!r}")

    readme = (root / "README.md").read_text()
    positions = []
    for command in CANONICAL:
        token = f"airlock {command}"
        pos = readme.find(token)
        if pos < 0:
            errors.append(f"README is missing {token!r}")
        positions.append(pos)
    if all(pos >= 0 for pos in positions) and positions != sorted(positions):
        errors.append("README canonical commands are not presented in workflow order")

    changelog = (root / "CHANGELOG.md").read_text()
    frozen_heading = "## 0.3.0 — Autonomous work loop\n"
    if frozen_heading not in changelog:
        errors.append("CHANGELOG lost the frozen 0.3.0 release entry")

    release_doc = (root / "docs" / "AIRLOCK_V0_3_001.md").read_text()
    for schema in SCHEMAS:
        if schema not in release_doc:
            errors.append(f"release schema freeze is missing {schema}")

    checklist = (root / "RELEASE_CHECKLIST.md").read_text()
    if "genuinely separate fork" not in checklist or "/airlock submit" not in checklist:
        errors.append("release checklist lost the public-fork evidence boundary")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    errors = verify(Path(args.repo))
    if errors:
        print("AIRLOCK v0.3 contract verification: FAIL", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("AIRLOCK v0.3 contract verification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
