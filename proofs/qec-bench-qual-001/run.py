from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
PREREG_PATH = HERE / "prereg.json"
EXPERIMENT_ID = "QEC-BENCH-QUAL-001"
PASS = "QEC_BENCH_QUAL_PASS"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git(repo: Path, *args: str) -> str:
    p = subprocess.run(
        ["git", "-C", str(repo), *args], text=True, capture_output=True, timeout=30
    )
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p.stdout.strip()


def cpu_model() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text(errors="replace").splitlines():
            if line.lower().startswith("model name") and ":" in line:
                return line.split(":", 1)[1].strip()
    return platform.processor() or "unknown"


def pooled_accuracy(replicates: list[dict[str, int]]) -> dict[str, float | int]:
    shots = sum(x["shots"] for x in replicates)
    errors = sum(x["errors"] for x in replicates)
    p = errors / shots if shots else 0.0
    max_z = 0.0
    if shots and 0.0 < p < 1.0:
        for row in replicates:
            se = math.sqrt(p * (1.0 - p) / row["shots"])
            if se:
                z = abs((row["errors"] / row["shots"] - p) / se)
                max_z = max(max_z, z)
    return {
        "shots": shots,
        "errors": errors,
        "failure_rate": p,
        "max_abs_z_from_pooled": max_z,
    }


def timing_summary(values: list[float]) -> dict[str, float]:
    med = statistics.median(values)
    deviations = [abs(x - med) for x in values]
    mad = statistics.median(deviations)
    return {
        "median_seconds_per_shot": med,
        "mad_seconds_per_shot": mad,
        "mad_over_median": mad / med if med else float("inf"),
        "max_over_min": max(values) / min(values) if values and min(values) > 0 else float("inf"),
        "minimum_seconds_per_shot": min(values),
        "maximum_seconds_per_shot": max(values),
    }


def classify(
    accuracy: dict[str, float | int], timing: dict[str, float], prereg: dict[str, Any]
) -> tuple[str, str]:
    limits = prereg["within_run_acceptance"]
    if int(accuracy["errors"]) < int(limits["minimum_total_logical_errors"]):
        return (
            "INCONCLUSIVE_ACCURACY_SIGNAL_TOO_WEAK",
            "pooled logical-error count is below the preregistered signal floor",
        )
    if float(accuracy["max_abs_z_from_pooled"]) > float(
        limits["maximum_accuracy_abs_z_from_pooled"]
    ):
        return (
            "BENCHMARK_UNSTABLE_ACCURACY",
            "replicate logical-error rates exceed the preregistered pooled-binomial stability bound",
        )
    if float(timing["mad_over_median"]) > float(
        limits["maximum_timing_mad_over_median"]
    ) or float(timing["max_over_min"]) > float(limits["maximum_timing_max_over_min"]):
        return (
            "BENCHMARK_UNSTABLE_TIMING",
            "same-run decoder timing exceeds the preregistered robust variability bound",
        )
    return PASS, "within-run accuracy and timing measurement surfaces qualified"


def self_test() -> None:
    prereg = json.loads(PREREG_PATH.read_text())
    good_accuracy = pooled_accuracy([
        {"shots": 5000, "errors": 100},
        {"shots": 5000, "errors": 95},
        {"shots": 5000, "errors": 105},
        {"shots": 5000, "errors": 98},
    ])
    good_timing = timing_summary([1.00e-4, 1.05e-4, 0.98e-4, 1.02e-4, 1.01e-4])
    assert classify(good_accuracy, good_timing, prereg)[0] == PASS

    weak = pooled_accuracy([
        {"shots": 5000, "errors": 2},
        {"shots": 5000, "errors": 3},
        {"shots": 5000, "errors": 1},
        {"shots": 5000, "errors": 2},
    ])
    assert classify(weak, good_timing, prereg)[0] == "INCONCLUSIVE_ACCURACY_SIGNAL_TOO_WEAK"

    bad_timing = timing_summary([1e-4, 1e-4, 1e-4, 1e-4, 2e-4])
    assert classify(good_accuracy, bad_timing, prereg)[0] == "BENCHMARK_UNSTABLE_TIMING"
    print("QEC-BENCH-QUAL-001 self-test PASS")


def package_versions(names: list[str]) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for name in names:
        try:
            out[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            out[name] = None
    return out


def terminal_base(prereg: dict[str, Any], qec_root: Path, qec_sha: str) -> dict[str, Any]:
    return {
        "schema": "openline.qec-bench-qual-001.result.v1",
        "experiment_id": EXPERIMENT_ID,
        "prereg_sha256": sha256_bytes(PREREG_PATH.read_bytes()),
        "pins": {
            "airlock_base": prereg["airlock_base"],
            "qec_lego_bench": qec_sha,
        },
        "qec_checkout": str(qec_root),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_model": cpu_model(),
            "github_event_name": os.environ.get("GITHUB_EVENT_NAME"),
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_sha": os.environ.get("GITHUB_SHA"),
        },
    }


def run(qec_root: Path, output: Path) -> int:
    prereg = json.loads(PREREG_PATH.read_text())
    output.mkdir(parents=True, exist_ok=True)

    try:
        qec_sha = git(qec_root, "rev-parse", "HEAD")
    except Exception as exc:
        qec_sha = "UNAVAILABLE"
        result = {
            **terminal_base(prereg, qec_root, qec_sha),
            "verdict": "INCONCLUSIVE_QEC_INSTALL",
            "reason": f"qec checkout unavailable: {type(exc).__name__}: {exc}",
        }
        write_json(output / "result.json", result)
        return 0

    expected = prereg["external_benchmark"]["commit"]
    if qec_sha != expected:
        raise RuntimeError(f"QEC_PIN_MISMATCH expected={expected} actual={qec_sha}")

    install = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", str(qec_root)],
        text=True,
        capture_output=True,
        timeout=600,
    )
    (output / "pip-install.log").write_text(
        install.stdout + "\n--- STDERR ---\n" + install.stderr, encoding="utf-8"
    )
    if install.returncode != 0:
        result = {
            **terminal_base(prereg, qec_root, qec_sha),
            "verdict": "INCONCLUSIVE_QEC_INSTALL",
            "reason": "pinned qec-lego-bench dependency installation failed",
            "pip_install_returncode": install.returncode,
        }
        write_json(output / "result.json", result)
        return 0

    freeze = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--all"],
        text=True,
        capture_output=True,
        timeout=60,
    )
    (output / "pip-freeze.txt").write_text(freeze.stdout, encoding="utf-8")

    try:
        importlib.invalidate_caches()
        import qec_lego_bench.cli  # noqa: F401  # registers code/noise/decoder names
        from qec_lego_bench.cli.codes import CodeCli
        from qec_lego_bench.cli.decoders import DecoderCli
        from qec_lego_bench.cli.decoding_speed import decoding_speed
        from qec_lego_bench.cli.logical_error_rate import logical_error_rate

        cfg = prereg["baseline"]
        code = cfg["code"]
        decoder = cfg["decoder"]

        # Arguably normally converts annotated CLI strings into these wrappers
        # before calling the functions. Programmatic invocation must do the same:
        # both benchmark functions later read DecoderCli.decompose_errors.
        code_arg = CodeCli(code)
        decoder_arg = DecoderCli(decoder)

        circuit = code_arg().circuit
        circuit_sha = sha256_bytes(str(circuit).encode("utf-8"))

        # Warm-up is intentionally excluded from the timing receipt.
        for _ in range(int(cfg["timing_warmups"])):
            decoding_speed(
                code_arg,
                decoder=decoder_arg,
                min_init_time=float(cfg["timing_min_init_seconds"]),
                min_init_shots=10,
                min_time=0.25,
                min_shots=int(cfg["timing_min_shots"]),
                max_shots=int(cfg["timing_max_shots"]),
                no_print=True,
            )

        timing_rows: list[dict[str, float | int]] = []
        for index in range(int(cfg["timing_replicates"])):
            measured = decoding_speed(
                code_arg,
                decoder=decoder_arg,
                min_init_time=float(cfg["timing_min_init_seconds"]),
                min_init_shots=10,
                min_time=float(cfg["timing_min_seconds"]),
                min_shots=int(cfg["timing_min_shots"]),
                max_shots=int(cfg["timing_max_shots"]),
                no_print=True,
            )
            timing_rows.append({
                "replicate": index + 1,
                "shots": int(measured.shots),
                "elapsed_seconds": float(measured.elapsed),
                "seconds_per_shot": float(measured.decoding_time),
            })

        accuracy_rows: list[dict[str, int | float]] = []
        shots = int(cfg["accuracy_shots_per_replicate"])
        for index in range(int(cfg["accuracy_replicates"])):
            stats = logical_error_rate(
                code_arg,
                decoder=decoder_arg,
                max_shots=shots,
                max_errors=shots,
                num_workers=1,
                no_progress=True,
                no_print=True,
            )
            accuracy_rows.append({
                "replicate": index + 1,
                "shots": int(stats.samples),
                "errors": int(stats.failed),
                "failure_rate": float(stats.failure_rate_value),
            })

        accuracy = pooled_accuracy([
            {"shots": int(x["shots"]), "errors": int(x["errors"])} for x in accuracy_rows
        ])
        timing = timing_summary([float(x["seconds_per_shot"]) for x in timing_rows])
        verdict, reason = classify(accuracy, timing, prereg)

        result = {
            **terminal_base(prereg, qec_root, qec_sha),
            "verdict": verdict,
            "reason": reason,
            "baseline": cfg,
            "circuit_sha256": circuit_sha,
            "timing_replicates": timing_rows,
            "timing_summary": timing,
            "accuracy_replicates": accuracy_rows,
            "accuracy_summary": accuracy,
            "resolved_versions": package_versions([
                "qec-lego-bench", "stim", "sinter", "mwpf", "mwpf-rational",
                "mwpf-fast", "numpy", "ldpc", "ipython"
            ]),
            "claim": "BENCHMARK_QUALIFIED_WITHIN_RUN_ONLY" if verdict == PASS else "NONE",
        }
        write_json(output / "result.json", result)
        return 0
    except Exception as exc:
        result = {
            **terminal_base(prereg, qec_root, qec_sha),
            "verdict": "INCONCLUSIVE_QEC_RUNTIME",
            "reason": f"pinned benchmark runtime failed: {type(exc).__name__}: {exc}",
            "resolved_versions": package_versions([
                "qec-lego-bench", "stim", "sinter", "mwpf", "mwpf-rational",
                "mwpf-fast", "numpy", "ldpc", "ipython"
            ]),
        }
        write_json(output / "result.json", result)
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qec-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.qec_root is None or args.output is None:
        parser.error("--qec-root and --output are required unless --self-test is used")
    return run(args.qec_root.resolve(), args.output.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
