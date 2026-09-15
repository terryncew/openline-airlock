"""RSI-006-Q3 shared repository pool (environment facts only).

The four pinned repositories, unchanged from RSI-006-Q / Q2. This module
carries no seeds, budgets, thresholds, or scientific constants: it is
imported by both Stage 1 (environment qualification) and Stage 2
(scientific contact) so the two stages cannot drift on the pool definition.
"""

from __future__ import annotations

POOL = [
    {
        "name": "more-itertools",
        "url": "https://github.com/more-itertools/more-itertools.git",
        "sha": "b2f3aff7633057d234ec9186c18a53f4df306d08",
        "pkg": "more_itertools",
        "src_layout": False,
        "tests": "tests",
    },
    {
        "name": "cachetools",
        "url": "https://github.com/tkem/cachetools.git",
        "sha": "4500e3d04288738d25acbb4973eb3c3e1bf41db9",
        "pkg": "cachetools",
        "src_layout": True,
        "tests": "tests",
    },
    {
        "name": "boltons",
        "url": "https://github.com/mahmoud/boltons.git",
        "sha": "961dcff3f42e73b245aef65e377fe82763b257bb",
        "pkg": "boltons",
        "src_layout": False,
        "tests": "tests",
    },
    {
        "name": "pluggy",
        "url": "https://github.com/pytest-dev/pluggy.git",
        "sha": "0a4974175aa2d873f401345b151297af2e74c851",
        "pkg": "pluggy",
        "src_layout": True,
        "tests": "testing",
    },
]

# Minimal test-execution dependencies for the untouched baselines.
# Stage 1 verifies these are importable (installing them if authorized to)
# and freezes exact versions into the environment receipt.
REQUIRED_PACKAGES = ("pytest",)
