#!/usr/bin/env python3
"""RSI-004: lineage-aware inheritance across three generations.

Question: when gen1's receiver evidence is reopened, does questioned standing
propagate through receiver-signed REQUIRED lineage to gen2 and gen3, which
inherited from gen1's installed policy - while an unrelated accepted root
(rootU) keeps its inherited standing?

The repaired projector (derive_airlock_memory_with_lineage, pinned at
openline-verified-memory@36e3d0e) derives local standing first, then
propagates questioned standing transitively through REQUIRED lineage
dependencies to a deterministic fixed point. This runner exercises that
projector through the real Airlock/Nightshift and receiver-evidence
machinery: real Nightshift selections, real receiver-observed installations
into isolated git refs, real signed promotion/standing/lineage records.

Execution gate: the default invocation runs the self-check only and never
executes the primary. The primary sequence is encoded below but is NOT
invoked without the explicit --execute-primary flag. Nothing in this file
may contact Nightshift, mint a REOPEN, or write a primary result unless the
gate is open.

Preregistration: RSI_004_PREREGISTRATION.json (same directory, frozen bytes).
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import inspect
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any

from airlock.nightshift import run_nightshift
from airlock.verification import sign, verify_signature

try:
    from openline_verified_memory import (
        AIRLOCK_GENERATION_SCHEMA,
        AIRLOCK_LINEAGE_SCHEMA,
        AIRLOCK_PROMOTION_SCHEMA,
        AIRLOCK_STANDING_SCHEMA,
        EvidenceError,
        derive_airlock_memory,
        derive_airlock_memory_with_lineage,
        established,
        signed_record_sha256,
        verify_hmac_record,
    )
    import openline_verified_memory as _ovm_pkg
except ImportError as exc:  # fail closed: the repaired projector is part of the experiment
    raise SystemExit(
        "RSI-004 requires openline-verified-memory pinned to "
        "36e3d0e0dab6a121abc1c14accbaa7310b5c2186 "
        "(derive_airlock_memory_with_lineage)"
    ) from exc


PREREG_PATH = Path(__file__).with_name("RSI_004_PREREGISTRATION.json")
PREREG_SHA256 = "20ee57c424b9dd8281ef973b0d3cc250f61b5c908662d9dcc7b45fe8e55f1055"
AIRLOCK_BASE_MAIN = "db9fb27aa154a240eed16c1ac7bf99401011f198"
VERIFIED_MEMORY_COMMIT = "36e3d0e0dab6a121abc1c14accbaa7310b5c2186"
EVIDENCE_PY_SHA256 = "ba02bc78c999120b31ea68fcb4f4fd2d12967c705e380204d0ee093b1d874ec9"

VERDICT_PASS = "PASS_RSI_004_LINEAGE_AWARE_INHERITANCE"
VERDICT_FAIL = "FAIL_RSI_004_REQUIRED_ANCESTRY_NOT_ENFORCED"
VERDICT_INCONCLUSIVE = "INCONCLUSIVE_RSI_004_PRECONDITION_FAILURE"
VERDICTS = (VERDICT_PASS, VERDICT_FAIL, VERDICT_INCONCLUSIVE)
CAUSE_CODES = (
    "NONE",
    "REQUIRED_ANCESTRY_NOT_ENFORCED",
    "INSTALLED_REF_MUTATION",
    "RECEIPT_MUTATION",
    "PROJECTION_NONDETERMINISM",
    "LINEAGE_BINDING_FAILURE",
    "REOPEN_NOT_OBSERVED",
    "CHECKPOINT_NOT_ESTABLISHED",
)

EXECUTE_PRIMARY_FLAG = "--execute-primary"
PRIMARY_CONTACT_MARKER = Path(__file__).with_name(".rsi-004-primary-contact")

RU = "refs/heads/rsi-004/installed-rootU"
R1 = "refs/heads/rsi-004/installed-gen1"
R2 = "refs/heads/rsi-004/installed-gen2"
R3 = "refs/heads/rsi-004/installed-gen3"
RU_BRANCH = "rsi-004/installed-rootU"
R1_BRANCH = "rsi-004/installed-gen1"
R2_BRANCH = "rsi-004/installed-gen2"
R3_BRANCH = "rsi-004/installed-gen3"
WORK_BRANCHES = {
    "rootU": "rsi-004/rootU-work",
    "gen1": "rsi-004/gen1-work",
    "gen2": "rsi-004/gen2-work",
    "gen3": "rsi-004/gen3-work",
}
INSTALL_REFS = {"rootU": RU, "gen1": R1, "gen2": R2, "gen3": R3}

ROOTU_LESSON = {
    "lesson_id": "rsi-004-rootU-unrelated-policy",
    "title": "rootU earned an unrelated generator policy improvement",
    "text": (
        "An independent Nightshift selection improved the generator policy on an "
        "unrelated axis (bonus term, not the STEP lineage) and earned inheritance "
        "through exact receiver-observed installation at the rootU ref. Its "
        "lineage record is an explicit receiver-signed ROOT declaration."
    ),
}
GEN1_LESSON = {
    "lesson_id": "rsi-004-gen1-earned-policy",
    "title": "Gen1 earned an improved generator policy through exact installation",
    "text": (
        "A unique Nightshift selection improved the generator policy "
        "(src/policy.py STEP 1 -> 2) and applied it once, earning inheritance "
        "through exact receiver-observed installation at the gen1 ref. Its "
        "lineage record is an explicit receiver-signed ROOT declaration."
    ),
}
GEN2_LESSON = {
    "lesson_id": "rsi-004-gen2-inherited-policy",
    "title": "Gen2 inherited by running under gen1's installed policy",
    "text": (
        "Gen2's generator was bound to the exact installed gen1 policy bytes; "
        "its own selection earned inheritance through exact receiver-observed "
        "installation at the gen2 ref. Its lineage record is a receiver-signed "
        "REQUIRED declaration naming gen1 as its single required parent."
    ),
}
GEN3_LESSON = {
    "lesson_id": "rsi-004-gen3-inherited-policy",
    "title": "Gen3 inherited by running under gen2's installed policy",
    "text": (
        "Gen3's generator was bound to the exact installed gen2 policy bytes; "
        "its own selection earned inheritance through exact receiver-observed "
        "installation at the gen3 ref. Its lineage record is a receiver-signed "
        "REQUIRED declaration naming gen2 as its single required parent."
    ),
}
LESSONS = {"rootU": ROOTU_LESSON, "gen1": GEN1_LESSON, "gen2": GEN2_LESSON, "gen3": GEN3_LESSON}
GEN4_LESSON_ID = "rsi-004-gen4-admission-probe"

POLICY_V1 = (
    '"""Generator policy: ordinary code. The installed policy is the generator."""\n'
    "STEP = 1\n"
    "\n"
    "\n"
    "def propose(value: int) -> int:\n"
    "    return value + STEP\n"
)
POLICY_V2 = POLICY_V1.replace("STEP = 1", "STEP = 2")
POLICY_VU = (
    '"""Generator policy: unrelated root improvement (bonus axis)."""\n'
    "STEP = 1\n"
    "BONUS = 1\n"
    "\n"
    "\n"
    "def propose(value: int) -> int:\n"
    "    return value + STEP + BONUS\n"
)

ROOTU_SHIM = """#!/usr/bin/env python3
import json, os
from pathlib import Path

if os.environ.get("AIRLOCK_RELEASE_AUTHORITY") != "ABSENT":
    raise SystemExit(20)
if os.environ.get("OPENROUTER_API_KEY") != "rsi-fixture-secret":
    raise SystemExit(21)
# rootU's improvement: unrelated bonus-axis policy AND apply it once.
# VALUE 0 -> 2 via STEP + BONUS, matching the preregistered expected gain.
Path("src/policy.py").write_text(__POLICY_VU__)
Path("src/value.py").write_text("VALUE = 2\\n")
Path(os.environ["AIRLOCK_AGENT_REPORT"]).write_text(json.dumps({
    "reported_cost_usd": "0.01",
    "provider": "fixture",
    "model": "fake-hermes-rsi-004-rootU",
}))
print("rsi-004 rootU candidate written")
""".replace("__POLICY_VU__", repr(POLICY_VU))

GEN1_SHIM = """#!/usr/bin/env python3
import json, os
from pathlib import Path

if os.environ.get("AIRLOCK_RELEASE_AUTHORITY") != "ABSENT":
    raise SystemExit(20)
if os.environ.get("OPENROUTER_API_KEY") != "rsi-fixture-secret":
    raise SystemExit(21)
# Gen1's improvement: install a better generator policy AND apply it once.
Path("src/policy.py").write_text(__POLICY_V2__)
Path("src/value.py").write_text("VALUE = 2\\n")
Path(os.environ["AIRLOCK_AGENT_REPORT"]).write_text(json.dumps({
    "reported_cost_usd": "0.01",
    "provider": "fixture",
    "model": "fake-hermes-rsi-004-gen1",
}))
print("rsi-004 gen1 candidate written")
""".replace("__POLICY_V2__", repr(POLICY_V2))


def inheriting_shim_code(policy_sha256: str, pristine_path: str, base_value: int, gen: str) -> str:
    """A generation's generator executable, written in-phase with its parent's
    installed policy binding baked into its bytes. It loads propose() only
    from the pristine parent archive, hash-asserts it, and never rewrites
    the installed policy."""
    return """#!/usr/bin/env python3
import hashlib, importlib.util, json, os
from pathlib import Path

# Baked at generation time from the installed parent ref, verified by the
# harness before Nightshift runs.
BAKED_POLICY_SHA256 = %r
BAKED_PRISTINE_PATH = %r
BAKED_BASE_VALUE = %r

if os.environ.get("AIRLOCK_RELEASE_AUTHORITY") != "ABSENT":
    raise SystemExit(20)
if os.environ.get("OPENROUTER_API_KEY") != "rsi-fixture-secret":
    raise SystemExit(21)
policy_path = Path(BAKED_PRISTINE_PATH) / "src" / "policy.py"
actual = hashlib.sha256(policy_path.read_bytes()).hexdigest()
if actual != BAKED_POLICY_SHA256:
    raise SystemExit(22)
spec = importlib.util.spec_from_file_location("rsi_installed_policy", str(policy_path))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Path("src/value.py").write_text(f"VALUE = {module.propose(BAKED_BASE_VALUE)}\\n")
Path(os.environ["AIRLOCK_AGENT_REPORT"]).write_text(json.dumps({
    "reported_cost_usd": "0.01",
    "provider": "fixture",
    "model": "fake-hermes-rsi-004-%s",
}))
print("rsi-004 %s candidate written")
""" % (policy_sha256, pristine_path, base_value, gen, gen)


class PreconditionFailure(Exception):
    """A preregistered precondition was not met: the propagation question
    could not be put to the mechanism. Maps to INCONCLUSIVE, not a crash."""


def sh(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    cp = subprocess.run(
        list(args),
        cwd=None if cwd is None else str(cwd),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and cp.returncode != 0:
        raise RuntimeError(
            f"command failed ({cp.returncode}): {' '.join(args)}\n{cp.stderr.strip()}"
        )
    return cp.stdout.strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def ref_bytes(ref: str, repo: Path) -> str:
    """Byte hash of the commit object an installed ref points to."""
    out = subprocess.run(
        ["git", "cat-file", "commit", ref],
        cwd=str(repo),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout
    return hashlib.sha256(out).hexdigest()


def policy_bytes_at(repo: Path, commit: str) -> bytes:
    """Exact installed-policy bytes at a commit. The verifier recomputes the
    digest from these bytes itself; no caller-supplied digest is trusted."""
    return subprocess.run(
        ["git", "show", f"{commit}:src/policy.py"],
        cwd=str(repo),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_receipt(repo: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else repo / path


def mint_lineage_record(
    *,
    subject_lesson_id: str,
    subject_promotion_receipt_sha256: str,
    key: bytes,
    parent_lesson_id: str | None = None,
    parent_promotion_receipt_sha256: str | None = None,
    parent_selected_commit: str | None = None,
    parent_installed_policy_sha256: str | None = None,
) -> dict[str, Any]:
    """Mint one receiver-signed lineage record.

    Claim boundary: exactly one required parent per generation. A generation
    with no parent gets an explicit ROOT declaration; a generation with a
    parent gets a REQUIRED declaration naming that single parent and binding
    the child promotion receipt, the parent promotion receipt, the parent
    selected commit, and the digest of the parent installed-policy bytes.
    There is no multi-parent form: arbitrary multi-parent lineage is outside
    this experiment's claim boundary.
    """
    payload: dict[str, Any] = {
        "schema": AIRLOCK_LINEAGE_SCHEMA,
        "subject_lesson_id": subject_lesson_id,
        "subject_promotion_receipt_sha256": subject_promotion_receipt_sha256,
    }
    if parent_lesson_id is None:
        payload["declaration"] = "ROOT"
    else:
        for name, value in (
            ("parent_promotion_receipt_sha256", parent_promotion_receipt_sha256),
            ("parent_selected_commit", parent_selected_commit),
            ("parent_installed_policy_sha256", parent_installed_policy_sha256),
        ):
            if not isinstance(value, str) or not value:
                raise PreconditionFailure(f"REQUIRED lineage missing {name}")
        payload["declaration"] = "REQUIRED"
        payload["parent_lesson_id"] = parent_lesson_id
        payload["parent_promotion_receipt_sha256"] = parent_promotion_receipt_sha256
        payload["parent_selected_commit"] = parent_selected_commit
        payload["parent_installed_policy_sha256"] = parent_installed_policy_sha256
    record = sign(payload, key)
    if not verify_hmac_record(record, key):
        raise PreconditionFailure("minted lineage record failed to verify")
    return record


def lineage_record_set_sha256(records: list[dict[str, Any]]) -> str:
    """Deterministic hash of the complete lineage record set: canonical JSON
    per record (sorted keys), ordered by subject_lesson_id, newline-joined.
    The same record bytes always produce the same digest regardless of load
    order; any byte change anywhere in the set changes the digest."""
    canonical = sorted(
        json.dumps(r, sort_keys=True, separators=(",", ":"))
        for r in records
    )
    return hashlib.sha256("\n".join(canonical).encode("utf-8")).hexdigest()


def load_bundle(state_dir: Path, prefix: str) -> dict[str, Any]:
    """Reload one generation's signed records from disk (fresh-process safe)."""
    sel = read_json(state_dir / f"{prefix}_selection.json")
    inst = read_json(state_dir / f"{prefix}_installation.json")
    standing_path = inst.get("standing_record")
    lineage_path = state_dir / f"{prefix}_lineage.json"
    return {
        "prefix": prefix,
        "lesson": LESSONS[prefix],
        "generation": read_json(resolve_receipt_path(sel["generation_record"])),
        "promotion": read_json(Path(inst["promotion_record"])),
        "standing": read_json(Path(standing_path)) if standing_path else None,
        "lineage": read_json(lineage_path) if lineage_path.exists() else None,
        "selection": sel,
        "installation": inst,
    }


def resolve_receipt_path(value: str) -> Path:
    path = Path(value)
    return path  # selection records store absolute paths


def projector_inputs(bundles: dict[str, dict[str, Any]], repo: Path) -> tuple[list[dict], list[dict], dict[str, bytes]]:
    """Build the projector inputs from disk-loaded bundles. Installed-policy
    bytes are read from the installed refs; their digests are recomputed
    inside the verifier, never trusted from a caller."""
    order = ("rootU", "gen1", "gen2", "gen3")
    generations: list[dict] = []
    lineage_records: list[dict] = []
    installed_policies: dict[str, bytes] = {}
    for prefix in order:
        b = bundles[prefix]
        lesson = b["lesson"]
        generations.append(
            {
                "lesson_id": lesson["lesson_id"],
                "title": lesson["title"],
                "text": lesson["text"],
                "generation_record": b["generation"],
                "promotion_record": b["promotion"],
                "standing_record": b["standing"],
            }
        )
        if b["lineage"] is None:
            raise PreconditionFailure(f"{prefix}: lineage record missing from disk")
        lineage_records.append(b["lineage"])
        installed_policies[lesson["lesson_id"]] = policy_bytes_at(
            repo, b["selection"]["selected_commit"]
        )
    return generations, lineage_records, installed_policies


def project_lineage_memories(
    generations: list[dict],
    lineage_records: list[dict],
    installed_policies: dict[str, bytes],
    key: bytes,
):
    """The single choke point for lineage-aware projection in this runner.
    Every standing projection goes through this function; it is the ONLY
    caller of derive_airlock_memory_with_lineage in run_rsi_004.py (enforced
    by the self-check's AST boundary check). Exactly one projector call per
    projection."""
    return derive_airlock_memory_with_lineage(
        generations=generations,
        lineage_records=lineage_records,
        installed_policies=installed_policies,
        key=key,
    )


def project_bundles(bundles: dict[str, dict[str, Any]], repo: Path, key: bytes):
    """Projector inputs from disk-loaded bundles, through the single choke
    point. Used by the checkpoint and REOPEN phases."""
    generations, lineage_records, installed_policies = projector_inputs(bundles, repo)
    return project_lineage_memories(generations, lineage_records, installed_policies, key)


def witness_paths(projection) -> dict[str, list[str]]:
    """Deterministic ancestor paths from the projector's lineage-edge evidence."""
    child_to_parent: dict[str, str] = {}
    subjects: set[str] = set()
    for lesson_id in sorted(projection):
        for e in projection[lesson_id].evidence:
            if e.get("kind") == "airlock_lineage_edge":
                child_to_parent[e["child_lesson_id"]] = e["parent_lesson_id"]
                subjects.add(lesson_id)
    paths: dict[str, list[str]] = {}
    for lesson_id in sorted(subjects):
        chain = [lesson_id]
        node = child_to_parent.get(lesson_id)
        while node is not None and node not in chain:
            chain.append(node)
            node = child_to_parent.get(node)
        paths[lesson_id] = chain
    return paths


def probe_gen4_admission(
    *,
    key: bytes,
    bundles: dict[str, dict[str, Any]],
    generations: list[dict],
    lineage_records: list[dict],
    installed_policies: dict[str, bytes],
) -> tuple[str, dict[str, Any]]:
    """Compute the gen4 admission probe through gen3. gen4 is NEVER executed:
    no Nightshift selection, no installation, no git ref. The probe mints
    hypothetical signed records for a child of gen3 and asks the projector
    what standing it would earn. A questioned gen4 means admission DENIED.

    The synthetic probe records are inherent to the preregistered probe
    design (a hypothetical child cannot have real Nightshift receipts); they
    are not a substitute harness for any executed generation.
    """
    gen3 = bundles["gen3"]
    probe_commit = "4" * 40
    gen_payload = {
        "schema": AIRLOCK_GENERATION_SCHEMA,
        "run_id": "rsi-004-gen4-probe",
        "generation": 0,
        "base_commit": gen3["selection"]["selected_commit"],
        "decision": "UNIQUE_WINNER",
        "selection": {"status": "UNIQUE_WINNER", "winner": {"commit": probe_commit}},
        "synthetic_probe": True,
        "note": "hypothetical child of gen3; never executed",
    }
    generation = sign(gen_payload, key)
    promo_payload = {
        "schema": AIRLOCK_PROMOTION_SCHEMA,
        "run_id": "rsi-004-gen4-probe",
        "generation": 0,
        "base_commit": gen3["selection"]["selected_commit"],
        "generation_receipt_sha256": signed_record_sha256(generation),
        "selected_commit": probe_commit,
        "observed_branch_after": probe_commit,
        "status": "INSTALLED",
        "synthetic_probe": True,
    }
    promotion = sign(promo_payload, key)
    lineage = mint_lineage_record(
        subject_lesson_id=GEN4_LESSON_ID,
        subject_promotion_receipt_sha256=signed_record_sha256(promotion),
        key=key,
        parent_lesson_id=gen3["lesson"]["lesson_id"],
        parent_promotion_receipt_sha256=gen3["installation"]["promotion_record_sha256"],
        parent_selected_commit=gen3["selection"]["selected_commit"],
        parent_installed_policy_sha256=hashlib.sha256(
            installed_policies[gen3["lesson"]["lesson_id"]]
        ).hexdigest(),
    )
    probe_generations = list(generations) + [
        {
            "lesson_id": GEN4_LESSON_ID,
            "title": "gen4 admission probe (hypothetical; never executed)",
            "text": "Hypothetical REQUIRED child of gen3, evaluated by the projector only.",
            "generation_record": generation,
            "promotion_record": promotion,
            "standing_record": None,
        }
    ]
    out = project_lineage_memories(
        probe_generations,
        list(lineage_records) + [lineage],
        installed_policies,
        key,
    )
    mem = out[GEN4_LESSON_ID]
    disposition = "DENIED" if mem.status == "questioned" else "ADMITTED"
    return disposition, {
        "disposition": disposition,
        "executed": False,
        "status": mem.status,
        "witness": mem.witness,
        "generation_record_sha256": signed_record_sha256(generation),
        "promotion_record_sha256": signed_record_sha256(promotion),
        "lineage_record_sha256": signed_record_sha256(lineage),
        "parent_lesson_id": gen3["lesson"]["lesson_id"],
    }


def decide_verdict(
    *,
    pre_reopen_ok: bool,
    lineage_ok: bool,
    refs_unchanged: bool,
    receipts_unchanged: bool,
    deterministic: bool,
    gen1_questioned: bool,
    standings: dict[str, str],
    gen4_probe: str,
) -> tuple[str, str]:
    """Map the frozen verdict precedence to exactly one formal verdict plus
    one cause code. Only the three formal verdicts are ever emitted;
    every diagnostic travels through cause_code."""
    if not pre_reopen_ok:
        return (VERDICT_INCONCLUSIVE, "CHECKPOINT_NOT_ESTABLISHED")
    if not lineage_ok:
        return (VERDICT_INCONCLUSIVE, "LINEAGE_BINDING_FAILURE")
    if not refs_unchanged:
        return (VERDICT_FAIL, "INSTALLED_REF_MUTATION")
    if not receipts_unchanged:
        return (VERDICT_FAIL, "RECEIPT_MUTATION")
    if not deterministic:
        return (VERDICT_FAIL, "PROJECTION_NONDETERMINISM")
    if not gen1_questioned:
        return (VERDICT_INCONCLUSIVE, "REOPEN_NOT_OBSERVED")
    s = standings
    if (
        s.get("gen1") == "questioned"
        and s.get("gen2") == "questioned"
        and s.get("gen3") == "questioned"
        and s.get("rootU") == "inherited"
        and gen4_probe == "DENIED"
    ):
        return (VERDICT_PASS, "NONE")
    if (
        s.get("gen2") == "inherited"
        or s.get("gen3") == "inherited"
        or s.get("rootU") != "inherited"
        or gen4_probe == "ADMITTED"
    ):
        return (VERDICT_FAIL, "REQUIRED_ANCESTRY_NOT_ENFORCED")
    return (VERDICT_INCONCLUSIVE, "REQUIRED_ANCESTRY_NOT_ENFORCED")


RECEIPT_REQUIRED_TOP_KEYS = (
    "schema",
    "experiment",
    "verdict",
    "cause_code",
    "airlock_base_sha",
    "verified_memory_sha",
    "verified_memory_evidence_py_sha256",
    "preregistration_sha256",
    "generations",
    "required_edges",
    "pre_reopen_established",
    "pre_reopen_standings",
    "reopen_evidence",
    "restart_evidence",
    "post_reopen_standings",
    "lineage_witness_paths",
    "gen4_probe",
    "historical_receipt_hashes",
    "installed_ref_hashes",
    "installed_policy_hashes",
    "installed_refs_unchanged",
    "reprojection_deterministic",
    "lineage_record_set_sha256_checkpoint",
    "lineage_record_set_sha256_reprojection",
    "phase_process_pids",
    "claim_boundary",
)
RECEIPT_REQUIRED_GEN_KEYS = (
    "lesson_id",
    "selected_commit",
    "install_ref",
    "receipt_hashes",
)
RECEIPT_REQUIRED_EDGE_KEYS = (
    "child_lesson_id",
    "parent_lesson_id",
    "parent_promotion_receipt_sha256",
    "parent_selected_commit",
    "parent_installed_policy_sha256",
    "edge_record_sha256",
)


def validate_receipt_bindings(receipt: dict[str, Any]) -> list[str]:
    """Check every required receipt binding is present. Returns problems."""
    problems: list[str] = []
    for k in RECEIPT_REQUIRED_TOP_KEYS:
        if k not in receipt:
            problems.append(f"receipt missing top-level binding: {k}")
    if problems:
        return problems
    if receipt.get("schema") != "airlock.rsi-004.result.v1":
        problems.append("receipt schema mismatch")
    if receipt.get("verdict") not in VERDICTS:
        problems.append("receipt verdict is not one of the three formal verdicts")
    if receipt.get("cause_code") not in CAUSE_CODES:
        problems.append("receipt cause_code not in the preregistered set")
    for prefix in ("rootU", "gen1", "gen2", "gen3"):
        gen = receipt["generations"].get(prefix)
        if not isinstance(gen, dict):
            problems.append(f"receipt generations missing {prefix}")
            continue
        for k in RECEIPT_REQUIRED_GEN_KEYS:
            if k not in gen:
                problems.append(f"receipt generations.{prefix} missing {k}")
        rh = gen.get("receipt_hashes", {})
        for rk in ("generation", "promotion", "lineage", "standing"):
            if rk not in rh:
                problems.append(f"receipt generations.{prefix}.receipt_hashes missing {rk}")
    for i, edge in enumerate(receipt.get("required_edges", [])):
        for k in RECEIPT_REQUIRED_EDGE_KEYS:
            if k not in edge:
                problems.append(f"receipt required_edges[{i}] missing {k}")
    if receipt.get("gen4_probe", {}).get("executed") is not False:
        problems.append("receipt gen4_probe.executed must be false")
    return problems


def build_fixture(root: Path) -> dict[str, str]:
    repo = root / "repo"
    repo.mkdir(parents=True)
    sh("git", "init", "-q", str(repo))
    sh("git", "-C", str(repo), "config", "user.name", "RSI-004")
    sh("git", "-C", str(repo), "config", "user.email", "rsi-004@example.invalid")

    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / ".airlock" / "objectives").mkdir(parents=True)
    (repo / "src" / "value.py").write_text("VALUE = 0\n", encoding="utf-8")
    (repo / "src" / "policy.py").write_text(POLICY_V1, encoding="utf-8")
    (repo / "tests" / "check.py").write_text(
        "from src.value import VALUE\n"
        "raise SystemExit(0 if isinstance(VALUE, int) and VALUE >= 0 else 1)\n",
        encoding="utf-8",
    )
    (repo / ".airlock" / "objectives" / "measure.py").write_text(
        "import json\n"
        "from src.value import VALUE\n"
        "print(json.dumps({'value': VALUE}))\n",
        encoding="utf-8",
    )
    objective = {
        "schema": "airlock.objective.v1",
        "name": "RSI-004 fixture value",
        "goal": "Increase fixture value without changing the evaluator.",
        "measure": {
            "command": [sys.executable, ".airlock/objectives/measure.py"],
            "direction": "maximize",
            "unit": "points",
            "repeats": 1,
            "timeout_seconds": 30,
            "pass_env": [],
            "protected_evaluator_paths": [".airlock/objectives/measure.py"],
        },
        "bounds": {
            "max_generations": 1,
            "max_changed_files": 2,
            "max_changed_lines": 10,
        },
        "selection": {
            "minimum_gain": "1",
            "complexity_penalty_per_changed_line": "0",
            "minimum_score_gap": "0",
        },
    }
    write_json(repo / ".airlock" / "objective.json", objective)
    config = {
        "schema": "airlock.config.v1",
        "parallelism": 1,
        "protected_paths": ["tests/**", ".github/**", ".airlock/**", "pyproject.toml"],
        "verification": {
            "static_commands": [[sys.executable, "-m", "py_compile", "src/value.py"]],
            "test_commands": [[sys.executable, "tests/check.py"]],
            "target_commands": [[sys.executable, "tests/check.py"]],
            "timeout_seconds": 30,
            "coverage_mode": "changed-module-reference",
        },
        "providers": {
            "hermes": {
                "command": ["hermes", "-z", "{prompt}"],
                "pass_env": ["HERMES_HOME", "OPENROUTER_API_KEY"],
                "timeout_seconds": 30,
            }
        },
        "init_baseline": {"green": True},
    }
    write_json(repo / ".airlock" / "config.json", config)
    (repo / ".gitignore").write_text(
        ".airlock/runs/\n"
        ".airlock/records/\n"
        ".airlock/improvements/\n"
        ".airlock/verification.key\n"
        ".airlock/index.json\n",
        encoding="utf-8",
    )
    sh("git", "add", ".", cwd=repo)
    sh("git", "commit", "-qm", "rsi-004 base", cwd=repo)
    base = sh("git", "rev-parse", "HEAD", cwd=repo)
    for branch in (RU_BRANCH, R1_BRANCH, R2_BRANCH, R3_BRANCH):
        sh("git", "branch", branch, base, cwd=repo)

    bin_dir = root / "bin"
    bin_dir.mkdir()
    hermes = bin_dir / "hermes"
    hermes.write_text(ROOTU_SHIM, encoding="utf-8")
    hermes.chmod(hermes.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    hermes_home = root / "hermes-home"
    hermes_home.mkdir()

    state = {
        "repo": str(repo),
        "base_commit": base,
        "hermes_executable": str(hermes),
        "hermes_home": str(hermes_home),
        "state_dir": str(root / "state"),
    }
    write_json(root / "state.json", state)
    return state


def _accept_one(report: dict[str, Any], prefix: str) -> dict[str, Any]:
    if report.get("accepted_generations") != 1 or report.get("status") != "COMPLETED_LIMIT":
        raise PreconditionFailure(
            f"{prefix} Nightshift did not select exactly one winner: {report.get('status')}"
        )
    if len(report.get("generations", [])) != 1:
        raise PreconditionFailure(f"{prefix}: expected exactly one generation")
    return report


def candidate_paths(repo: Path, base: str, selected: str) -> list[str]:
    """Files changed between a generation's ACTUAL base and its selected
    commit. The base must be the commit the generation was produced on, not
    the fixture base: for child generations the inherited parent changes
    must not be counted as the child's candidate changes."""
    return sorted(
        row.strip()
        for row in sh("git", "diff", "--name-only", f"{base}..{selected}", cwd=repo).splitlines()
        if row.strip()
    )


def actual_generation_base(
    *, prefix: str, state: dict[str, str], generation: dict[str, Any],
    parent_commit: str | None,
) -> str:
    """The ACTUAL base commit a generation was produced on, cross-checked
    against its signed generation record. rootU/gen1 are produced on the
    fixture base; gen2/gen3 are produced on the parent's exact installed
    (selected) commit."""
    if prefix in ("rootU", "gen1"):
        expected = state["base_commit"]
    else:
        if parent_commit is None:
            raise PreconditionFailure(f"{prefix}: no parent commit to bind the generation base")
        expected = parent_commit
    observed = generation.get("payload", {}).get("base_commit") or generation.get("base_commit")
    if observed != expected:
        raise PreconditionFailure(
            f"{prefix}: signed generation base {observed!r} != expected base {expected!r}"
        )
    return expected


def _verify_selection_common(
    *,
    prefix: str,
    lesson: dict[str, str],
    state: dict[str, str],
    repo: Path,
    state_dir: Path,
    report: dict[str, Any],
    hermes: Path,
    shim_before: str,
    expected_paths: list[str],
    parent_commit: str | None = None,
) -> dict[str, Any]:
    _accept_one(report, prefix)
    receipt_path = resolve_receipt(repo, report["generations"][0]["receipt"])
    generation = read_json(receipt_path)
    key = (repo / ".airlock" / "verification.key").read_bytes()
    if not verify_signature(generation, key):
        raise PreconditionFailure(f"{prefix} Nightshift generation signature did not verify")

    candidate = derive_airlock_memory(
        lesson_id=lesson["lesson_id"],
        title=lesson["title"],
        text=lesson["text"],
        generation_record=generation,
        key=key,
    )
    if candidate.status != "candidate" or candidate.survived != 0:
        raise PreconditionFailure(f"{prefix} selection alone incorrectly earned inheritance")

    selected = candidate.selected_commit
    # The diff base is the generation's ACTUAL base from its signed record:
    # the fixture base for rootU/gen1, the parent's exact installed commit
    # for gen2/gen3. Diffing a child from the fixture base would count the
    # inherited parent policy change as the child's candidate change.
    gen_base = actual_generation_base(
        prefix=prefix, state=state, generation=generation, parent_commit=parent_commit
    )
    candidate_paths_list = candidate_paths(repo, gen_base, selected)
    # NOTE: per-generation path expectations are asserted by the caller, which
    # knows whether this generation rewrites the policy (roots) or runs under
    # an installed one (children). The common check below only guards the
    # evaluator boundary.
    if any(p.startswith("tests/") or p.startswith(".airlock/") for p in candidate_paths_list):
        raise PreconditionFailure(f"{prefix} candidate escaped ordinary code: {candidate_paths_list}")

    if sha256_file(hermes) != shim_before:
        raise PreconditionFailure(f"Hermes shim changed during {prefix} candidate generation")
    lineage = report.get("run_context", {}).get("harness_lineage", [])
    if not lineage or any(row.get("changed") for row in lineage):
        raise PreconditionFailure(f"Hermes harness changed during {prefix}")

    return {
        "phase": f"select-{prefix}",
        "process_pid": os.getpid(),
        "run_id": generation["payload"]["run_id"],
        "generation": generation["payload"]["generation"],
        "generation_record": str(receipt_path),
        "generation_record_sha256": signed_record_sha256(generation),
        "selected_commit": selected,
        "base_commit": gen_base,
        "candidate_paths": candidate_paths_list,
        "expected_paths": expected_paths,
        "shim_sha256": shim_before,
        "harness_frozen": True,
        "nightshift_status": report["status"],
        "nightshift_accepted_generations": report["accepted_generations"],
    }


def _prepare_work_branch(repo: Path, prefix: str, base_commit: str, ref: str) -> str:
    sh("git", "reset", "-q", "--hard", base_commit, cwd=repo)
    sh("git", "checkout", "-q", "-B", WORK_BRANCHES[prefix], base_commit, cwd=repo)
    if sh("git", "status", "--porcelain", cwd=repo):
        raise PreconditionFailure(f"{prefix} work branch is not clean at base")
    branch = {"rootU": RU_BRANCH, "gen1": R1_BRANCH, "gen2": R2_BRANCH, "gen3": R3_BRANCH}[prefix]
    sh("git", "branch", "-f", branch, base_commit, cwd=repo)
    before = sh("git", "rev-parse", ref, cwd=repo)
    if before != base_commit:
        raise PreconditionFailure(f"{prefix} install ref was not created at its base")
    return before


def _write_shim(hermes: Path, code: str) -> str:
    hermes.write_text(code, encoding="utf-8")
    return sha256_file(hermes)


def phase_select_rootU(state_path: Path) -> None:
    state = read_json(state_path)
    repo = Path(state["repo"])
    state_dir = Path(state["state_dir"])
    state_dir.mkdir(parents=True, exist_ok=True)
    hermes = Path(state["hermes_executable"])
    shim_before = sha256_file(hermes)  # ROOTU_SHIM written by build_fixture
    _prepare_work_branch(repo, "rootU", state["base_commit"], RU)
    report = run_nightshift(
        repo,
        objective_path=".airlock/objective.json",
        generations=1,
        agents=1,
        profiles=[],
        budget=0.10,
    )
    result = _verify_selection_common(
        prefix="rootU", lesson=ROOTU_LESSON, state=state, repo=repo,
        state_dir=state_dir, report=report, hermes=hermes,
        shim_before=shim_before, expected_paths=["src/policy.py", "src/value.py"],
    )
    if result["candidate_paths"] != ["src/policy.py", "src/value.py"]:
        raise PreconditionFailure(
            f"rootU candidate must install its unrelated policy and apply it: {result['candidate_paths']}"
        )
    result["install_ref"] = RU
    write_json(state_dir / "rootU_selection.json", result)


def phase_select_gen1(state_path: Path) -> None:
    state = read_json(state_path)
    repo = Path(state["repo"])
    state_dir = Path(state["state_dir"])
    hermes = Path(state["hermes_executable"])
    shim_before = _write_shim(hermes, GEN1_SHIM)
    _prepare_work_branch(repo, "gen1", state["base_commit"], R1)
    report = run_nightshift(
        repo,
        objective_path=".airlock/objective.json",
        generations=1,
        agents=1,
        profiles=[],
        budget=0.10,
    )
    result = _verify_selection_common(
        prefix="gen1", lesson=GEN1_LESSON, state=state, repo=repo,
        state_dir=state_dir, report=report, hermes=hermes,
        shim_before=shim_before, expected_paths=["src/policy.py", "src/value.py"],
    )
    if result["candidate_paths"] != ["src/policy.py", "src/value.py"]:
        raise PreconditionFailure(
            f"gen1 candidate must improve the generator policy and apply it: {result['candidate_paths']}"
        )
    result["install_ref"] = R1
    write_json(state_dir / "gen1_selection.json", result)


def _bind_child_generator(
    *, prefix: str, parent_prefix: str, state: dict[str, str], repo: Path,
    state_dir: Path, expected_base_value: int, child_gen: str,
) -> tuple[str, dict[str, Any]]:
    """Bind a child's generator to its parent's exact installed policy bytes."""
    parent_sel = read_json(state_dir / f"{parent_prefix}_selection.json")
    parent_commit = parent_sel["selected_commit"]
    parent_ref = INSTALL_REFS[parent_prefix]
    if sh("git", "rev-parse", parent_ref, cwd=repo) != parent_commit:
        raise PreconditionFailure(f"{parent_ref} moved before {prefix} selection")

    pristine = state_dir / f"pristine-{parent_prefix}"
    if pristine.exists():
        shutil.rmtree(pristine)
    pristine.mkdir(parents=True)
    archive = subprocess.run(
        ["git", "archive", parent_commit], cwd=str(repo),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    ).stdout
    subprocess.run(["tar", "-x", "-C", str(pristine)], input=archive, check=True)
    policy_pristine = sha256_file(pristine / "src" / "policy.py")
    policy_committed = hashlib.sha256(policy_bytes_at(repo, parent_commit)).hexdigest()
    if policy_pristine != policy_committed:
        raise PreconditionFailure(f"pristine {parent_prefix} policy != committed policy bytes")
    ns: dict[str, Any] = {}
    exec((pristine / "src" / "value.py").read_text(encoding="utf-8"), ns)
    if ns.get("VALUE") != expected_base_value:
        raise PreconditionFailure(
            f"{prefix} base VALUE is {ns.get('VALUE')!r}, expected {expected_base_value}"
        )

    ref = INSTALL_REFS[prefix]
    _prepare_work_branch(repo, prefix, parent_commit, ref)
    hermes = Path(state["hermes_executable"])
    shim_before = _write_shim(
        hermes, inheriting_shim_code(policy_committed, str(pristine), expected_base_value, child_gen)
    )
    binding = {
        "parent_prefix": parent_prefix,
        "parent_commit": parent_commit,
        "installed_policy_sha256": policy_committed,
        "pristine_policy_sha256": policy_pristine,
        "pristine_path": str(pristine),
        "base_value": expected_base_value,
    }
    return shim_before, binding


def phase_select_gen2(state_path: Path) -> None:
    state = read_json(state_path)
    repo = Path(state["repo"])
    state_dir = Path(state["state_dir"])
    hermes = Path(state["hermes_executable"])
    shim_before, binding = _bind_child_generator(
        prefix="gen2", parent_prefix="gen1", state=state, repo=repo,
        state_dir=state_dir, expected_base_value=2, child_gen="gen2",
    )
    report = run_nightshift(
        repo,
        objective_path=".airlock/objective.json",
        generations=1,
        agents=1,
        profiles=[],
        budget=0.10,
    )
    result = _verify_selection_common(
        prefix="gen2", lesson=GEN2_LESSON, state=state, repo=repo,
        state_dir=state_dir, report=report, hermes=hermes,
        shim_before=shim_before, expected_paths=["src/value.py"],
        parent_commit=binding["parent_commit"],
    )
    if result["candidate_paths"] != ["src/value.py"]:
        raise PreconditionFailure(
            f"gen2 candidate must run under the installed policy, not rewrite it: {result['candidate_paths']}"
        )
    policy_after = hashlib.sha256(policy_bytes_at(repo, binding["parent_commit"])).hexdigest()
    if policy_after != binding["installed_policy_sha256"]:
        raise PreconditionFailure("installed gen1 policy bytes changed during gen2's run")
    result["install_ref"] = R2
    result["generator_binding"] = binding
    write_json(state_dir / "gen2_selection.json", result)


def phase_select_gen3(state_path: Path) -> None:
    state = read_json(state_path)
    repo = Path(state["repo"])
    state_dir = Path(state["state_dir"])
    hermes = Path(state["hermes_executable"])
    shim_before, binding = _bind_child_generator(
        prefix="gen3", parent_prefix="gen2", state=state, repo=repo,
        state_dir=state_dir, expected_base_value=4, child_gen="gen3",
    )
    report = run_nightshift(
        repo,
        objective_path=".airlock/objective.json",
        generations=1,
        agents=1,
        profiles=[],
        budget=0.10,
    )
    result = _verify_selection_common(
        prefix="gen3", lesson=GEN3_LESSON, state=state, repo=repo,
        state_dir=state_dir, report=report, hermes=hermes,
        shim_before=shim_before, expected_paths=["src/value.py"],
        parent_commit=binding["parent_commit"],
    )
    if result["candidate_paths"] != ["src/value.py"]:
        raise PreconditionFailure(
            f"gen3 candidate must run under the installed policy, not rewrite it: {result['candidate_paths']}"
        )
    policy_after = hashlib.sha256(policy_bytes_at(repo, binding["parent_commit"])).hexdigest()
    if policy_after != binding["installed_policy_sha256"]:
        raise PreconditionFailure("installed gen2 policy bytes changed during gen3's run")
    result["install_ref"] = R3
    result["generator_binding"] = binding
    write_json(state_dir / "gen3_selection.json", result)


def _install(*, prefix: str, state_path: Path, retain: bool = False) -> None:
    state = read_json(state_path)
    repo = Path(state["repo"])
    state_dir = Path(state["state_dir"])
    sel = read_json(state_dir / f"{prefix}_selection.json")
    generation = read_json(Path(sel["generation_record"]))
    key = (repo / ".airlock" / "verification.key").read_bytes()
    lesson = LESSONS[prefix]
    ref = INSTALL_REFS[prefix]
    branch = {"rootU": RU_BRANCH, "gen1": R1_BRANCH, "gen2": R2_BRANCH, "gen3": R3_BRANCH}[prefix]

    # Fresh process reconstructs CANDIDATE from disk, not from volatile state.
    recovered = derive_airlock_memory(
        lesson_id=lesson["lesson_id"],
        title=lesson["title"],
        text=lesson["text"],
        generation_record=generation,
        key=key,
    )
    if recovered.status != "candidate":
        raise PreconditionFailure(f"{prefix} restart did not reconstruct candidate standing")
    selected = recovered.selected_commit
    before = sh("git", "rev-parse", ref, cwd=repo)
    if before != sel["base_commit"]:
        raise PreconditionFailure(f"{prefix} installation ref was not at its base on restart")

    # Negative control: a validly signed receipt for the wrong commit must not earn inheritance.
    wrong_payload = {
        "schema": AIRLOCK_PROMOTION_SCHEMA,
        "run_id": generation["payload"]["run_id"],
        "generation": generation["payload"]["generation"],
        "base_commit": generation["payload"]["base_commit"],
        "generation_receipt_sha256": signed_record_sha256(generation),
        "selected_commit": sel["base_commit"],
        "observed_branch_after": selected,
        "status": "INSTALLED",
    }
    wrong_rejected = False
    try:
        derive_airlock_memory(
            lesson_id=lesson["lesson_id"],
            title=lesson["title"],
            text=lesson["text"],
            generation_record=generation,
            promotion_record=sign(wrong_payload, key),
            key=key,
        )
    except EvidenceError:
        wrong_rejected = True
    if not wrong_rejected:
        raise PreconditionFailure(f"{prefix} wrong-commit promotion unexpectedly earned inheritance")

    sh("git", "branch", "-f", branch, selected, cwd=repo)
    observed = sh("git", "rev-parse", ref, cwd=repo)
    if observed != selected:
        raise PreconditionFailure(f"{prefix} receiver did not observe exact selected commit")

    support = state_dir / f"{prefix}_support.witness"
    support.write_text(f"RSI-004 {prefix} receiver support live\n", encoding="utf-8")
    promotion_payload = {
        "schema": AIRLOCK_PROMOTION_SCHEMA,
        "run_id": generation["payload"]["run_id"],
        "generation": generation["payload"]["generation"],
        "base_commit": generation["payload"]["base_commit"],
        "generation_receipt_sha256": signed_record_sha256(generation),
        "selected_commit": selected,
        "installation_ref": ref,
        "observed_branch_before": before,
        "observed_branch_after": observed,
        "support_witness_sha256": sha256_file(support),
        "status": "INSTALLED",
        "claim_boundary": "Synthetic receiver installation into an isolated fixture ref; not deployment authority.",
    }
    promotion = sign(promotion_payload, key)
    promotion_path = state_dir / f"{prefix}_promotion.json"
    write_json(promotion_path, promotion)
    promotion_sha = signed_record_sha256(promotion)

    standing_record: dict[str, Any] | None = None
    standing_path: Path | None = None
    standing_sha: str | None = None
    if retain:
        # rootU carries an explicit RETAIN standing record per the prereg binding.
        standing_payload = {
            "schema": AIRLOCK_STANDING_SCHEMA,
            "selected_commit": selected,
            "promotion_receipt_sha256": promotion_sha,
            "decision": "RETAIN",
            "reason": "SUPPORT_WITNESS_LIVE",
            "observed_support_witness": "PRESENT",
            "installed_state_action": "NONE",
        }
        standing_record = sign(standing_payload, key)
        standing_path = state_dir / f"{prefix}_standing.json"
        write_json(standing_path, standing_record)
        standing_sha = signed_record_sha256(standing_record)

    inherited = derive_airlock_memory(
        lesson_id=lesson["lesson_id"],
        title=lesson["title"],
        text=lesson["text"],
        generation_record=generation,
        promotion_record=promotion,
        standing_record=standing_record,
        key=key,
    )
    if inherited.status != "inherited" or inherited.survived != 1:
        raise PreconditionFailure(f"{prefix} exact installation failed to earn inherited standing")

    result = {
        "phase": f"install-{prefix}",
        "process_pid": os.getpid(),
        "recovered_preinstall_status": recovered.status,
        "wrong_install_rejected": wrong_rejected,
        "promotion_record": str(promotion_path),
        "promotion_record_sha256": promotion_sha,
        "standing_record": str(standing_path) if standing_path else None,
        "standing_record_sha256": standing_sha,
        "support_witness": str(support),
        "support_witness_sha256": sha256_file(support),
        "install_ref_before": before,
        "install_ref_after": observed,
        "install_ref_byte_sha256": ref_bytes(ref, repo),
        "installed_commit_tree": sh("git", "rev-parse", f"{observed}^{{tree}}", cwd=repo),
        "installed_policy_sha256": hashlib.sha256(policy_bytes_at(repo, observed)).hexdigest(),
        "memory": inherited.to_dict(),
    }
    write_json(state_dir / f"{prefix}_installation.json", result)


def phase_install_rootU(state_path: Path) -> None:
    _install(prefix="rootU", state_path=state_path, retain=True)


def phase_install_gen1(state_path: Path) -> None:
    _install(prefix="gen1", state_path=state_path)


def phase_install_gen2(state_path: Path) -> None:
    _install(prefix="gen2", state_path=state_path)


def phase_install_gen3(state_path: Path) -> None:
    _install(prefix="gen3", state_path=state_path)


def phase_mint_lineage(state_path: Path) -> None:
    """Fresh process mints receiver-signed lineage records from the ACTUAL
    promotion receipts and ACTUAL installed-policy bytes on disk. Single
    required parent per generation; explicit ROOT where there is no parent."""
    state = read_json(state_path)
    repo = Path(state["repo"])
    state_dir = Path(state["state_dir"])
    key = (repo / ".airlock" / "verification.key").read_bytes()
    bundles = {p: load_bundle(state_dir, p) for p in ("rootU", "gen1", "gen2", "gen3")}

    edges: list[dict[str, Any]] = []
    for prefix, parent_prefix in (
        ("rootU", None),
        ("gen1", None),
        ("gen2", "gen1"),
        ("gen3", "gen2"),
    ):
        b = bundles[prefix]
        subject_sha = b["installation"]["promotion_record_sha256"]
        if parent_prefix is None:
            record = mint_lineage_record(
                subject_lesson_id=b["lesson"]["lesson_id"],
                subject_promotion_receipt_sha256=subject_sha,
                key=key,
            )
        else:
            pb = bundles[parent_prefix]
            parent_commit = pb["selection"]["selected_commit"]
            parent_policy_bytes = policy_bytes_at(repo, parent_commit)
            record = mint_lineage_record(
                subject_lesson_id=b["lesson"]["lesson_id"],
                subject_promotion_receipt_sha256=subject_sha,
                key=key,
                parent_lesson_id=pb["lesson"]["lesson_id"],
                parent_promotion_receipt_sha256=pb["installation"]["promotion_record_sha256"],
                parent_selected_commit=parent_commit,
                parent_installed_policy_sha256=hashlib.sha256(parent_policy_bytes).hexdigest(),
            )
            edges.append(
                {
                    "child_prefix": prefix,
                    "child_lesson_id": b["lesson"]["lesson_id"],
                    "parent_prefix": parent_prefix,
                    "parent_lesson_id": pb["lesson"]["lesson_id"],
                    "parent_promotion_receipt_sha256": pb["installation"]["promotion_record_sha256"],
                    "parent_selected_commit": parent_commit,
                    "parent_installed_policy_sha256": hashlib.sha256(parent_policy_bytes).hexdigest(),
                    "edge_record_sha256": signed_record_sha256(record),
                }
            )
        path = state_dir / f"{prefix}_lineage.json"
        write_json(path, record)
        if not verify_hmac_record(record, key):
            raise PreconditionFailure(f"{prefix} lineage record failed to verify after minting")

    minted_records = [read_json(state_dir / f"{p}_lineage.json") for p in ("rootU", "gen1", "gen2", "gen3")]
    write_json(
        state_dir / "lineage.json",
        {
            "phase": "mint-lineage",
            "process_pid": os.getpid(),
            "required_edges": edges,
            "roots": ["rootU", "gen1"],
            "lineage_record_set_sha256": lineage_record_set_sha256(minted_records),
        },
    )


def _receipt_hashes(state_dir: Path, bundles: dict[str, dict[str, Any]]) -> dict[str, dict[str, str | None]]:
    out: dict[str, dict[str, str | None]] = {}
    for prefix, b in bundles.items():
        sel = b["selection"]
        inst = b["installation"]
        lineage_path = state_dir / f"{prefix}_lineage.json"
        out[prefix] = {
            "generation": sel["generation_record_sha256"],
            "promotion": inst["promotion_record_sha256"],
            "lineage": sha256_file(lineage_path) if lineage_path.exists() else None,
            "standing": inst.get("standing_record_sha256"),
        }
    return out


def _installed_hashes(repo: Path, bundles: dict[str, dict[str, Any]]) -> tuple[dict[str, str], dict[str, str]]:
    ref_hashes: dict[str, str] = {}
    policy_hashes: dict[str, str] = {}
    for prefix, b in bundles.items():
        ref = INSTALL_REFS[prefix]
        ref_hashes[prefix] = ref_bytes(ref, repo)
        policy_hashes[prefix] = hashlib.sha256(
            policy_bytes_at(repo, b["selection"]["selected_commit"])
        ).hexdigest()
    return ref_hashes, policy_hashes


def phase_checkpoint(state_path: Path) -> None:
    """Fresh process reloads every record from disk and verifies the
    pre-REOPEN projection: all four generations inherited. Then it freezes
    the hashes of every historical receipt and every installed ref/policy
    byte sequence. Nothing here mutates installed state."""
    state = read_json(state_path)
    repo = Path(state["repo"])
    state_dir = Path(state["state_dir"])
    key = (repo / ".airlock" / "verification.key").read_bytes()
    bundles = {p: load_bundle(state_dir, p) for p in ("rootU", "gen1", "gen2", "gen3")}

    try:
        projection = project_bundles(bundles, repo, key)
    except EvidenceError as exc:
        raise PreconditionFailure(f"pre-REOPEN lineage projection failed: {exc}") from exc

    standings = {b["lesson"]["lesson_id"]: projection[b["lesson"]["lesson_id"]].status for b in bundles.values()}
    lesson_ids = {b["lesson"]["lesson_id"] for b in bundles.values()}
    if any(s != "inherited" for s in standings.values()):
        raise PreconditionFailure(f"pre-REOPEN standings not all inherited: {standings}")
    established_ids = {m.lesson_id for m in established(list(projection.values()))}
    if established_ids != lesson_ids:
        raise PreconditionFailure(f"pre-REOPEN established set wrong: {sorted(established_ids)}")

    ref_hashes, policy_hashes = _installed_hashes(repo, bundles)
    # The lineage record set is frozen here: recompute its digest from the
    # records on disk and require it to equal the mint-time digest. The
    # harness never re-mints, reorders, or edits lineage records between
    # projections.
    lineage_summary = read_json(state_dir / "lineage.json")
    checkpoint_lineage_hash = lineage_record_set_sha256(
        [read_json(state_dir / f"{p}_lineage.json") for p in ("rootU", "gen1", "gen2", "gen3")]
    )
    if checkpoint_lineage_hash != lineage_summary["lineage_record_set_sha256"]:
        raise PreconditionFailure("lineage record set changed between minting and checkpoint")
    checkpoint = {
        "phase": "checkpoint",
        "process_pid": os.getpid(),
        "pre_reopen_standings": standings,
        "pre_reopen_established": sorted(established_ids),
        "historical_receipt_hashes": _receipt_hashes(state_dir, bundles),
        "installed_ref_hashes": ref_hashes,
        "installed_policy_hashes": policy_hashes,
        "lineage_record_set_sha256": checkpoint_lineage_hash,
    }
    write_json(state_dir / "checkpoint.json", checkpoint)


def phase_reopen(state_path: Path) -> None:
    """Fresh process re-verifies the checkpoint from disk, rejects a forged
    REOPEN, issues the valid receiver-signed REOPEN(gen1), then terminates:
    the post-REOPEN projection runs in a fresh process from persisted
    evidence (the restart boundary)."""
    state = read_json(state_path)
    repo = Path(state["repo"])
    state_dir = Path(state["state_dir"])
    key = (repo / ".airlock" / "verification.key").read_bytes()
    bundles = {p: load_bundle(state_dir, p) for p in ("rootU", "gen1", "gen2", "gen3")}
    checkpoint = read_json(state_dir / "checkpoint.json")
    gen1 = bundles["gen1"]

    # Re-verify every precondition from disk in this fresh process.
    try:
        projection = project_bundles(bundles, repo, key)
    except EvidenceError as exc:
        raise PreconditionFailure(f"lineage binding failure before REOPEN: {exc}") from exc
    standings = {b["lesson"]["lesson_id"]: projection[b["lesson"]["lesson_id"]].status for b in bundles.values()}
    if any(s != "inherited" for s in standings.values()):
        raise PreconditionFailure(f"reopen precondition: standings not all inherited: {standings}")
    ref_hashes, policy_hashes = _installed_hashes(repo, bundles)
    if ref_hashes != checkpoint["installed_ref_hashes"] or policy_hashes != checkpoint["installed_policy_hashes"]:
        raise PreconditionFailure("installed state moved between checkpoint and REOPEN")

    # Negative control: a forged REOPEN (wrong signer) must change nothing.
    forged_payload = {
        "schema": AIRLOCK_STANDING_SCHEMA,
        "selected_commit": gen1["selection"]["selected_commit"],
        "promotion_receipt_sha256": gen1["installation"]["promotion_record_sha256"],
        "decision": "REOPEN",
        "reason": "SUPPORT_WITNESS_MISSING",
        "observed_support_witness": "MISSING",
        "installed_state_action": "NONE",
    }
    forged_rejected = False
    try:
        derive_airlock_memory(
            lesson_id=gen1["lesson"]["lesson_id"],
            title=gen1["lesson"]["title"],
            text=gen1["lesson"]["text"],
            generation_record=gen1["generation"],
            promotion_record=gen1["promotion"],
            standing_record=sign(forged_payload, os.urandom(32)),
            key=key,
        )
    except EvidenceError:
        forged_rejected = True
    if not forged_rejected:
        raise PreconditionFailure("forged REOPEN was unexpectedly accepted")

    # Controlled support loss for gen1's promotion evidence.
    support = Path(gen1["installation"]["support_witness"])
    if support.exists():
        raise PreconditionFailure("REOPEN control requires gen1's support witness to be absent")

    standing_payload = {
        "schema": AIRLOCK_STANDING_SCHEMA,
        "selected_commit": gen1["selection"]["selected_commit"],
        "promotion_receipt_sha256": gen1["installation"]["promotion_record_sha256"],
        "decision": "REOPEN",
        "reason": "SUPPORT_WITNESS_MISSING",
        "observed_support_witness": "MISSING",
        "installed_state_action": "NONE",
        "claim_boundary": "Synthetic support-loss control; tests propagation of signed REOPEN, not real-world evidence-loss detection.",
    }
    standing = sign(standing_payload, key)
    standing_path = state_dir / "gen1_standing.json"
    write_json(standing_path, standing)
    write_json(
        state_dir / "reopen.json",
        {
            "phase": "reopen",
            "process_pid": os.getpid(),
            "standing_record": str(standing_path),
            "standing_record_sha256": signed_record_sha256(standing),
            "decision": "REOPEN",
            "bound_promotion_receipt_sha256": standing_payload["promotion_receipt_sha256"],
            "gen1_support_witness_observed": "MISSING",
            "forged_reopen_rejected": forged_rejected,
        },
    )

    # Restart boundary: the projection process terminates here. Reprojection
    # runs in a fresh process from persisted evidence only.
    script = Path(__file__).resolve()
    cp = subprocess.run(
        [sys.executable, str(script), EXECUTE_PRIMARY_FLAG, "--phase", "reproject",
         "--state", str(state_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_phase_env(state),
    )
    if cp.returncode == 42:
        raise PreconditionFailure(cp.stderr.strip().splitlines()[-1] if cp.stderr.strip() else "reproject")
    if cp.returncode != 0:
        raise RuntimeError(
            f"RSI-004 reproject phase failed ({cp.returncode})\nstdout:\n{cp.stdout}\nstderr:\n{cp.stderr}"
        )


def phase_reproject(state_path: Path) -> None:
    """Fresh process: reload every record from disk, reproject twice
    (determinism), require the propagated standings, compute the gen4
    admission probe (never executed), verify history is byte-identical,
    decide the verdict, and write the receipt."""
    state = read_json(state_path)
    repo = Path(state["repo"])
    state_dir = Path(state["state_dir"])
    key = (repo / ".airlock" / "verification.key").read_bytes()
    checkpoint = read_json(state_dir / "checkpoint.json")
    reopen = read_json(state_dir / "reopen.json")
    bundles = {p: load_bundle(state_dir, p) for p in ("rootU", "gen1", "gen2", "gen3")}
    # The REOPEN standing record is loaded from disk like every other record.
    bundles["gen1"]["standing"] = read_json(Path(reopen["standing_record"]))

    generations, lineage_records, installed_policies = projector_inputs(bundles, repo)

    # Restart-boundary lineage check: the record set reloaded from disk must
    # hash exactly to the checkpoint digest. The harness never re-mints,
    # reorders, or edits lineage records between projections.
    reproject_lineage_hash = lineage_record_set_sha256(lineage_records)
    if reproject_lineage_hash != checkpoint["lineage_record_set_sha256"]:
        raise PreconditionFailure("lineage record set changed between checkpoint and reprojection")

    try:
        run_a = project_lineage_memories(
            generations, lineage_records, installed_policies, key
        )
        run_b = project_lineage_memories(
            generations, lineage_records, installed_policies, key
        )
    except EvidenceError as exc:
        raise PreconditionFailure(f"lineage binding failure at reprojection: {exc}") from exc
    snap = lambda proj: {lid: proj[lid].to_dict() for lid in sorted(proj)}  # noqa: E731
    deterministic = json.dumps(snap(run_a), sort_keys=True) == json.dumps(snap(run_b), sort_keys=True)

    by_lesson = {b["lesson"]["lesson_id"]: b["prefix"] for b in bundles.values()}
    standings = {by_lesson[lid]: mem.status for lid, mem in run_a.items() if lid in by_lesson}
    gen1_questioned = standings.get("gen1") == "questioned"
    if not gen1_questioned:
        raise PreconditionFailure(
            f"valid REOPEN did not question gen1 (status={standings.get('gen1')}); propagation question is moot"
        )
    for lid, mem in run_a.items():
        if lid in by_lesson and mem.to_dict()["installed_state_action"] != "NONE":
            raise PreconditionFailure(f"{by_lesson[lid]} standing acquired rollback authority")

    paths = witness_paths(run_a)
    try:
        probe_disposition, probe_info = probe_gen4_admission(
            key=key,
            bundles=bundles,
            generations=generations,
            lineage_records=lineage_records,
            installed_policies=installed_policies,
        )
    except EvidenceError as exc:
        raise PreconditionFailure(f"gen4 probe lineage failure: {exc}") from exc

    final_receipts = _receipt_hashes(state_dir, bundles)
    # gen1's REOPEN standing is new post-checkpoint; it is bound separately in
    # reopen_evidence, not in the historical-receipt comparison.
    final_receipts["gen1"]["standing"] = checkpoint["historical_receipt_hashes"]["gen1"]["standing"]
    receipts_unchanged = final_receipts == checkpoint["historical_receipt_hashes"]
    ref_hashes, policy_hashes = _installed_hashes(repo, bundles)
    refs_unchanged = (
        ref_hashes == checkpoint["installed_ref_hashes"]
        and policy_hashes == checkpoint["installed_policy_hashes"]
    )

    pre_reopen_ok = True  # established by phase_checkpoint from the same disk state
    lineage_ok = True  # the projection above verified every lineage binding
    verdict, cause_code = decide_verdict(
        pre_reopen_ok=pre_reopen_ok,
        lineage_ok=lineage_ok,
        refs_unchanged=refs_unchanged,
        receipts_unchanged=receipts_unchanged,
        deterministic=deterministic,
        gen1_questioned=gen1_questioned,
        standings=standings,
        gen4_probe=probe_disposition,
    )

    lineage_summary = read_json(state_dir / "lineage.json")
    receipt = {
        "schema": "airlock.rsi-004.result.v1",
        "experiment": "RSI-004 lineage-aware inheritance",
        "verdict": verdict,
        "cause_code": cause_code,
        "airlock_base_sha": AIRLOCK_BASE_MAIN,
        "verified_memory_sha": VERIFIED_MEMORY_COMMIT,
        "verified_memory_evidence_py_sha256": EVIDENCE_PY_SHA256,
        "preregistration_sha256": sha256_file(PREREG_PATH),
        "generations": {
            prefix: {
                "lesson_id": b["lesson"]["lesson_id"],
                "selected_commit": b["selection"]["selected_commit"],
                "install_ref": INSTALL_REFS[prefix],
                "receipt_hashes": final_receipts[prefix],
            }
            for prefix, b in bundles.items()
        },
        "required_edges": lineage_summary["required_edges"],
        "pre_reopen_established": checkpoint["pre_reopen_established"],
        "pre_reopen_standings": checkpoint["pre_reopen_standings"],
        "reopen_evidence": {
            "standing_record": reopen["standing_record"],
            "standing_record_sha256": reopen["standing_record_sha256"],
            "decision": reopen["decision"],
            "bound_promotion_receipt_sha256": reopen["bound_promotion_receipt_sha256"],
            "gen1_support_witness_observed": reopen["gen1_support_witness_observed"],
            "forged_reopen_rejected": reopen["forged_reopen_rejected"],
        },
        "restart_evidence": {
            "checkpoint_phase_pid": checkpoint["process_pid"],
            "reopen_phase_pid": reopen["process_pid"],
            "reproject_phase_pid": os.getpid(),
            "fresh_process": (
                checkpoint["process_pid"] != reopen["process_pid"] != os.getpid()
            ),
        },
        "post_reopen_standings": standings,
        "lineage_witness_paths": paths,
        "lineage_record_set_sha256_checkpoint": checkpoint["lineage_record_set_sha256"],
        "lineage_record_set_sha256_reprojection": reproject_lineage_hash,
        "lineage_record_set_unchanged": (
            reproject_lineage_hash == checkpoint["lineage_record_set_sha256"]
        ),
        "gen4_probe": probe_info,
        "historical_receipt_hashes": {
            "checkpoint": checkpoint["historical_receipt_hashes"],
            "final": final_receipts,
            "unchanged": receipts_unchanged,
        },
        "installed_ref_hashes": {
            prefix: {
                "at_install": bundles[prefix]["installation"]["install_ref_byte_sha256"],
                "checkpoint": checkpoint["installed_ref_hashes"][prefix],
                "final": ref_hashes[prefix],
            }
            for prefix in bundles
        },
        "installed_policy_hashes": {
            prefix: {
                "checkpoint": checkpoint["installed_policy_hashes"][prefix],
                "final": policy_hashes[prefix],
            }
            for prefix in bundles
        },
        "installed_refs_unchanged": refs_unchanged,
        "reprojection_deterministic": deterministic,
        "phase_process_pids": {
            "checkpoint": checkpoint["process_pid"],
            "reopen": reopen["process_pid"],
            "reproject": os.getpid(),
        },
        "claim_boundary": [
            "Four installed generations plus one unexecuted admission probe. Not a claim about open-ended recursion.",
            "Single-required-parent lineage only; arbitrary multi-parent lineage is outside this experiment's claim boundary.",
            "Does not earn the final RSI claim: a later test still needs an inherited method mutation to beat its unchanged parent on fresh verified results per dollar.",
            "Deterministic fake Hermes through the real Nightshift path; no paid live-Hermes claim.",
            "Does not claim hostile-process isolation; the Hermes profile is not a sandbox.",
            "Installation is isolated synthetic Git refs, not deployment authority.",
            "PASS under this ID validates the repaired projector's lineage semantics; it does not re-litigate RSI-003, which stays frozen.",
        ],
    }
    problems = validate_receipt_bindings(receipt)
    if problems:
        raise PreconditionFailure(f"receipt failed binding validation: {problems}")
    write_json(state_dir / "result.json", receipt)


def primary_gate(argv: list[str]) -> bool:
    """The explicit execution gate. The primary sequence is encoded but never
    invoked unless this returns True. Default invocation stays closed."""
    return EXECUTE_PRIMARY_FLAG in argv


def _phase_env(state: dict[str, str]) -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = str(Path(state["hermes_executable"]).parent) + os.pathsep + env.get("PATH", "")
    env["HERMES_HOME"] = state["hermes_home"]
    env["OPENROUTER_API_KEY"] = "rsi-fixture-secret"
    return env


def run_phase(script: Path, phase: str, state_path: Path, env: dict[str, str]) -> None:
    cp = subprocess.run(
        [sys.executable, str(script), EXECUTE_PRIMARY_FLAG,
         "--phase", phase, "--state", str(state_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    if cp.returncode == 42:
        # The phase reported a preregistered precondition failure; map it to
        # INCONCLUSIVE rather than a harness crash.
        raise PreconditionFailure(cp.stderr.strip().splitlines()[-1] if cp.stderr.strip() else phase)
    if cp.returncode != 0:
        raise RuntimeError(
            f"RSI-004 phase {phase} failed ({cp.returncode})\nstdout:\n{cp.stdout}\nstderr:\n{cp.stderr}"
        )


def _cause_for_precondition(reason: str) -> str:
    low = reason.lower()
    if "lineage" in low:
        return "LINEAGE_BINDING_FAILURE"
    if "reopen" in low:
        return "REOPEN_NOT_OBSERVED"
    return "CHECKPOINT_NOT_ESTABLISHED"


def inconclusive_result(reason: str, state_dir: Path | None) -> dict:
    return {
        "schema": "airlock.rsi-004.result.v1",
        "experiment": "RSI-004 lineage-aware inheritance",
        "verdict": VERDICT_INCONCLUSIVE,
        "cause_code": _cause_for_precondition(reason),
        "reason": reason,
        "preregistration_sha256": sha256_file(PREREG_PATH),
        "airlock_base_sha": AIRLOCK_BASE_MAIN,
        "verified_memory_sha": VERIFIED_MEMORY_COMMIT,
        "verified_memory_evidence_py_sha256": EVIDENCE_PY_SHA256,
    }


def self_check() -> list[str]:
    """Verify every prereg binding and every fail-closed gate. Returns a list
    of problems; empty means clean. Any problem stops execution before it
    starts. Performs zero Nightshift generations, zero candidate executions,
    zero REOPEN mutations, and zero primary contact by construction: it
    never calls run_nightshift, never mints standing records, never writes
    a result, and never creates the primary-contact marker."""
    problems: list[str] = []
    source = Path(__file__).read_text(encoding="utf-8")

    # 1. Preregistration bytes are exactly the frozen ones; bindings complete.
    try:
        prereg_bytes = PREREG_PATH.read_bytes()
    except Exception as exc:
        return [f"preregistration unreadable: {exc}"]
    if hashlib.sha256(prereg_bytes).hexdigest() != PREREG_SHA256:
        return ["preregistration bytes differ from the frozen SHA-256"]
    try:
        prereg = json.loads(prereg_bytes.decode("utf-8"))
    except Exception as exc:
        return [f"preregistration invalid JSON: {exc}"]
    if prereg.get("schema") != "airlock.rsi-004.preregistration.v1":
        problems.append("preregistration schema mismatch")
    bindings = prereg.get("bindings", [])
    if len(bindings) != 16:
        problems.append(f"preregistration has {len(bindings)} bindings, expected 16")
    for b in bindings:
        bid = b.get("id", "?")
        if b.get("kind") == "pinned" and not b.get("value"):
            problems.append(f"binding {bid}: pinned but value missing (ambiguous)")
        if b.get("kind") in ("derived", "pinned_rule") and not (b.get("derivation") or b.get("value")):
            problems.append(f"binding {bid}: no derivation rule (ambiguous)")
        if not b.get("verification"):
            problems.append(f"binding {bid}: no verification rule (ambiguous)")

    # 2. Implementation constants match the preregistration.
    base = prereg.get("base", {})
    dep = prereg.get("dependency", {})
    if AIRLOCK_BASE_MAIN != base.get("main_commit"):
        problems.append("AIRLOCK_BASE_MAIN does not match prereg base.main_commit")
    if VERIFIED_MEMORY_COMMIT != dep.get("commit"):
        problems.append("VERIFIED_MEMORY_COMMIT does not match prereg dependency.commit")
    if EVIDENCE_PY_SHA256 != dep.get("evidence_py_sha256"):
        problems.append("EVIDENCE_PY_SHA256 does not match prereg dependency.evidence_py_sha256")

    # 3. Exactly three formal verdicts; diagnostics only through cause_code.
    if set(prereg.get("verdicts", {})) != {VERDICT_PASS, VERDICT_FAIL, VERDICT_INCONCLUSIVE}:
        problems.append("preregistration does not expose exactly the three formal verdicts")
    if set(prereg.get("cause_codes", {})) != set(CAUSE_CODES):
        problems.append("preregistration cause_codes do not match the implementation set")
    if not prereg.get("verdict_precedence"):
        problems.append("preregistration verdict_precedence missing")

    # 4. The branch must descend from the pinned Airlock main commit.
    try:
        repo_root = Path(__file__).resolve().parents[2]
        cp = subprocess.run(
            ["git", "merge-base", "--is-ancestor", AIRLOCK_BASE_MAIN, "HEAD"],
            cwd=str(repo_root),
        )
        if cp.returncode != 0:
            problems.append(f"{AIRLOCK_BASE_MAIN} is not an ancestor of HEAD")
    except Exception as exc:
        problems.append(f"could not verify main-commit ancestry: {exc}")

    # 5. The imported projector is the pinned one: exact bytes AND exact commit.
    try:
        evidence_py = Path(_ovm_pkg.__file__).with_name("evidence.py")
        if sha256_file(evidence_py) != EVIDENCE_PY_SHA256:
            problems.append("imported openline_verified_memory evidence.py != pinned digest")
        from importlib.metadata import distribution, PackageNotFoundError

        try:
            dist = distribution("openline-verified-memory")
            direct_url = dist.read_text("direct_url.json")
        except (PackageNotFoundError, FileNotFoundError, KeyError):
            direct_url = None
        commit_id = None
        if direct_url:
            try:
                commit_id = json.loads(direct_url).get("vcs_info", {}).get("commit_id")
            except Exception:
                commit_id = None
        if commit_id != VERIFIED_MEMORY_COMMIT:
            problems.append(
                "installed openline-verified-memory commit_id != pinned commit "
                f"(got {commit_id!r}); refusing to trust an unverifiable install"
            )
    except Exception as exc:
        problems.append(f"could not verify projector provenance: {exc}")

    # 6. No existing primary receipt/result and no prior primary-contact marker.
    if PRIMARY_CONTACT_MARKER.exists():
        problems.append("prior RSI-004 primary-contact marker exists; anti-rescue is in effect")
    if Path(__file__).with_name("result.json").exists():
        problems.append("an RSI-004 primary result already exists in the experiment tree")
    try:
        if (repo_root / "proofs" / "rsi-004").exists():
            problems.append("proofs/rsi-004 already exists; the primary may have run")
    except Exception as exc:
        problems.append(f"could not check proofs dir: {exc}")

    # 7. Single-required-parent claim boundary, checked structurally.
    try:
        tree = ast.parse(source)

        mint_fn = next(
            (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "mint_lineage_record"),
            None,
        )
        if mint_fn is None:
            problems.append("mint_lineage_record missing")
        else:
            arg_names = [a.arg for a in mint_fn.args.args] + [a.arg for a in mint_fn.args.kwonlyargs]
            if "parent_lesson_id" not in arg_names:
                problems.append("mint_lineage_record lost its single-parent parameter")
            if any("parents" in a for a in arg_names):
                problems.append("mint_lineage_record grew a multi-parent parameter")
            literals = [
                n.value for n in ast.walk(mint_fn)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
            ]
            if "parents" in literals:
                problems.append("mint_lineage_record builds a multi-parent payload")

        schema_text = ""
        for b in bindings:
            if b.get("id") == "lineage_schema":
                schema_text = str(b.get("value") or b.get("derivation") or "")
        if "parent_lesson_id" not in schema_text or "parents" in schema_text:
            problems.append("prereg lineage_schema does not describe single-parent lineage")
    except Exception as exc:
        problems.append(f"lineage-boundary AST check failed: {exc}")

    # 8. gen4 is probe-only: no execution path exists for it.
    try:
        tree = ast.parse(source)

        class ParentTracker(ast.NodeVisitor):
            def __init__(self):
                self.stack: list[ast.AST] = []
                self.nightshift_in: set[str] = set()
                self.names: set[str] = set()

            def generic_visit(self, node):
                if isinstance(node, ast.FunctionDef):
                    self.names.add(node.name)
                self.stack.append(node)
                super().generic_visit(node)
                self.stack.pop()

            def visit_Call(self, node):
                func = node.func
                name = ""
                if isinstance(func, ast.Attribute):
                    name = func.attr
                elif isinstance(func, ast.Name):
                    name = func.id
                    self.names.add(name)
                if name == "run_nightshift":
                    enclosing = next(
                        (n for n in reversed(self.stack) if isinstance(n, ast.FunctionDef)),
                        None,
                    )
                    self.nightshift_in.add(enclosing.name if enclosing else "<module>")
                self.generic_visit(node)

        tracker = ParentTracker()
        tracker.visit(tree)
        allowed_selects = {"phase_select_rootU", "phase_select_gen1", "phase_select_gen2", "phase_select_gen3"}
        if tracker.nightshift_in != allowed_selects:
            problems.append(
                f"run_nightshift reachable from {sorted(tracker.nightshift_in)}, "
                f"expected exactly {sorted(allowed_selects)}"
            )
        probe_fn = next(
            (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "probe_gen4_admission"),
            None,
        )
        if probe_fn is None:
            problems.append("probe_gen4_admission missing")
        else:
            probe_calls = [
                n for n in ast.walk(probe_fn) if isinstance(n, ast.Call)
                and getattr(n.func, "attr", getattr(n.func, "id", "")) == "run_nightshift"
            ]
            if probe_calls:
                problems.append("probe_gen4_admission can reach run_nightshift")
        for forbidden in ("R4", "GEN4_INSTALL_REF", "phase_select_gen4", "phase_install_gen4"):
            if forbidden in tracker.names:
                problems.append(f"gen4 execution surface exists: {forbidden}")
    except Exception as exc:
        problems.append(f"gen4 probe-only AST check failed: {exc}")

    # 9. Diagnostics only through cause_code: no other formal-verdict strings.
    try:
        tree = ast.parse(source)
        verdict_re = __import__("re").compile(r"^(PASS|FAIL|INCONCLUSIVE)_RSI_004")
        found = {
            n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and verdict_re.match(n.value)
        }
        if found != {VERDICT_PASS, VERDICT_FAIL, VERDICT_INCONCLUSIVE}:
            problems.append(f"unexpected formal-verdict strings in code: {sorted(found)}")
    except Exception as exc:
        problems.append(f"verdict-literal check failed: {exc}")

    # 10. The lineage-aware projector is exercised exactly where preregistered:
    #     derive_airlock_memory_with_lineage is called ONLY from the single
    #     choke point project_lineage_memories(); every standing projection
    #     goes through it.
    try:
        tree = ast.parse(source)

        class CallTracker(ast.NodeVisitor):
            def __init__(self):
                self.stack: list[ast.AST] = []
                self.lineage_calls: set[str] = set()

            def generic_visit(self, node):
                self.stack.append(node)
                super().generic_visit(node)
                self.stack.pop()

            def visit_Call(self, node):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if name == "derive_airlock_memory_with_lineage":
                    enclosing = next(
                        (n for n in reversed(self.stack) if isinstance(n, ast.FunctionDef)),
                        None,
                    )
                    self.lineage_calls.add(enclosing.name if enclosing else "<module>")
                self.generic_visit(node)

        ct = CallTracker()
        ct.visit(tree)
        if ct.lineage_calls != {"project_lineage_memories"}:
            problems.append(
                "derive_airlock_memory_with_lineage called outside the "
                f"project_lineage_memories choke point: {sorted(ct.lineage_calls)}"
            )
    except Exception as exc:
        problems.append(f"projector-use check failed: {exc}")

    # 11. Fixture builds and the shims behave as preregistered (dry runs only:
    #     shims execute directly, never through Nightshift selection).
    try:
        tmp = Path(tempfile.mkdtemp(prefix="airlock-rsi-004-selfcheck-"))
        try:
            state = build_fixture(tmp)
            repo = Path(state["repo"])
            for rel in ("src/value.py", "src/policy.py", "tests/check.py",
                        ".airlock/objective.json", ".airlock/config.json", ".gitignore"):
                if not (repo / rel).exists():
                    problems.append(f"fixture missing {rel}")
            if (repo / "src" / "policy.py").read_text() != POLICY_V1:
                problems.append("fixture policy is not the preregistered STEP=1 base")
            for ref in (RU, R1, R2, R3):
                if sh("git", "rev-parse", ref, cwd=repo) != state["base_commit"]:
                    problems.append(f"{ref} not at fixture base after build")

            hermes = Path(state["hermes_executable"])
            agent_report = tmp / "agent-report.json"
            shim_env = dict(os.environ)
            shim_env["AIRLOCK_RELEASE_AUTHORITY"] = "ABSENT"
            shim_env["OPENROUTER_API_KEY"] = "rsi-fixture-secret"
            shim_env["AIRLOCK_AGENT_REPORT"] = str(agent_report)

            def dry_run(code: str, base_policy: str, base_value: str, label: str) -> Path:
                work = tmp / f"dry-{label}"
                shutil.copytree(repo / "src", work / "src")
                (work / "src" / "policy.py").write_text(base_policy, encoding="utf-8")
                (work / "src" / "value.py").write_text(base_value, encoding="utf-8")
                exe = tmp / f"hermes-dry-{label}"
                exe.write_text(code, encoding="utf-8")
                exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
                cp = subprocess.run([str(exe), "-z", "prompt"], cwd=str(work),
                                    env=shim_env, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if cp.returncode != 0:
                    problems.append(f"{label} shim dry run failed: {cp.stderr.strip()}")
                return work

            work = dry_run(ROOTU_SHIM, POLICY_V1, "VALUE = 0\n", "rootU")
            if (work / "src" / "policy.py").read_text() != POLICY_VU:
                problems.append("rootU shim did not install the unrelated bonus policy")
            if (work / "src" / "value.py").read_text() != "VALUE = 2\n":
                problems.append("rootU shim did not apply its policy (VALUE=2)")

            work = dry_run(GEN1_SHIM, POLICY_V1, "VALUE = 0\n", "gen1")
            if (work / "src" / "policy.py").read_text() != POLICY_V2:
                problems.append("gen1 shim did not install the STEP=2 policy")
            if (work / "src" / "value.py").read_text() != "VALUE = 2\n":
                problems.append("gen1 shim did not apply the policy (VALUE=2)")

            for label, base_value, expected in (("gen2", 2, 4), ("gen3", 4, 6)):
                parent_policy = POLICY_V2
                pristine = tmp / f"pristine-dry-{label}"
                if pristine.exists():
                    shutil.rmtree(pristine)
                (pristine / "src").mkdir(parents=True)
                (pristine / "src" / "policy.py").write_text(parent_policy, encoding="utf-8")
                code = inheriting_shim_code(
                    hashlib.sha256(parent_policy.encode()).hexdigest(), str(pristine),
                    base_value, label,
                )
                work = dry_run(code, parent_policy, f"VALUE = {base_value}\n", label)
                if (work / "src" / "value.py").read_text() != f"VALUE = {expected}\n":
                    problems.append(f"{label} shim did not apply the installed policy (VALUE={expected})")
                if (work / "src" / "policy.py").read_text() != parent_policy:
                    problems.append(f"{label} shim rewrote the installed policy (forbidden)")

            test_key = b"rsi-004-selfcheck-key"
            rec = sign({"hello": "world"}, test_key)
            if not verify_signature(rec, test_key) or verify_signature(rec, b"wrong"):
                problems.append("sign/verify round trip broken")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    except Exception as exc:
        problems.append(f"fixture/shim self-check failed: {exc}")

    # 12. The preregistration is frozen before primary contact: it is no
    #     longer PROPOSED, it records the superseded pre-run draft hash, and
    #     its SHA-256 binding matches the file bytes.
    try:
        prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
        decided = prereg.get("decided", "")
        if decided.startswith("PROPOSED"):
            problems.append("preregistration still PROPOSED; it must be frozen before primary contact")
        if "5750248e5236c506270fd5506bd695f62468dbc3114305cc2284e40d7a544d9c" not in decided:
            problems.append("preregistration does not record the superseded pre-run draft hash")
        if sha256_file(PREREG_PATH) != PREREG_SHA256:
            problems.append("preregistration SHA-256 binding does not match the file bytes")
    except Exception as exc:
        problems.append(f"preregistration frozen-state check failed: {exc}")

    # 13. Selection verification uses the generation's ACTUAL base commit from
    #     its signed generation record, never the fixture base: the stale
    #     pattern diffing every generation from state["base_commit"] counted
    #     inherited parent changes as child candidate changes.
    try:
        verify_source = inspect.getsource(_verify_selection_common)
        if 'state["base_commit"]}..{selected}' in verify_source or \
           "state['base_commit']}..{selected}" in verify_source or \
           'f"{state["base_commit"]}..{selected}"' in verify_source:
            problems.append(
                "_verify_selection_common still diffs from state[\"base_commit\"] "
                "(the gen2/gen3 inherited-change bug)"
            )
        if "actual_generation_base(" not in verify_source:
            problems.append(
                "_verify_selection_common does not derive the diff base via actual_generation_base"
            )
        if '"base_commit":gen_base' not in verify_source.replace(" ", ""):
            problems.append(
                "the recorded selection base_commit is not the generation's actual base"
            )
    except Exception as exc:
        problems.append(f"generation-base check failed: {exc}")

    return problems


PHASES = (
    "select-rootU", "install-rootU",
    "select-gen1", "install-gen1",
    "select-gen2", "install-gen2",
    "select-gen3", "install-gen3",
    "mint-lineage", "checkpoint", "reopen", "reproject",
)


def orchestrate(output: Path | None) -> dict:
    problems = self_check()
    if problems:
        raise SystemExit(
            "RSI-004 self-check FAILED - stopping before execution:\n"
            + "\n".join(f"  - {p}" for p in problems)
        )
    root = Path(tempfile.mkdtemp(prefix="airlock-rsi-004-"))
    script = Path(__file__).resolve()
    state_dir: Path | None = None
    try:
        state = build_fixture(root)
        state_path = root / "state.json"
        state_dir = Path(state["state_dir"])
        env = _phase_env(state)

        # Anti-rescue marker: written immediately before the first Nightshift
        # contact. From here on, the primary is in motion.
        PRIMARY_CONTACT_MARKER.write_text(
            "RSI-004 primary Nightshift contact began; anti-rescue in effect\n",
            encoding="utf-8",
        )

        for phase in (
            "select-rootU", "install-rootU",
            "select-gen1", "install-gen1",
            "select-gen2", "install-gen2",
            "select-gen3", "install-gen3",
            "mint-lineage", "checkpoint",
        ):
            run_phase(script, phase, state_path, env)

        # Controlled support loss for gen1's promotion evidence, then REOPEN.
        (state_dir / "gen1_support.witness").unlink()
        run_phase(script, "reopen", state_path, env)

        result = read_json(state_dir / "result.json")
        pids = [
            read_json(state_dir / f"{p}_selection.json")["process_pid"]
            for p in ("rootU", "gen1", "gen2", "gen3")
        ] + [
            read_json(state_dir / f"{p}_installation.json")["process_pid"]
            for p in ("rootU", "gen1", "gen2", "gen3")
        ] + [
            read_json(state_dir / "checkpoint.json")["process_pid"],
            read_json(state_dir / "reopen.json")["process_pid"],
            result["restart_evidence"]["reproject_phase_pid"],
        ]
        if len(set(pids)) != len(pids):
            raise AssertionError("phases did not execute across independent processes")
        if output is not None:
            write_json(output, result)
        return result
    except PreconditionFailure as exc:
        result = inconclusive_result(str(exc), state_dir)
        if output is not None:
            write_json(output, result)
        return result
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        description="RSI-004 lineage-aware inheritance (default: self-check only; primary gated)"
    )
    parser.add_argument("--phase", choices=PHASES)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-check", action="store_true",
                        help="verify prereg bindings and stop (no execution)")
    parser.add_argument(
        EXECUTE_PRIMARY_FLAG, action="store_true",
        help="FUTURE GATE: encode the primary sequence for a later authorized run. "
             "Do not pass without explicit authorization.",
    )
    args = parser.parse_args(raw)

    if args.phase and not args.execute_primary:
        parser.error("phase execution requires --execute-primary (explicit primary gate)")

    if args.self_check or (not args.execute_primary and not args.phase):
        problems = self_check()
        if problems:
            print("RSI-004 self-check FAILED:")
            for p in problems:
                print(f"  - {p}")
            return 1
        print(
            "RSI-004 self-check clean: 16 prereg bindings unambiguous, pins verified, "
            "gates closed. Primary NOT executed (pass --execute-primary only when authorized)."
        )
        return 0

    if args.phase:
        if args.state is None:
            parser.error("--state is required with --phase")
        try:
            {
                "select-rootU": phase_select_rootU,
                "install-rootU": phase_install_rootU,
                "select-gen1": phase_select_gen1,
                "install-gen1": phase_install_gen1,
                "select-gen2": phase_select_gen2,
                "install-gen2": phase_install_gen2,
                "select-gen3": phase_select_gen3,
                "install-gen3": phase_install_gen3,
                "mint-lineage": phase_mint_lineage,
                "checkpoint": phase_checkpoint,
                "reopen": phase_reopen,
                "reproject": phase_reproject,
            }[args.phase](args.state)
        except PreconditionFailure as exc:
            # Surface precondition failures distinctly so the orchestrator can
            # map them to INCONCLUSIVE rather than a harness crash.
            print(f"RSI-004 precondition failure in {args.phase}: {exc}", file=sys.stderr)
            return 42
        return 0

    try:
        result = orchestrate(args.output)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"RSI-004 harness error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
