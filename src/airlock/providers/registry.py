from __future__ import annotations

import shutil

# Thin command adapters only. They do not own reasoning loops.
# Users can override every command in .airlock/config.json.
PRESETS = {
    "claude-code": {"binary": "claude", "command": ["claude", "-p", "{prompt}"]},
    "codex": {"binary": "codex", "command": ["codex", "exec", "{prompt}"]},
    "aider": {"binary": "aider", "command": ["aider", "--message", "{prompt}"]},
    "opencode": {"binary": "opencode", "command": ["opencode", "run", "{prompt}"]},
}


def builtin_providers() -> dict:
    out = {}
    for name, spec in PRESETS.items():
        if shutil.which(spec["binary"]):
            out[name] = {"command": spec["command"], "pass_env": []}
    return out


def resolve_provider(config: dict, name: str) -> dict:
    providers = config.get("providers", {})
    if name in providers:
        return providers[name]
    if name in PRESETS and shutil.which(PRESETS[name]["binary"]):
        return {"command": PRESETS[name]["command"], "pass_env": []}
    raise ValueError(
        f"unknown/unavailable model adapter '{name}'. Add providers.{name} to .airlock/config.json"
    )
