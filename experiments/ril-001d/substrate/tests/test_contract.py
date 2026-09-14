from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from protected.benchmark import generate_tasks, score_policy, validate_policy_source  # noqa: E402


def main() -> int:
    policy = ROOT / "mutable" / "generator.py"
    validate_policy_source(policy)
    tasks = generate_tasks("RIL001-CONTRACT", per_kind=2)
    score, outcomes = score_policy(policy, tasks)
    assert score.total == 12
    assert len(outcomes) == 12
    assert set(score.by_kind) == {"bug", "performance", "constraint", "flaky", "migration", "cleanup"}
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
