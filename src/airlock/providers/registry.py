from __future__ import annotations

import re
import shutil
from pathlib import Path

# Thin command adapters only. They do not own reasoning loops.
# Users can override every command in .airlock/config.json.
PRESETS = {
    "claude-code": {"binary": "claude", "command": ["claude", "-p", "{prompt}"], "pass_env": []},
    "codex": {"binary": "codex", "command": ["codex", "exec", "{prompt}"], "pass_env": []},
    "aider": {"binary": "aider", "command": ["aider", "--message", "{prompt}"], "pass_env": []},
    "opencode": {"binary": "opencode", "command": ["opencode", "run", "{prompt}"], "pass_env": []},
    "hermes": {"binary": "hermes", "command": ["hermes", "-z", "{prompt}"], "pass_env": ["HERMES_HOME"]},
}

_HERMES_PROFILE_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_HERMES_NON_SECRET_CONTEXT = frozenset({
    "HERMES_COMMIT",
    "HERMES_VERSION",
    "SEARCH004_USAGE_FILE",
})


def _preset_provider(name: str) -> dict:
    spec = PRESETS[name]
    return {
        "command": list(spec["command"]),
        "pass_env": list(spec.get("pass_env", [])),
    }


def _validate_hermes_provider(provider: dict) -> dict:
    command = provider.get("command")
    if not isinstance(command, list) or not command or any(not isinstance(part, str) or not part for part in command):
        raise ValueError("providers.hermes.command must be a non-empty argv array")
    pass_env = provider.get("pass_env", [])
    if not isinstance(pass_env, list) or any(not isinstance(key, str) or not key.strip() for key in pass_env):
        raise ValueError("providers.hermes.pass_env must be a list of environment variable names")

    # The built-in adapter may forward its state root plus the narrow,
    # non-secret controller metadata used to bind an experimental run. A
    # maintainer may also explicitly name one provider credential in protected
    # Airlock config. Refuse credential buffets rather than guessing which
    # secrets a model runtime might want.
    credentials = list(dict.fromkeys(
        key for key in pass_env
        if key != "HERMES_HOME" and key not in _HERMES_NON_SECRET_CONTEXT
    ))
    if len(credentials) > 1:
        raise ValueError(
            "providers.hermes.pass_env may contain approved non-secret controller context "
            "plus at most one explicitly named provider credential"
        )
    return provider


def _split_hermes_alias(name: str) -> tuple[bool, str | None]:
    if name == "hermes":
        return True, None
    if not name.startswith("hermes@"):
        return False, None
    profile = name.split("@", 1)[1]
    if not profile or not _HERMES_PROFILE_RE.fullmatch(profile):
        raise ValueError("Hermes profile names must contain only letters, numbers, hyphens, or underscores")
    return True, profile


def _profiled_hermes(provider: dict, profile: str | None) -> dict:
    _validate_hermes_provider(provider)
    provider = {
        **provider,
        "command": list(provider.get("command", [])),
        "pass_env": list(provider.get("pass_env", [])),
    }
    if profile is None:
        return provider

    command = list(provider["command"])
    if Path(command[0]).name != "hermes":
        raise ValueError(
            "Hermes profile isolation requires a direct hermes command; custom wrappers must define separate providers explicitly"
        )
    # Hermes profiles are isolated persistent instances. Put the global profile
    # selector immediately after the executable and leave scripted -z intact.
    command[1:1] = ["-p", profile]
    provider["command"] = command
    provider["hermes_profile"] = profile
    return provider


def builtin_providers() -> dict:
    out = {}
    for name, spec in PRESETS.items():
        if shutil.which(spec["binary"]):
            provider = _preset_provider(name)
            out[name] = _profiled_hermes(provider, None) if name == "hermes" else provider
    return out


def resolve_provider(config: dict, name: str) -> dict:
    is_hermes, profile = _split_hermes_alias(name)
    if is_hermes:
        providers = config.get("providers", {})
        if "hermes" in providers:
            provider = providers["hermes"]
            if not isinstance(provider, dict):
                raise ValueError("providers.hermes must be an object")
            return _profiled_hermes(provider, profile)
        if shutil.which(PRESETS["hermes"]["binary"]):
            return _profiled_hermes(_preset_provider("hermes"), profile)
        raise ValueError(
            "unknown/unavailable model adapter 'hermes'. Add providers.hermes to .airlock/config.json"
        )

    providers = config.get("providers", {})
    if name in providers:
        provider = providers[name]
        if not isinstance(provider, dict):
            raise ValueError(f"providers.{name} must be an object")
        return provider
    if name in PRESETS and shutil.which(PRESETS[name]["binary"]):
        return _preset_provider(name)
    raise ValueError(
        f"unknown/unavailable model adapter '{name}'. Add providers.{name} to .airlock/config.json"
    )
