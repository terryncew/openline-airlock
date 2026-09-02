from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Iterable

from .util import canonical_json_bytes, sha256_bytes, sha256_file


HERMES_HARNESS_SCHEMA = "airlock.hermes-harness-fingerprint.v1"
HERMES_HARNESS_SET_SCHEMA = "airlock.hermes-harness-set.v1"

# Deliberately narrow for the first implementation. These surfaces can change
# how Hermes behaves in scripted CLI work without dragging credentials, session
# transcripts, caches, or database churn into the identity.
_TRACKED_ROOT_FILES = ("config.yaml", "SOUL.md")
_TRACKED_DIRS = ("skills", "tools", "memories", "hooks", "context")
_EXCLUDED_DIR_NAMES = {
    ".cache",
    "__pycache__",
    "backups",
    "cache",
    "checkpoints",
    "home",
    "logs",
    "sessions",
    "state-snapshots",
    "tmp",
}
_EXCLUDED_FILE_NAMES = {
    ".env",
    ".DS_Store",
    "auth.json",
    "state.db",
}
_EXCLUDED_SUFFIXES = (
    ".db",
    ".db-shm",
    ".db-wal",
    ".key",
    ".pem",
    ".sqlite",
    ".sqlite3",
    ".token",
)
_SECRET_KEY = re.compile(
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|credential|private[_-]?key)",
    re.IGNORECASE,
)
_YAML_KEY = re.compile(r"^(?P<indent>\s*)(?P<key>[^:#\n]+?):(?P<value>.*)$")
_HEX_COMMIT = re.compile(r"^[0-9a-fA-F]{7,64}$")


class HarnessFingerprintError(RuntimeError):
    """The controller could not establish a deterministic Hermes harness identity."""


def _profile_name(model: str) -> str | None:
    if model == "hermes":
        return None
    if model.startswith("hermes@"):
        value = model.split("@", 1)[1]
        return value or None
    raise HarnessFingerprintError(f"unsupported harness fingerprint model {model!r}")


def hermes_home(model: str, *, env: dict[str, str] | None = None) -> Path:
    """Resolve the state root Hermes will use for this Airlock worker identity."""
    source = os.environ if env is None else env
    base = Path(source.get("HERMES_HOME") or (Path.home() / ".hermes")).expanduser()
    profile = _profile_name(model)
    if profile is None:
        return base.resolve()

    # Hermes profiles are separate HERMES_HOME trees under profiles/<name>.
    # If the caller already supplied that exact profile as HERMES_HOME, preserve it.
    if base.name == profile and base.parent.name == "profiles":
        return base.resolve()
    return (base / "profiles" / profile).resolve()


def _excluded(relative: Path) -> bool:
    if any(part in _EXCLUDED_DIR_NAMES for part in relative.parts[:-1]):
        return True
    name = relative.name
    if name in _EXCLUDED_FILE_NAMES:
        return True
    lowered = name.lower()
    if any(lowered.endswith(suffix) for suffix in _EXCLUDED_SUFFIXES):
        return True
    if _SECRET_KEY.search(name):
        return True
    return False


def _sanitized_config_bytes(path: Path) -> bytes:
    """Hash behavior-bearing config while removing credential values and comments.

    Hermes documents config.yaml as configuration, but installations may still
    contain provider secret fields. Credential rotation must not create a new
    harness identity, and Airlock must never persist a verifier of the secret.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HarnessFingerprintError("Hermes config.yaml must be UTF-8 to fingerprint safely") from exc

    normalized: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _YAML_KEY.match(line)
        if match and _SECRET_KEY.search(match.group("key").strip()):
            line = f'{match.group("indent")}{match.group("key").rstrip()}: <redacted>'
        normalized.append(line)
    return ("\n".join(normalized) + ("\n" if normalized else "")).encode("utf-8")


def _symlink_record(path: Path, relative: Path) -> dict:
    target = os.readlink(path)
    record = {
        "path": relative.as_posix(),
        "kind": "symlink",
        "target_sha256": sha256_bytes(target.encode("utf-8")),
    }
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        record["resolved_present"] = False
        return record
    record["resolved_present"] = True
    if resolved.is_file():
        record["resolved_kind"] = "file"
        record["resolved_sha256"] = sha256_file(resolved)
        record["resolved_size_bytes"] = resolved.stat().st_size
    else:
        record["resolved_kind"] = "non_file"
    return record


def _file_record(home: Path, path: Path) -> dict:
    relative = path.relative_to(home)
    if path.is_symlink():
        return _symlink_record(path, relative)
    if relative.as_posix() == "config.yaml":
        payload = _sanitized_config_bytes(path)
        return {
            "path": relative.as_posix(),
            "kind": "file",
            "normalization": "yaml-comments-removed-secret-values-redacted",
            "sha256": sha256_bytes(payload),
            "size_bytes": len(payload),
        }
    return {
        "path": relative.as_posix(),
        "kind": "file",
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _tracked_state(home: Path) -> list[dict]:
    candidates: list[Path] = []
    for name in _TRACKED_ROOT_FILES:
        path = home / name
        if path.is_file() or path.is_symlink():
            candidates.append(path)
    for dirname in _TRACKED_DIRS:
        root = home / dirname
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not (path.is_file() or path.is_symlink()):
                continue
            relative = path.relative_to(home)
            if not _excluded(relative):
                candidates.append(path)
    return [_file_record(home, path) for path in sorted(set(candidates), key=lambda p: p.relative_to(home).as_posix())]


def _source_identity(home: Path, *, env: dict[str, str] | None = None) -> dict:
    source = os.environ if env is None else env
    declared_commit = source.get("HERMES_COMMIT")
    if declared_commit and not _HEX_COMMIT.fullmatch(declared_commit):
        declared_commit = None

    checkout = home / "hermes-agent"
    git_commit = None
    version = source.get("HERMES_VERSION") or None
    if checkout.is_dir():
        try:
            cp = subprocess.run(
                ["git", "-C", str(checkout), "rev-parse", "HEAD"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
            value = cp.stdout.strip()
            if cp.returncode == 0 and _HEX_COMMIT.fullmatch(value):
                git_commit = value.lower()
        except (OSError, subprocess.TimeoutExpired):
            pass
        pyproject = checkout / "pyproject.toml"
        if version is None and pyproject.is_file():
            try:
                parsed = tomllib.loads(pyproject.read_text())
                raw = parsed.get("project", {}).get("version")
                if isinstance(raw, str) and raw.strip():
                    version = raw.strip()
            except (OSError, tomllib.TOMLDecodeError):
                pass

    binary = shutil.which("hermes", path=source.get("PATH"))
    binary_sha = None
    binary_name = None
    if binary:
        binary_path = Path(binary).resolve()
        if binary_path.is_file():
            binary_sha = sha256_file(binary_path)
            binary_name = binary_path.name

    return {
        "version": version,
        "source_commit": git_commit or (declared_commit.lower() if declared_commit else None),
        "source_commit_observed_from_git": git_commit is not None,
        "source_commit_declared_by_environment": declared_commit.lower() if declared_commit else None,
        "executable_name": binary_name,
        "executable_sha256": binary_sha,
    }




def _normalized_config_payload(home: Path) -> bytes | None:
    path = home / "config.yaml"
    if not path.is_file():
        return None
    return _sanitized_config_bytes(path)


def _requested_model(home: Path) -> tuple[str | None, str | None]:
    """Best-effort requested LLM identity from non-secret Hermes config.

    This is deliberately descriptive rather than authoritative: an adapter may
    route again at runtime. The receipt separately records any effective model
    the worker reports after execution.
    """
    payload = _normalized_config_payload(home)
    if payload is None:
        return None, None
    keys = {"model", "model_name", "llm_model", "default_model"}
    for raw in payload.decode("utf-8").splitlines():
        match = _YAML_KEY.match(raw)
        if not match:
            continue
        key = match.group("key").strip().lower()
        if key not in keys:
            continue
        value = match.group("value").strip()
        if not value or value in {"{}", "[]", "null", "~"}:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value, f"config.yaml:{key}"
    return None, None


def _tool_registry(files: list[dict]) -> dict:
    records = [
        {k: row[k] for k in sorted(row) if k not in {"normalization"}}
        for row in files
        if str(row.get("path", "")).startswith("tools/")
    ]
    basis = {"files": records}
    return {
        "tracked_tool_files": len(records),
        "fingerprint_sha256": sha256_bytes(canonical_json_bytes(basis)),
    }


def fingerprint_hermes_harness(
    model: str,
    provider: dict,
    *,
    env: dict[str, str] | None = None,
) -> dict:
    """Return a deterministic, non-secret snapshot of the Hermes harness state."""
    home = hermes_home(model, env=env)
    profile = _profile_name(model)
    files = _tracked_state(home) if home.is_dir() else []
    requested_model, requested_model_source = _requested_model(home)
    tool_registry = _tool_registry(files)
    routing_basis = {
        "requested_model": requested_model,
        "requested_model_source": requested_model_source,
        "adapter_command": list(provider.get("command", [])),
        "tool_registry_sha256": tool_registry["fingerprint_sha256"],
    }
    routing = {
        **routing_basis,
        "tool_registry": tool_registry,
        "fingerprint_sha256": sha256_bytes(canonical_json_bytes(routing_basis)),
        "effective_model_note": (
            "The requested model is configuration state. The effective model is recorded per attempt "
            "from post-execution worker evidence when available; absence is preserved as unknown."
        ),
    }
    identity = {
        "schema": HERMES_HARNESS_SCHEMA,
        "worker": "hermes",
        "airlock_model": model,
        "hermes_profile": profile or "default",
        "adapter_command": list(provider.get("command", [])),
        "adapter_pass_env": sorted(str(value) for value in provider.get("pass_env", [])),
        "routing": routing,
        "runtime": _source_identity(home, env=env),
        "state_root_present": home.is_dir(),
        "tracked_files": files,
        "tracked_file_count": len(files),
        "tracked_bytes": sum(int(row.get("size_bytes", 0)) for row in files),
        "tracked_surfaces": {
            "root_files": list(_TRACKED_ROOT_FILES),
            "directories": list(_TRACKED_DIRS),
        },
        "excluded_surfaces": {
            "credential_files": [".env", "auth.json", "*token*", "*secret*", "*credential*", "*.key", "*.pem"],
            "transient_directories": sorted(_EXCLUDED_DIR_NAMES),
            "databases_and_runtime_state": ["state.db", "*.db", "*.sqlite", "*.sqlite3"],
        },
        "claim_boundary": (
            "This fingerprint binds deterministic non-secret Hermes runtime/config/instruction/skill/tool/memory state, "
            "including requested model routing and the tracked tool registry. It deliberately excludes credentials, "
            "session transcripts, logs, caches, databases, checkpoints, and profile HOME."
        ),
    }
    fingerprint = sha256_bytes(canonical_json_bytes(identity))
    return {**identity, "fingerprint_sha256": fingerprint}


def fingerprint_harness_set(
    models: Iterable[str],
    providers: Iterable[dict],
    *,
    env: dict[str, str] | None = None,
) -> dict:
    workers = [
        fingerprint_hermes_harness(model, provider, env=env)
        for model, provider in zip(models, providers, strict=True)
    ]
    basis = {
        "schema": HERMES_HARNESS_SET_SCHEMA,
        "workers": [
            {
                "airlock_model": row["airlock_model"],
                "hermes_profile": row["hermes_profile"],
                "fingerprint_sha256": row["fingerprint_sha256"],
            }
            for row in workers
        ],
    }
    return {
        **basis,
        "workers": workers,
        "fingerprint_sha256": sha256_bytes(canonical_json_bytes(basis)),
    }
