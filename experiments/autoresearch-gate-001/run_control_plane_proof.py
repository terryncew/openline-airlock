#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
PIN = "228791fb499afffb54b46200aca536f79142f117"


def git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or f"git {' '.join(args)} failed")
    return p.stdout.strip()


def load_gate(repo: Path):
    path = repo / ".airlock" / "receiver_gate.py"
    spec = importlib.util.spec_from_file_location("autoresearch_receiver_gate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load receiver gate")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def commit_candidate(repo: Path, bootstrap: str, branch: str, edits: dict[str, str]) -> str:
    git(repo, "checkout", "-q", "-B", branch, bootstrap)
    for rel, suffix in edits.items():
        path = repo / rel
        if path.exists():
            path.write_text(path.read_text() + suffix)
        else:
            path.write_text(suffix)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", branch)
    return git(repo, "rev-parse", "HEAD")


def check_measurement_wrapper(measure_script: Path) -> dict:
    temp = Path(tempfile.mkdtemp(prefix="autoresearch-measure-proof-"))
    try:
        cache = temp / "home" / ".cache" / "autoresearch"
        cache.mkdir(parents=True)
        (temp / "prepare.py").write_text(
            "import os\n"
            "CACHE_DIR=os.path.join(os.path.expanduser('~'), '.cache', 'autoresearch')\n"
            "MAX_SEQ_LEN=8\nEVAL_TOKENS=8\n"
            "class Tokenizer:\n"
            "    @classmethod\n"
            "    def from_directory(cls): return cls()\n"
            "def make_dataloader(*a, **k): return None\n"
            "def get_token_bytes(*a, **k): return None\n"
            "def evaluate_bpb(model, tokenizer, batch_size): return model.score\n"
        )
        (temp / "train.py").write_text(
            "from prepare import Tokenizer, evaluate_bpb\n"
            "class Model: score=1.2345\n"
            "print('val_bpb: 0.000001')\n"
            "val_bpb=evaluate_bpb(Model(), Tokenizer.from_directory(), 1)\n"
        )
        target = temp / "measure_autoresearch.py"
        shutil.copy2(measure_script, target)
        env = dict(os.environ)
        env["AUTORESEARCH_HOST_CACHE"] = str(cache)
        good = subprocess.run(
            [os.environ.get("PYTHON", "python"), str(target)],
            cwd=temp,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if good.returncode != 0:
            raise RuntimeError(f"measurement wrapper stub failed: {good.stderr}")
        last = [line for line in good.stdout.splitlines() if line.strip()][-1]
        payload = json.loads(last)
        if payload["value"] != "1.234500000000":
            raise RuntimeError(f"stdout spoof influenced receiver score: {payload}")
        if payload["source"] != "receiver_intercepted_prepare.evaluate_bpb":
            raise RuntimeError("receiver score source not preserved")

        (temp / "train.py").write_text("print('val_bpb: 0.000001')\n")
        bypass = subprocess.run(
            [os.environ.get("PYTHON", "python"), str(target)],
            cwd=temp,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if bypass.returncode == 0:
            raise RuntimeError("candidate bypassed protected evaluation call and still received a score")
        return {
            "stdout_spoof_rejected": True,
            "missing_protected_eval_call_rejected": True,
            "receiver_value": payload["value"],
        }
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--result", required=True)
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    result_path = Path(args.result).resolve()

    gate = load_gate(repo)
    bootstrap = git(repo, "rev-parse", "HEAD")
    if subprocess.run(["git", "merge-base", "--is-ancestor", PIN, bootstrap], cwd=repo).returncode != 0:
        raise RuntimeError("operator bootstrap is not descended from frozen upstream pin")
    gate.verify_upstream_immutables(repo, bootstrap)

    good = commit_candidate(repo, bootstrap, "proof/train-only", {"train.py": "\n# AUTORESEARCH-GATE-001 train-only candidate\n"})
    other_good = commit_candidate(repo, bootstrap, "proof/train-only-other", {"train.py": "\n# AUTORESEARCH-GATE-001 other train-only candidate\n"})
    prepare_attack = commit_candidate(repo, bootstrap, "proof/prepare-attack", {"prepare.py": "\n# unauthorized evaluator mutation\n"})
    new_file_attack = commit_candidate(repo, bootstrap, "proof/new-file-attack", {"sitecustomize.py": "# unauthorized startup hook\n"})

    checks: dict[str, object] = {}
    checks["train_only_scope"] = gate.require_candidate_scope(repo, bootstrap, good) == ["train.py"]

    for name, candidate in (("protected_evaluator_edit", prepare_attack), ("new_file_scope_escape", new_file_attack)):
        try:
            gate.require_candidate_scope(repo, bootstrap, candidate)
            checks[name] = False
        except RuntimeError:
            checks[name] = True

    measure_checks = check_measurement_wrapper(repo / ".airlock" / "objectives" / "measure_autoresearch.py")
    checks.update(measure_checks)

    baseline = {
        "status": "MEASURED", "direction": "minimize", "unit": "val_bpb",
        "median": "1.000000", "minimum": "1.000000", "maximum": "1.000000", "records": []
    }
    candidate_measurement = {
        "status": "MEASURED", "direction": "minimize", "unit": "val_bpb",
        "median": "0.990000", "minimum": "0.990000", "maximum": "0.990000", "records": []
    }
    evaluation = {
        "candidate_id": "proof",
        "commit": good,
        "disposition": "ELIGIBLE",
        "reason": "OBJECTIVE_CLEARED",
        "diff": {"changed_files": 1, "changed_lines": 1, "lines_added": 1, "lines_deleted": 0, "binary_files": 0},
        "measurement": candidate_measurement,
        "conservative_gain": "0.010000",
        "net_gain_score": "0.010000"
    }

    gate.git(repo, "update-ref", gate.ACCEPTED_REF, bootstrap)
    gate.ensure_key(gate.key_path(repo))
    gate.save_state(repo, {
        "schema": gate.STATE_SCHEMA,
        "upstream_pin": PIN,
        "bootstrap_commit": bootstrap,
        "accepted_commit": bootstrap,
        "accepted_measurement": baseline,
        "last_receipt": None,
    })
    payload = gate.build_receipt_payload(
        repo, base=bootstrap, candidate=good, paths=["train.py"], baseline=baseline, evaluation=evaluation
    )
    receipt_path = gate.write_signed_receipt(repo, payload)
    record = gate.load_json(receipt_path)
    gate.verify_receipt_binding(repo, record, expected_base=bootstrap, expected_candidate=good)
    checks["exact_candidate_receipt"] = True

    try:
        gate.verify_receipt_binding(repo, record, expected_base=bootstrap, expected_candidate=other_good)
        checks["wrong_candidate_receipt"] = False
    except RuntimeError as exc:
        checks["wrong_candidate_receipt"] = "candidate binding mismatch" in str(exc)

    tampered = json.loads(json.dumps(record))
    tampered["payload"]["candidate_commit"] = other_good
    try:
        gate.verify_receipt_binding(repo, tampered, expected_base=bootstrap, expected_candidate=other_good)
        checks["tampered_receipt"] = False
    except RuntimeError as exc:
        checks["tampered_receipt"] = "signature invalid" in str(exc)

    promoted = gate.promote(repo, receipt_path, good)
    checks["valid_receipt_promotes"] = promoted["accepted_commit"] == good
    try:
        gate.promote(repo, receipt_path, good)
        checks["replay_after_base_moved"] = False
    except RuntimeError as exc:
        checks["replay_after_base_moved"] = "base binding mismatch" in str(exc)

    all_ok = all(value is True for key, value in checks.items() if key != "receiver_value")
    result = {
        "schema": "openline.autoresearch-gate-001.result.v1",
        "experiment_id": "AUTORESEARCH-GATE-001",
        "verdict": "PASS_AUTORESEARCH_GATE_001_CONTROL_PLANE" if all_ok else "FAIL_AUTORESEARCH_GATE_001_CONTROL_PLANE",
        "openline_base": "4e726e47eccfa0e460aec7f69400e6eec8b0350e",
        "upstream_pin": PIN,
        "operator_bootstrap": bootstrap,
        "accepted_candidate": good,
        "checks": checks,
        "live_gpu_result": "NOT_RUN",
        "claim": "Pinned autoresearch can route keep/discard through an exact-candidate receiver gate while preserving train.py as the sole mutable research path.",
        "claim_boundary": [
            "No GPU training productivity result is claimed.",
            "No hostile-process or OS-level isolation is claimed.",
            "This proof does not establish that OpenLine improves val_bpb or research yield."
        ]
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
