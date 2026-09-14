"""Intentionally mediocre search-policy generator for RIL-001.

This policy does not edit code. It chooses up to five receiver-defined search tactics that the
protected worker turns into bounded guidance for the live agent. Accepted changes to this file
therefore change how later live-agent opportunities search for improvements.
"""
from __future__ import annotations


def choose_tactics(context):
    # Generic starting policy: sensible, but deliberately insensitive to the kind of work.
    return [
        "inspect_repo",
        "run_baseline",
        "small_patch",
        "preserve_invariants",
    ]
