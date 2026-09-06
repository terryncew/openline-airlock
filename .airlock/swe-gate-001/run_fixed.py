from __future__ import annotations

from collections import defaultdict
import importlib.util
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
RUN_PATH = HERE / "run.py"

spec = importlib.util.spec_from_file_location("airlock_swe_gate_001_original", RUN_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"could not load {RUN_PATH}")
original = importlib.util.module_from_spec(spec)
spec.loader.exec_module(original)


def _actual_test_pass(value: Any) -> bool | None:
    """Read both SWE-Gate validation-matrix schemas at the pinned commit."""
    if isinstance(value, bool):
        return value
    if not isinstance(value, dict):
        return None

    returncode = value.get("returncode")
    if isinstance(returncode, int) and not isinstance(returncode, bool):
        return returncode == 0

    actual_pass = value.get("actual_pass")
    if isinstance(actual_pass, bool):
        return actual_pass

    expected_pass = value.get("expected_pass")
    validated = value.get("passed")
    if isinstance(expected_pass, bool) and validated is True:
        return expected_pass

    return None


def eligible_instances(
    swe_gate_root: Path,
    seed: str,
    repo_count: int,
) -> list[dict[str, Any]]:
    """Original deterministic selection with schema-compatible truth parsing."""
    instances_root = swe_gate_root / "data" / "instances"
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    expected_truth = {
        "noncompliant_functional": True,
        "noncompliant_constraint": False,
        "gold_functional": True,
        "gold_constraint": True,
    }

    for instance_dir in sorted(instances_root.iterdir()):
        swe_if = instance_dir / "swe_if"
        validation_path = swe_if / "validation_matrix.json"
        metadata_path = swe_if / "metadata.json"
        docker_build_path = instance_dir / "docker_build.json"
        required = [
            validation_path,
            metadata_path,
            docker_build_path,
            swe_if / "diff_not_follow_constraint.patch",
            swe_if / "gold.patch",
        ]
        if not all(path.exists() for path in required):
            continue

        try:
            validation = json.loads(validation_path.read_text())
            metadata = json.loads(metadata_path.read_text())
            docker_build = json.loads(docker_build_path.read_text())
        except Exception:
            continue

        truth = {
            key: _actual_test_pass(validation.get(key))
            for key in expected_truth
        }
        if truth != expected_truth:
            continue

        repo_id = str(metadata.get("repo_id") or "").strip()
        instance_id = str(metadata.get("instance_id") or instance_dir.name).strip()
        image = str(docker_build.get("image") or "").strip()
        base_image = str(docker_build.get("base_image") or "").strip()
        if not repo_id or not instance_id or not image or not base_image:
            continue

        grouped[repo_id].append(
            {
                "repo_id": repo_id,
                "instance_id": instance_id,
                "image": image,
                "base_image": base_image,
                "released_validation": truth,
                "instance_rank": original.sha_rank(
                    seed, "instance", repo_id, instance_id
                ),
            }
        )

    representatives: list[dict[str, Any]] = []
    for repo_id, rows in grouped.items():
        rows.sort(key=lambda row: (row["instance_rank"], row["instance_id"]))
        chosen = dict(rows[0])
        chosen["repo_rank"] = original.sha_rank(seed, "repo", repo_id)
        representatives.append(chosen)

    representatives.sort(key=lambda row: (row["repo_rank"], row["repo_id"]))
    selected = representatives[:repo_count]
    if len(selected) != repo_count:
        raise RuntimeError(
            f"only {len(selected)} eligible distinct repos; need {repo_count}"
        )
    return selected


# Infrastructure-only repair. Preserve run.py's preregistered evaluator and
# downstream behavior; replace only the released-matrix parser that crashed
# before selection.json could be frozen.
original.eligible_instances = eligible_instances


if __name__ == "__main__":
    raise SystemExit(original.main())
