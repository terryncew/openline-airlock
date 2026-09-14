from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def load_protocol():
    path = Path(__file__).resolve().parent / "autoresearch-live-003" / "protocol.py"
    spec = importlib.util.spec_from_file_location("autoresearch_live_003_protocol", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load protocol")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
