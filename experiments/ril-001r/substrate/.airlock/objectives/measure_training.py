from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from protected.benchmark import generate_tasks, score_policy, validate_policy_source  # noqa: E402

TRAINING_SEED = "RIL001-FROZEN-TRAINING-V1"
TASKS_PER_KIND = 8
POLICY = ROOT / "mutable" / "generator.py"

try:
    guard = validate_policy_source(POLICY)
    tasks = generate_tasks(TRAINING_SEED, per_kind=TASKS_PER_KIND)
    score, _ = score_policy(POLICY, tasks)
    print(json.dumps({"value": score.successes, "score": score.to_dict(), "policy_guard": guard}, sort_keys=True))
except Exception as exc:
    print(json.dumps({"error": type(exc).__name__, "detail": str(exc)[-500:]}, sort_keys=True))
    raise SystemExit(2)
