from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Iterable


def canonical_json_bytes(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def run(argv: list[str], cwd: Path, *, env: dict[str, str] | None = None, timeout: int | None = None) -> dict:
    started = time.monotonic()
    try:
        cp = subprocess.run(
            argv,
            cwd=str(cwd),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return {
            "argv": argv,
            "exit_code": cp.returncode,
            "stdout": cp.stdout,
            "stderr": cp.stderr,
            "duration_seconds": round(time.monotonic() - started, 6),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "argv": argv,
            "exit_code": 124,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "duration_seconds": round(time.monotonic() - started, 6),
            "timed_out": True,
        }


def compact_result(result: dict) -> dict:
    return {
        "argv": result["argv"],
        "exit_code": result["exit_code"],
        "duration_seconds": result["duration_seconds"],
        "timed_out": result["timed_out"],
        "stdout_sha256": sha256_bytes(result["stdout"].encode()),
        "stderr_sha256": sha256_bytes(result["stderr"].encode()),
        "stdout_tail": result["stdout"][-2000:],
        "stderr_tail": result["stderr"][-2000:],
    }


def parse_command(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return [str(x) for x in value]
    return shlex.split(value)


def expand(parts: Iterable[str], values: dict[str, str]) -> list[str]:
    return [str(p).format(**values) for p in parts]


def matches_any(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) or path == pattern.rstrip("/") for pattern in patterns)


def scrub_agent_env(pass_env: Iterable[str], *, home: Path, extra: dict[str, str]) -> dict[str, str]:
    forbidden_exact = {"GITHUB_TOKEN", "GH_TOKEN", "SSH_AUTH_SOCK", "AIRLOCK_RECEIPT_KEY", "OPENLINE_RELEASE_KEY"}
    forbidden_markers = ("RELEASE_KEY", "DEPLOY_KEY", "SIGNING_KEY")
    env: dict[str, str] = {}
    for key in ("PATH", "LANG", "LC_ALL", "TZ", "SYSTEMROOT", "WINDIR", "PATHEXT"):
        if key in os.environ:
            env[key] = os.environ[key]
    for key in pass_env:
        up = key.upper()
        if up in forbidden_exact or any(marker in up for marker in forbidden_markers):
            continue
        if key in os.environ:
            env[key] = os.environ[key]
    home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "remote.origin.pushurl"
    env["GIT_CONFIG_VALUE_0"] = "disabled://airlock-agent-no-push"
    env["AIRLOCK_RELEASE_AUTHORITY"] = "ABSENT"
    env.update(extra)
    return env
