from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PREREG = HERE / "prereg.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("artifact_dir", type=Path)
    args = ap.parse_args()

    result_path = args.artifact_dir / "result.json"
    if not result_path.is_file():
        raise SystemExit("missing result.json")
    result = json.loads(result_path.read_text())
    prereg = json.loads(PREREG.read_text())

    assert result["schema"] == "openline.qec-bench-qual-001.result.v1"
    assert result["experiment_id"] == "QEC-BENCH-QUAL-001"
    assert result["prereg_sha256"] == sha256(PREREG)
    assert result["pins"]["airlock_base"] == prereg["airlock_base"]
    assert result["pins"]["qec_lego_bench"] == prereg["external_benchmark"]["commit"]
    assert result["verdict"] in prereg["terminal_verdicts"]

    if result["verdict"] == "QEC_BENCH_QUAL_PASS":
        limits = prereg["within_run_acceptance"]
        assert result["claim"] == "BENCHMARK_QUALIFIED_WITHIN_RUN_ONLY"
        assert result["accuracy_summary"]["errors"] >= limits["minimum_total_logical_errors"]
        assert result["accuracy_summary"]["max_abs_z_from_pooled"] <= limits["maximum_accuracy_abs_z_from_pooled"]
        assert result["timing_summary"]["mad_over_median"] <= limits["maximum_timing_mad_over_median"]
        assert result["timing_summary"]["max_over_min"] <= limits["maximum_timing_max_over_min"]
        assert len(result["accuracy_replicates"]) == prereg["baseline"]["accuracy_replicates"]
        assert len(result["timing_replicates"]) == prereg["baseline"]["timing_replicates"]
        assert len(result["circuit_sha256"]) == 64

    print(result["verdict"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
