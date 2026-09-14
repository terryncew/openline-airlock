from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from protected.benchmark import generate_tasks, score_policy, validate_policy_source  # noqa: E402

POLICY = ROOT / "mutable" / "generator.py"
validate_policy_source(POLICY)
tasks = generate_tasks("RIL001-SMOKE", per_kind=1)
score, _ = score_policy(POLICY, tasks)
if score.total != 6:
    raise SystemExit(2)
print(score.to_dict())
