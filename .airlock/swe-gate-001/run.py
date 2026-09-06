from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any


def run(argv: list[str], cwd: Path, timeout: int) -> dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return {
            "argv": argv,
            "returncode": proc.returncode,
            "timed_out": False,
            "duration_seconds": round(time.time() - started, 3),
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "argv": argv,
            "returncode": 124,
            "timed_out": True,
            "duration_seconds": round(time.time() - started, 3),
            "stdout": exc.stdout if isinstance(exc.stdout, str) else "",
            "stderr": exc.stderr if isinstance(exc.stderr, str) else "",
        }


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def parse_last_json(stdout: str) -> dict[str, Any]:
    for raw in reversed(stdout.splitlines()):
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return {"parse_error": "no_json_object_in_stdout"}


def sha_rank(seed: str, *parts: str) -> str:
    return hashlib.sha256("|".join([seed, *parts]).encode()).hexdigest()


def eligible_instances(swe_gate_root: Path, seed: str, repo_count: int) -> list[dict[str, Any]]:
    instances_root = swe_gate_root / "data" / "instances"
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

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
            "noncompliant_functional": bool((validation.get("noncompliant_functional") or {}).get("passed")),
            "noncompliant_constraint": bool((validation.get("noncompliant_constraint") or {}).get("passed")),
            "gold_functional": bool((validation.get("gold_functional") or {}).get("passed")),
            "gold_constraint": bool((validation.get("gold_constraint") or {}).get("passed")),
        }
        if truth != {
            "noncompliant_functional": True,
            "noncompliant_constraint": False,
            "gold_functional": True,
            "gold_constraint": True,
        }:
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
                "instance_rank": sha_rank(seed, "instance", repo_id, instance_id),
            }
        )

    representatives: list[dict[str, Any]] = []
    for repo_id, rows in grouped.items():
        rows.sort(key=lambda row: (row["instance_rank"], row["instance_id"]))
        chosen = dict(rows[0])
        chosen["repo_rank"] = sha_rank(seed, "repo", repo_id)
        representatives.append(chosen)

    representatives.sort(key=lambda row: (row["repo_rank"], row["repo_id"]))
    selected = representatives[:repo_count]
    if len(selected) != repo_count:
        raise RuntimeError(f"only {len(selected)} eligible distinct repos; need {repo_count}")
    return selected


def external_truth(image: str, patch: str, cwd: Path) -> dict[str, Any]:
    proc = run(["docker", "run", "--rm", image, patch], cwd, timeout=1800)
    parsed = parse_last_json(proc.get("stdout") or "")
    return {
        "process": {
            "returncode": proc["returncode"],
            "timed_out": proc["timed_out"],
            "duration_seconds": proc["duration_seconds"],
            "stderr_tail": (proc.get("stderr") or "")[-4000:],
        },
        "result": parsed,
    }


def truth_ok(noncompliant: dict[str, Any], gold: dict[str, Any]) -> bool:
    n = noncompliant.get("result") or {}
    g = gold.get("result") or {}
    return (
        n.get("patch_apply_passed") is True
        and n.get("functional_test_passed") is True
        and n.get("constraint_test_passed") is False
        and g.get("patch_apply_passed") is True
        and g.get("functional_test_passed") is True
        and g.get("constraint_test_passed") is True
    )


def airlock_eval(image: str, instance_id: str, airlock_root: Path, cwd: Path) -> dict[str, Any]:
    script = "/airlock-src/.airlock/swe-gate-001/evaluate_inside.py"
    proc = run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "python",
            "-e",
            "PYTHONPATH=/airlock-src/src",
            "-v",
            f"{airlock_root.resolve()}:/airlock-src:ro",
            image,
            script,
            "--instance-id",
            instance_id,
        ],
        cwd,
        timeout=3600,
    )
    return {
        "process": {
            "returncode": proc["returncode"],
            "timed_out": proc["timed_out"],
            "duration_seconds": proc["duration_seconds"],
            "stderr_tail": (proc.get("stderr") or "")[-4000:],
        },
        "result": parse_last_json(proc.get("stdout") or ""),
    }


def remove_image(image: str, cwd: Path) -> None:
    if image:
        run(["docker", "image", "rm", "-f", image], cwd, timeout=300)


def verdict(rows: list[dict[str, Any]]) -> str:
    if any(row.get("status") == "EXTERNAL_TRUTH_DRIFT" for row in rows):
        return "INCONCLUSIVE_EXTERNAL_TRUTH_DRIFT"
    if any(row.get("status") == "AIRLOCK_INIT_FAILED" for row in rows):
        return "INCONCLUSIVE_AIRLOCK_INIT_FAILURE"
    if any(row.get("status") not in {"EVALUATED"} for row in rows):
        return "INCONCLUSIVE_INFRASTRUCTURE"
    classes = [row.get("pair_class") for row in rows]
    if "UNDERCONSTRAINED" in classes:
        return "CURRENT_GATE_NOT_REVIEW_COMPLETE"
    if all(value == "DISCRIMINATED" for value in classes):
        return "EXTERNAL_CONSTRAINT_DISCRIMINATION_EARNED"
    if any(value in {"OVERCONSERVATIVE_OR_INSUFFICIENT", "INVERTED", "INCONCLUSIVE"} for value in classes):
        return "INCONCLUSIVE_CONSERVATIVE_GATE"
    return "INCONCLUSIVE_INFRASTRUCTURE"


def markdown_report(payload: dict[str, Any]) -> str:
    counts = payload["pair_class_counts"]
    lines = [
        "# AIRLOCK-SWE-GATE-001 result",
        "",
        f"Verdict: **{payload['verdict']}**",
        "",
        f"Airlock base: `{payload['airlock_base_sha']}`",
        f"SWE-Gate: `{payload['swe_gate_sha']}`",
        f"Frozen sample: {payload['selected_repo_count']} distinct repos / {payload['selected_instance_count']} instances / {payload['patch_evaluation_count']} patch evaluations.",
        "",
        "## Pair classes",
        "",
        "| Class | Count |",
        "|---|---:|",
    ]
    for key in [
        "DISCRIMINATED",
        "UNDERCONSTRAINED",
        "OVERCONSERVATIVE_OR_INSUFFICIENT",
        "INVERTED",
        "INCONCLUSIVE",
    ]:
        lines.append(f"| {key} | {counts.get(key, 0)} |")

    lines.extend(["", "## Instances", "", "| Repo | Instance | Noncompliant | Gold | Pair |", "|---|---|---|---|---|"])
    for row in payload["instances"]:
        n = ((row.get("airlock") or {}).get("result") or {}).get("noncompliant") or {}
        g = ((row.get("airlock") or {}).get("result") or {}).get("gold") or {}
        lines.append(
            f"| {row.get('repo_id','')} | `{row.get('instance_id','')}` | "
            f"{n.get('disposition','?')} / {n.get('reason','?')} | "
            f"{g.get('disposition','?')} / {g.get('reason','?')} | "
            f"{row.get('pair_class','?')} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `UNDERCONSTRAINED` is the preregistered falsifier: current Airlock admits both a functional-pass/review-fail patch and its functional-pass/review-pass gold control.",
            "- `DISCRIMINATED` means current Airlock withholds the noncompliant patch while admitting the gold control without benchmark-specific configuration.",
            "- Withholding both is conservative/inconclusive, not a success.",
            "",
            "No product code, Starter Rules, thresholds, protected paths, or target checks were changed for this benchmark.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--swe-gate-root", type=Path, required=True)
    parser.add_argument("--airlock-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--repo-count", type=int, default=12)
    args = parser.parse_args()

    swe_gate_root = args.swe_gate_root.resolve()
    airlock_root = args.airlock_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    swe_gate_sha = run(["git", "rev-parse", "HEAD"], swe_gate_root, timeout=30)["stdout"].strip()
    airlock_base_sha = os.environ.get("AIRLOCK_BASE_SHA", "").strip()
    selected = eligible_instances(swe_gate_root, args.seed, args.repo_count)

    selection_receipt = {
        "schema": "airlock.swe-gate-001.selection.v1",
        "seed": args.seed,
        "airlock_base_sha": airlock_base_sha,
        "swe_gate_sha": swe_gate_sha,
        "repo_count": args.repo_count,
        "selection_rule": "one deterministic eligible instance per distinct repo; repo and instance order ranked by SHA-256(seed, scope, ids)",
        "eligibility": {
            "released_noncompliant_functional": True,
            "released_noncompliant_constraint": False,
            "released_gold_functional": True,
            "released_gold_constraint": True,
            "required_files_present": True,
        },
        "selected": selected,
    }
    write_json(output_dir / "selected.json", selection_receipt)

    rows: list[dict[str, Any]] = []
    rebuild_script = swe_gate_root / "scripts" / "swe_if_pipeline" / "12_rebuild_docker_images_from_contexts.py"
    for index, selected_row in enumerate(selected, start=1):
        instance_id = selected_row["instance_id"]
        image = selected_row["image"]
        base_image = selected_row["base_image"]
        row: dict[str, Any] = {
            "repo_id": selected_row["repo_id"],
            "instance_id": instance_id,
            "image": image,
            "base_image": base_image,
            "status": "STARTED",
        }
        print(json.dumps({"phase": "instance_start", "index": index, "total": len(selected), "instance_id": instance_id}))

        rebuild_out = output_dir / "build" / f"{instance_id}.json"
        rebuild = run(
            [
                sys.executable,
                str(rebuild_script),
                "--instance-ids",
                instance_id,
                "--workers",
                "1",
                "--output-json",
                str(rebuild_out),
            ],
            swe_gate_root,
            timeout=5400,
        )
        row["build"] = {
            "returncode": rebuild["returncode"],
            "timed_out": rebuild["timed_out"],
            "duration_seconds": rebuild["duration_seconds"],
            "stdout_tail": (rebuild.get("stdout") or "")[-6000:],
            "stderr_tail": (rebuild.get("stderr") or "")[-6000:],
        }
        if rebuild["returncode"] != 0:
            row["status"] = "BUILD_FAILED"
            rows.append(row)
            write_json(output_dir / "instances" / f"{instance_id}.json", row)
            remove_image(image, swe_gate_root)
            remove_image(base_image, swe_gate_root)
            continue

        try:
            noncompliant_truth = external_truth(image, "/swe_if/diff_not_follow_constraint.patch", swe_gate_root)
            gold_truth = external_truth(image, "/swe_if/gold.patch", swe_gate_root)
            row["external_truth"] = {"noncompliant": noncompliant_truth, "gold": gold_truth}
            if not truth_ok(noncompliant_truth, gold_truth):
                row["status"] = "EXTERNAL_TRUTH_DRIFT"
                rows.append(row)
                write_json(output_dir / "instances" / f"{instance_id}.json", row)
                continue

            airlock = airlock_eval(image, instance_id, airlock_root, swe_gate_root)
            row["airlock"] = airlock
            if airlock["process"]["returncode"] != 0:
                row["status"] = "AIRLOCK_EVALUATOR_FAILED"
            else:
                result = airlock.get("result") or {}
                if result.get("status") == "AIRLOCK_INIT_FAILED":
                    row["status"] = "AIRLOCK_INIT_FAILED"
                elif result.get("status") != "EVALUATED":
                    row["status"] = "AIRLOCK_EVALUATOR_FAILED"
                else:
                    row["status"] = "EVALUATED"
                    row["pair_class"] = result.get("pair_class")
            rows.append(row)
            write_json(output_dir / "instances" / f"{instance_id}.json", row)
        finally:
            remove_image(image, swe_gate_root)
            remove_image(base_image, swe_gate_root)

    pair_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        if row.get("pair_class"):
            pair_counts[str(row["pair_class"])] += 1

    payload = {
        "schema": "airlock.swe-gate-001.result.v1",
        "experiment": "AIRLOCK-SWE-GATE-001",
        "airlock_base_sha": airlock_base_sha,
        "swe_gate_sha": swe_gate_sha,
        "seed": args.seed,
        "selected_repo_count": len({row["repo_id"] for row in selected}),
        "selected_instance_count": len(selected),
        "patch_evaluation_count": 2 * len(selected),
        "verdict": verdict(rows),
        "pair_class_counts": dict(sorted(pair_counts.items())),
        "instances": rows,
    }
    write_json(output_dir / "result.json", payload)
    (output_dir / "result.md").write_text(markdown_report(payload))
    print(json.dumps({"verdict": payload["verdict"], "pair_class_counts": payload["pair_class_counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
