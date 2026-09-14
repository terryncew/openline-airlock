#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FREEZE = ROOT / "AUTORESEARCH_LIVE_003_FREEZE.json"
PREREG = ROOT / "AUTORESEARCH_LIVE_003_PREREGISTRATION.json"

A = "20a0df6cc98778ffb53957d6b4fafccda3a4973e"
BASE = "effe44963da4d8b81ecc9be1ba3f115ac3ef2dab"
ARCHIVE_SHA = "a66e354a5d46e1549484498593e01b2a7d43674c0985b739d4cc2df513cd05f1"
BUNDLE_SHA = "46f688458039507d753ed8ef2421727ad10703dd52d116b80d17c6bd6893370e"
RESULT_SHA = "756cfb21947515cce27d7a36fbd7b73f7d26e60ed12fad33496fae9bf768305e"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    x = json.loads(FREEZE.read_text())
    assert x["schema"] == "openline.autoresearch.live003-freeze.v1"
    assert x["experiment_id"] == "AUTORESEARCH-LIVE-003"
    assert x["terminal_verdict"] == "CONFIRMED_LIVE_IMPROVEMENT_PROMOTED"
    assert x["final_accepted_commit"] == A
    assert x["accepted_commit_parent"] == BASE
    assert x["baseline"]["accepted_commit"] == BASE
    assert x["confirmation"]["candidate_commit"] == A
    assert x["confirmation"]["base_commit"] == BASE
    assert x["confirmation"]["decision"] == "ACCEPT"
    assert x["confirmation"]["promotion_authority"] is True
    assert x["discoveries"][0]["decision"] == "REJECT"
    assert x["discoveries"][1]["candidate_commit"] == A
    assert x["discoveries"][1]["decision"] == "ACCEPT"
    assert x["integrity"]["protected_file_count"] == 15
    assert x["integrity"]["protected_integrity_before_after_every_measurement"] == "MATCH"
    assert x["off_pod_archive"]["sha256"] == ARCHIVE_SHA
    assert x["off_pod_archive"]["git_bundle_sha256"] == BUNDLE_SHA
    assert x["off_pod_archive"]["result_sha256"] == RESULT_SHA
    assert x["evidence_verification"]["receipt_signatures_reverified_post_hoc"] is False
    assert "recursive improvement" in x["not_earned"]
    assert "cumulative optimization" in x["not_earned"]
    assert x["budget"]["researcher_calls"] == 2
    assert x["budget"]["receiver_measurements"] == 4
    assert float(x["budget"]["estimated_gpu_spend_usd"]) < float(x["budget"]["paid_gpu_spend_ceiling_usd"])
    assert float(x["budget"]["pod_wall_seconds_observed"]) < float(x["budget"]["pod_wall_seconds_ceiling"])
    assert sha256_file(PREREG) == x["preregistration_sha256"]
    print("PASS AUTORESEARCH-LIVE-003 frozen result")
    print(f"accepted_commit={A}")
    print(f"archive_sha256={ARCHIVE_SHA}")
    print(f"git_bundle_sha256={BUNDLE_SHA}")
    print("claim=CONFIRMED_LIVE_IMPROVEMENT_PROMOTED")


if __name__ == "__main__":
    main()
