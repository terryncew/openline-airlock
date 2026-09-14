#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
MANIFEST = json.loads((HERE / "upstream_manifest.json").read_text())
OVERLAY = HERE / "overlay"


def git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or f"git {' '.join(args)} failed")
    return p.stdout.strip()


def verify_exact_upstream(repo: Path) -> None:
    head = git(repo, "rev-parse", "HEAD")
    if head != MANIFEST["commit"]:
        raise RuntimeError(f"expected exact karpathy/autoresearch pin {MANIFEST['commit']}; observed {head}")
    for path, expected in sorted(MANIFEST["blobs"].items()):
        actual = git(repo, "rev-parse", f"HEAD:{path}")
        if actual != expected:
            raise RuntimeError(f"upstream blob mismatch for {path}: {actual} != {expected}")


def copy_overlay(repo: Path) -> list[str]:
    copied: list[str] = []
    for source in sorted(p for p in OVERLAY.rglob("*") if p.is_file()):
        rel = source.relative_to(OVERLAY)
        dest = repo / rel
        if dest.exists():
            raise RuntimeError(f"refusing to overwrite existing operator file: {rel}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        copied.append(rel.as_posix())
    return copied


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    verify_exact_upstream(repo)
    copied = copy_overlay(repo)
    if args.commit:
        git(repo, "add", "--", *copied)
        git(repo, "commit", "-m", "openline: install receiver-owned autoresearch gate")
    print(json.dumps({
        "upstream_pin": MANIFEST["commit"],
        "copied": copied,
        "bootstrap_commit": git(repo, "rev-parse", "HEAD"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
