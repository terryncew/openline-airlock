"""RSI-005 scientific runner: lineage-aware inheritance (scientific stage).

Scientific question: when required ancestral evidence loses standing, does
the receiver prevent further inheritance through that dependency?

HARD STRUCTURE (frozen before primary contact):
- This file NEVER implements the harness bootstrap. It imports and reuses
  the QUALIFIED harness primitives from run_rsi_005.py (build_fixture,
  write_phase_token, _phase_env, nightshift_entry, ...). It fails closed
  unless run_rsi_005.py hashes exactly to QUALIFIED_HARNESS_SHA256, and it
  never modifies run_rsi_005.py, RSI-004, RSI-003, or Verified Memory.
- The ONLY Nightshift path is the qualified harness's nightshift_entry().
  This file contains no run_nightshift call and never writes the
  primary-contact marker; the marker is created only by nightshift_entry()
  immediately before run_nightshift is entered.
- Default invocation is non-executing (self-check only). --execute-primary
  is a future gate that CI, tests, and this build must never pass.

Predecessor: RSI-004 is permanently sealed (harness crash, no verdict;
runner 1195b9f0..., prereg 8e9ceb9b...). This experiment is the only
legitimate route back to the lineage question.

Claim boundary: single-required-parent lineage only; receiver-owned signed
lineage evidence; transitive required-dependency propagation; unrelated
accepted sibling branch (rootU) must remain usable; restart/reprojection
from persisted evidence; historical receipts and installed state are never
rewritten; gen4 is probe-only and never executed. No claim of arbitrary
multi-parent DAG support, open-ended recursion, live productivity
advantage, or isolation from distinct PIDs.

Anti-rescue: begins when the scientific execution first enters
nightshift_entry() and the RSI-005 primary-contact marker is written
immediately before run_nightshift. No rerun once the future one-run
authorization is consumed.
"""

import argparse
import ast
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_rsi_005 as h
from run_rsi_005 import sh, sha256_file, write_json, read_json
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
        "RSI-005 requires openline-verified-memory pinned to "
        "36e3d0e0dab6a121abc1c14accbaa7310b5c2186: " + str(exc)
    )

PREREG_PATH = Path(__file__).with_name("RSI_005_PREREGISTRATION.json")
# Frozen SHA-256 of the scientific preregistration file bytes. Filled when the
# preregistration is frozen; self-check fails closed on any drift.
PREREG_SHA256 = "256b41d726f5f8597b4e23ed2169f10974a034d9433f5fd0d5ba861ead8f2ac5"

# Frozen bindings (DECIDED - FROZEN BEFORE PRIMARY CONTACT).
AIRLOCK_BASE_MAIN = "5e319f069c247138ff17186674829e99feba1d9c"
QUALIFIED_HARNESS_SHA256 = "1fa894bd623eb4aacc39645ad546c0d31889dec391b1a65d65a27842937665e3"
QUALIFIED_HARNESS_COMMIT = "ffd1030b884664db37fe4d8ff66a58c06fbf5060"
VERIFIED_MEMORY_COMMIT = "36e3d0e0dab6a121abc1c14accbaa7310b5c2186"
EVIDENCE_PY_SHA256 = "ba02bc78c999120b31ea68fcb4f4fd2d12967c705e380204d0ee093b1d874ec9"
PREDECESSOR_RUNNER_SHA256 = "1195b9f0d54a6bdc93b982ac56778e9ee69f21f51a73333eb3c718a0ec951de2"
PREDECESSOR_PREREG_SHA256 = "8e9ceb9bc928c710920893a79fa99661f93d2456bc3acf1586a8175eb51ca8fd"

VERDICT_PASS = "PASS_RSI_005_LINEAGE_AWARE_INHERITANCE"
VERDICT_FAIL = "FAIL_RSI_005_REQUIRED_ANCESTRY_NOT_ENFORCED"
VERDICT_INCONCLUSIVE = "INCONCLUSIVE_RSI_005_PRECONDITION_FAILURE"
VERDICTS = (VERDICT_PASS, VERDICT_FAIL, VERDICT_INCONCLUSIVE)
# Diagnostics travel only through cause_code. Scientific FAIL is reserved for
# an otherwise valid experiment where lineage semantics fail; harness and
# integrity failures are INCONCLUSIVE with their precise cause code.
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

RU = "refs/heads/rsi-005/installed-rootU"
R1 = "refs/heads/rsi-005/installed-gen1"
R2 = "refs/heads/rsi-005/installed-gen2"
R3 = "refs/heads/rsi-005/installed-gen3"
RU_BRANCH = "rsi-005/installed-rootU"
R1_BRANCH = "rsi-005/installed-gen1"
R2_BRANCH = "rsi-005/installed-gen2"
R3_BRANCH = "rsi-005/installed-gen3"
WORK_BRANCHES = {
    "rootU": "rsi-005/rootU-work",
    "gen1": "rsi-005/gen1-work",
    "gen2": "rsi-005/gen2-work",
    "gen3": "rsi-005/gen3-work",
}
INSTALL_REFS = {"rootU": RU, "gen1": R1, "gen2": R2, "gen3": R3}

ROOTU_LESSON = {
    "lesson_id": "rsi-005-rootU-unrelated-policy",
    "title": "rootU earned an unrelated generator policy improvement",
    "text": (
        "An independent Nightshift selection improved the generator policy on an "
        "unrelated axis (bonus term, not the STEP lineage) and earned inheritance "
        "through exact receiver-observed installation at the rootU ref. Its "
        "lineage record is an explicit receiver-signed ROOT declaration."
    ),
}
GEN1_LESSON = {
    "lesson_id": "rsi-005-gen1-earned-policy",
    "title": "Gen1 earned an improved generator policy through exact installation",
    "text": (
        "A unique Nightshift selection improved the generator policy "
        "(src/policy.py STEP 1 -> 2) and applied it once, earning inheritance "
        "through exact receiver-observed installation at the gen1 ref. Its "
        "lineage record is an explicit receiver-signed ROOT declaration."
    ),
}
GEN2_LESSON = {
    "lesson_id": "rsi-005-gen2-inherited-policy",
    "title": "Gen2 inherited by running under gen1's installed policy",
    "text": (
        "Gen2's generator was bound to the exact installed gen1 policy bytes; "
        "its own selection earned inheritance through exact receiver-observed "
        "installation at the gen2 ref. Its lineage record is a receiver-signed "
        "REQUIRED declaration naming gen1 as its single required parent."
    ),
}
GEN3_LESSON = {
    "lesson_id": "rsi-005-gen3-inherited-policy",
    "title": "Gen3 inherited by running under gen2's installed policy",
    "text": (
        "Gen3's generator was bound to the exact installed gen2 policy bytes; "
        "its own selection earned inheritance through exact receiver-observed "
        "installation at the gen3 ref. Its lineage record is a receiver-signed "
        "REQUIRED declaration naming gen2 as its single required parent."
    ),
}
LESSONS = {"rootU": ROOTU_LESSON, "gen1": GEN1_LESSON, "gen2": GEN2_LESSON, "gen3": GEN3_LESSON}
GEN4_LESSON_ID = "rsi-005-gen4-admission-probe"

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
    "model": "fake-hermes-rsi-005-rootU",
}))
print("rsi-005 rootU candidate written")
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
    "model": "fake-hermes-rsi-005-gen1",
}))
print("rsi-005 gen1 candidate written")
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
    "model": "fake-hermes-rsi-005-%s",
}))
print("rsi-005 %s candidate written")
""" % (policy_sha256, pristine_path, base_value, gen, gen)

class PreconditionFailure(Exception):
    """A preregistered precondition was not met: the propagation question
    could not be put to the mechanism. Maps to INCONCLUSIVE, not a crash.

    Every raise site carries an EXPLICIT cause_code from the preregistered
    CAUSE_CODES set. Classification is never inferred from message
    substrings: the code is passed at the raise site, preserved through the
    child phase -> orchestrator -> terminal result chain, and read directly
    off the exception by inconclusive_result(). Scientific FAIL remains only
    FAIL_RSI_005_REQUIRED_ANCESTRY_NOT_ENFORCED for an otherwise valid
    experiment where lineage semantics fail."""

    def __init__(self, message: str, cause_code: str):
        if cause_code not in CAUSE_CODES:
            raise ValueError(f"unknown RSI-005 cause code: {cause_code!r}")
        super().__init__(message)
        self.cause_code = cause_code

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
                raise PreconditionFailure(f"REQUIRED lineage missing {name}", "LINEAGE_BINDING_FAILURE")
        payload["declaration"] = "REQUIRED"
        payload["parent_lesson_id"] = parent_lesson_id
        payload["parent_promotion_receipt_sha256"] = parent_promotion_receipt_sha256
        payload["parent_selected_commit"] = parent_selected_commit
        payload["parent_installed_policy_sha256"] = parent_installed_policy_sha256
    record = sign(payload, key)
    if not verify_hmac_record(record, key):
        raise PreconditionFailure("minted lineage record failed to verify", "LINEAGE_BINDING_FAILURE")
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
            raise PreconditionFailure(f"{prefix}: lineage record missing from disk", "LINEAGE_BINDING_FAILURE")
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
    caller of derive_airlock_memory_with_lineage in run_rsi_005_scientific.py (enforced
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
        "run_id": "rsi-005-gen4-probe",
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
        "run_id": "rsi-005-gen4-probe",
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
    receipts_byte_identical: bool,
    deterministic: bool,
    gen1_questioned: bool,
    standings: dict[str, str],
    gen4_probe: str,
) -> tuple[str, str]:
    """Map the frozen verdict precedence to exactly one formal verdict plus
    one cause code. Only the three formal verdicts are ever emitted;
    every diagnostic travels through cause_code.

    Decided scientific boundary: the scientific FAIL is reserved for an
    otherwise valid experiment where lineage semantics fail. Integrity and
    harness failures do not become the scientific FAIL; they are
    INCONCLUSIVE with their own cause codes, because the propagation
    question was not validly put to the mechanism."""
    if not pre_reopen_ok:
        return (VERDICT_INCONCLUSIVE, "CHECKPOINT_NOT_ESTABLISHED")
    if not lineage_ok:
        return (VERDICT_INCONCLUSIVE, "LINEAGE_BINDING_FAILURE")
    if not refs_unchanged:
        return (VERDICT_INCONCLUSIVE, "INSTALLED_REF_MUTATION")
    if not receipts_byte_identical:
        return (VERDICT_INCONCLUSIVE, "RECEIPT_MUTATION")
    if not deterministic:
        return (VERDICT_INCONCLUSIVE, "PROJECTION_NONDETERMINISM")
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
    # A post-projection combination matching neither the decided PASS
    # conditions nor the decided scientific-FAIL conditions: the pattern is
    # uninterpretable, so no scientific claim is made. REQUIRED_ANCESTRY_NOT_ENFORCED
    # is the nearest cause code; the verdict stays INCONCLUSIVE.
    return (VERDICT_INCONCLUSIVE, "REQUIRED_ANCESTRY_NOT_ENFORCED")

RECEIPT_REQUIRED_TOP_KEYS = (
    "schema",
    "experiment",
    "verdict",
    "cause_code",
    "airlock_base_sha",
    "qualified_harness_sha256",
    "qualified_harness_source_commit",
    "scientific_runner_normalized_sha256",
    "scientific_runner_file_sha256",
    "verified_memory_sha",
    "verified_memory_evidence_py_sha256",
    "preregistration_sha256",
    "execution_head_sha",
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
    "historical_receipt_file_hashes",
    "installed_ref_hashes",
    "installed_policy_hashes",
    "installed_refs_unchanged",
    "reprojection_deterministic",
    "lineage_record_set_sha256_checkpoint",
    "lineage_record_set_sha256_reprojection",
    "phase_process_pids",
    "phase_pids_distinct",
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
    if receipt.get("schema") != "airlock.rsi-005.result.v1":
        problems.append("receipt schema mismatch")
    if receipt.get("verdict") not in VERDICTS:
        problems.append("receipt verdict is not one of the three formal verdicts")
    if receipt.get("cause_code") not in CAUSE_CODES:
        problems.append("receipt cause_code not in the preregistered set")
    # Complete scientific-package bindings (fix: the receipt must name
    # exactly which harness, runner, preregistration, and Git HEAD produced
    # it; static values are checked for equality, runtime values for shape).
    if receipt.get("qualified_harness_sha256") != QUALIFIED_HARNESS_SHA256:
        problems.append("receipt qualified_harness_sha256 does not match the qualified harness")
    if receipt.get("qualified_harness_source_commit") != QUALIFIED_HARNESS_COMMIT:
        problems.append("receipt qualified_harness_source_commit does not match the qualified harness source commit")
    if receipt.get("scientific_runner_normalized_sha256") != normalized_runner_sha256():
        problems.append("receipt scientific_runner_normalized_sha256 does not match the canonicalized runner hash")
    # The receipt's normalized runner hash must ALSO equal the normalized
    # runner hash frozen in the preregistration. This closes the case where
    # the runner changes after preregistration while PREREG_SHA256 and the
    # prereg file remain unchanged.
    bound_runner = _prereg_bound_runner_sha256()
    if not re.fullmatch(r"[0-9a-f]{64}", bound_runner):
        problems.append("prereg-bound scientific_runner_sha256 is missing or malformed")
    elif receipt.get("scientific_runner_normalized_sha256") != bound_runner:
        problems.append("receipt scientific_runner_normalized_sha256 does not match the prereg-bound runner hash")
    if receipt.get("preregistration_sha256") != sha256_file(PREREG_PATH):
        problems.append("receipt preregistration_sha256 does not match the frozen preregistration file")
    for k in ("scientific_runner_file_sha256",):
        v = receipt.get(k)
        if not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v):
            problems.append(f"receipt {k} is not a 64-char lowercase hex SHA-256")
    head = receipt.get("execution_head_sha")
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
        problems.append(
            "receipt execution_head_sha must be an exact 40-char lowercase "
            "Git SHA (never UNKNOWN, empty, or malformed)"
        )
    if receipt.get("verified_memory_sha") != VERIFIED_MEMORY_COMMIT:
        problems.append("receipt verified_memory_sha does not match the pinned Verified Memory commit")
    if receipt.get("verified_memory_evidence_py_sha256") != EVIDENCE_PY_SHA256:
        problems.append("receipt verified_memory_evidence_py_sha256 does not match the pinned evidence.py hash")
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

def _accept_one(report: dict[str, Any], prefix: str) -> dict[str, Any]:
    if report.get("accepted_generations") != 1 or report.get("status") != "COMPLETED_LIMIT":
        raise PreconditionFailure(
            f"{prefix} Nightshift did not select exactly one winner: {report.get('status')}",
            "CHECKPOINT_NOT_ESTABLISHED")
    if len(report.get("generations", [])) != 1:
        raise PreconditionFailure(f"{prefix}: expected exactly one generation", "CHECKPOINT_NOT_ESTABLISHED")
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
            raise PreconditionFailure(f"{prefix}: no parent commit to bind the generation base", "CHECKPOINT_NOT_ESTABLISHED")
        expected = parent_commit
    observed = generation.get("payload", {}).get("base_commit") or generation.get("base_commit")
    if observed != expected:
        raise PreconditionFailure(
            f"{prefix}: signed generation base {observed!r} != expected base {expected!r}",
            "CHECKPOINT_NOT_ESTABLISHED")
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
        raise PreconditionFailure(f"{prefix} Nightshift generation signature did not verify", "CHECKPOINT_NOT_ESTABLISHED")

    candidate = derive_airlock_memory(
        lesson_id=lesson["lesson_id"],
        title=lesson["title"],
        text=lesson["text"],
        generation_record=generation,
        key=key,
    )
    if candidate.status != "candidate" or candidate.survived != 0:
        raise PreconditionFailure(f"{prefix} selection alone incorrectly earned inheritance", "CHECKPOINT_NOT_ESTABLISHED")

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
        raise PreconditionFailure(f"{prefix} candidate escaped ordinary code: {candidate_paths_list}", "CHECKPOINT_NOT_ESTABLISHED")

    if sha256_file(hermes) != shim_before:
        raise PreconditionFailure(f"Hermes shim changed during {prefix} candidate generation", "CHECKPOINT_NOT_ESTABLISHED")
    lineage = report.get("run_context", {}).get("harness_lineage", [])
    if not lineage or any(row.get("changed") for row in lineage):
        raise PreconditionFailure(f"Hermes harness changed during {prefix}", "CHECKPOINT_NOT_ESTABLISHED")

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
        raise PreconditionFailure(f"{prefix} work branch is not clean at base", "CHECKPOINT_NOT_ESTABLISHED")
    branch = {"rootU": RU_BRANCH, "gen1": R1_BRANCH, "gen2": R2_BRANCH, "gen3": R3_BRANCH}[prefix]
    sh("git", "branch", "-f", branch, base_commit, cwd=repo)
    before = sh("git", "rev-parse", ref, cwd=repo)
    if before != base_commit:
        raise PreconditionFailure(f"{prefix} install ref was not created at its base", "CHECKPOINT_NOT_ESTABLISHED")
    return before

def _write_shim(hermes: Path, code: str) -> str:
    hermes.write_text(code, encoding="utf-8")
    return sha256_file(hermes)

FRESH_PROCESS_PHASES = (
    "select-rootU", "install-rootU",
    "select-gen1", "install-gen1",
    "select-gen2", "install-gen2",
    "select-gen3", "install-gen3",
    "mint-lineage", "checkpoint", "reopen", "reproject",
)

def record_phase_pid(state_dir: Path, phase: str) -> None:
    """Bind this phase's process PID into the shared phase-PID map."""
    path = state_dir / "phase_pids.json"
    pids = read_json(path) if path.exists() else {}
    pids[phase] = os.getpid()
    write_json(path, pids)

def require_distinct_phase_pids(state_dir: Path) -> dict[str, int]:
    """Require every intended fresh-process phase to have recorded its own
    distinct process PID. The map is bound in the final receipt."""
    path = state_dir / "phase_pids.json"
    pids = read_json(path) if path.exists() else {}
    if set(pids) != set(FRESH_PROCESS_PHASES):
        raise PreconditionFailure(
            f"phase-PID map incomplete: have {sorted(pids)}, need {sorted(FRESH_PROCESS_PHASES)}",
            "CHECKPOINT_NOT_ESTABLISHED")
    if len(set(pids.values())) != len(FRESH_PROCESS_PHASES):
        raise PreconditionFailure("phase processes are not all distinct", "CHECKPOINT_NOT_ESTABLISHED")
    return pids

def phase_select_rootU(state_path: Path) -> None:
    state = read_json(state_path)
    repo = Path(state["repo"])
    state_dir = Path(state["state_dir"])
    record_phase_pid(state_dir, "select-rootU")
    state_dir.mkdir(parents=True, exist_ok=True)
    hermes = Path(state["hermes_executable"])
    shim_before = sha256_file(hermes)  # ROOTU_SHIM written by orchestrate
    _prepare_work_branch(repo, "rootU", state["base_commit"], RU)
    # RSI-005 contact boundary: the ONLY Nightshift path is the qualified
    # harness's nightshift_entry(), which writes the primary-contact marker
    # immediately before run_nightshift is entered. No other call path exists
    # in this runner.
    report = h.nightshift_entry(
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
            f"rootU candidate must install its unrelated policy and apply it: {result['candidate_paths']}",
            "CHECKPOINT_NOT_ESTABLISHED")
    result["install_ref"] = RU
    write_json(state_dir / "rootU_selection.json", result)

def phase_select_gen1(state_path: Path) -> None:
    state = read_json(state_path)
    repo = Path(state["repo"])
    state_dir = Path(state["state_dir"])
    record_phase_pid(state_dir, "select-gen1")
    hermes = Path(state["hermes_executable"])
    shim_before = _write_shim(hermes, GEN1_SHIM)
    _prepare_work_branch(repo, "gen1", state["base_commit"], R1)
    # RSI-005 contact boundary: the ONLY Nightshift path is the qualified
    # harness's nightshift_entry(), which writes the primary-contact marker
    # immediately before run_nightshift is entered. No other call path exists
    # in this runner.
    report = h.nightshift_entry(
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
            f"gen1 candidate must improve the generator policy and apply it: {result['candidate_paths']}",
            "CHECKPOINT_NOT_ESTABLISHED")
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
        raise PreconditionFailure(f"{parent_ref} moved before {prefix} selection", "INSTALLED_REF_MUTATION")

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
        raise PreconditionFailure(f"pristine {parent_prefix} policy != committed policy bytes", "INSTALLED_REF_MUTATION")
    ns: dict[str, Any] = {}
    exec((pristine / "src" / "value.py").read_text(encoding="utf-8"), ns)
    if ns.get("VALUE") != expected_base_value:
        raise PreconditionFailure(
            f"{prefix} base VALUE is {ns.get('VALUE')!r}, expected {expected_base_value}",
            "CHECKPOINT_NOT_ESTABLISHED")

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
    record_phase_pid(state_dir, "select-gen2")
    hermes = Path(state["hermes_executable"])
    shim_before, binding = _bind_child_generator(
        prefix="gen2", parent_prefix="gen1", state=state, repo=repo,
        state_dir=state_dir, expected_base_value=2, child_gen="gen2",
    )
    # RSI-005 contact boundary: the ONLY Nightshift path is the qualified
    # harness's nightshift_entry(), which writes the primary-contact marker
    # immediately before run_nightshift is entered. No other call path exists
    # in this runner.
    report = h.nightshift_entry(
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
            f"gen2 candidate must run under the installed policy, not rewrite it: {result['candidate_paths']}",
            "CHECKPOINT_NOT_ESTABLISHED")
    policy_after = hashlib.sha256(policy_bytes_at(repo, binding["parent_commit"])).hexdigest()
    if policy_after != binding["installed_policy_sha256"]:
        raise PreconditionFailure("installed gen1 policy bytes changed during gen2's run", "INSTALLED_REF_MUTATION")
    result["install_ref"] = R2
    result["generator_binding"] = binding
    write_json(state_dir / "gen2_selection.json", result)

def phase_select_gen3(state_path: Path) -> None:
    state = read_json(state_path)
    repo = Path(state["repo"])
    state_dir = Path(state["state_dir"])
    record_phase_pid(state_dir, "select-gen3")
    hermes = Path(state["hermes_executable"])
    shim_before, binding = _bind_child_generator(
        prefix="gen3", parent_prefix="gen2", state=state, repo=repo,
        state_dir=state_dir, expected_base_value=4, child_gen="gen3",
    )
    # RSI-005 contact boundary: the ONLY Nightshift path is the qualified
    # harness's nightshift_entry(), which writes the primary-contact marker
    # immediately before run_nightshift is entered. No other call path exists
    # in this runner.
    report = h.nightshift_entry(
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
            f"gen3 candidate must run under the installed policy, not rewrite it: {result['candidate_paths']}",
            "CHECKPOINT_NOT_ESTABLISHED")
    policy_after = hashlib.sha256(policy_bytes_at(repo, binding["parent_commit"])).hexdigest()
    if policy_after != binding["installed_policy_sha256"]:
        raise PreconditionFailure("installed gen2 policy bytes changed during gen3's run", "INSTALLED_REF_MUTATION")
    result["install_ref"] = R3
    result["generator_binding"] = binding
    write_json(state_dir / "gen3_selection.json", result)

def _install(*, prefix: str, state_path: Path, retain: bool = False) -> None:
    state = read_json(state_path)
    repo = Path(state["repo"])
    state_dir = Path(state["state_dir"])
    record_phase_pid(state_dir, f"install-{prefix}")
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
        raise PreconditionFailure(f"{prefix} restart did not reconstruct candidate standing", "CHECKPOINT_NOT_ESTABLISHED")
    selected = recovered.selected_commit
    before = sh("git", "rev-parse", ref, cwd=repo)
    if before != sel["base_commit"]:
        raise PreconditionFailure(f"{prefix} installation ref was not at its base on restart", "INSTALLED_REF_MUTATION")

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
        raise PreconditionFailure(f"{prefix} wrong-commit promotion unexpectedly earned inheritance", "CHECKPOINT_NOT_ESTABLISHED")

    sh("git", "branch", "-f", branch, selected, cwd=repo)
    observed = sh("git", "rev-parse", ref, cwd=repo)
    if observed != selected:
        raise PreconditionFailure(f"{prefix} receiver did not observe exact selected commit", "CHECKPOINT_NOT_ESTABLISHED")

    support = state_dir / f"{prefix}_support.witness"
    support.write_text(f"RSI-005 {prefix} receiver support live\n", encoding="utf-8")
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
        raise PreconditionFailure(f"{prefix} exact installation failed to earn inherited standing", "CHECKPOINT_NOT_ESTABLISHED")

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
    record_phase_pid(state_dir, "mint-lineage")
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
            raise PreconditionFailure(f"{prefix} lineage record failed to verify after minting", "LINEAGE_BINDING_FAILURE")

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
    """CANONICAL signed-record identities (generation / promotion /
    standing / lineage). The lineage entry is signed_record_sha256 over
    the PARSED signed lineage record, NOT the raw file bytes: whitespace-only
    reformatting of the lineage file does not change this digest. The
    literal file-byte identities live separately in raw_receipt_file_hashes()."""
    out: dict[str, dict[str, str | None]] = {}
    for prefix, b in bundles.items():
        sel = b["selection"]
        inst = b["installation"]
        out[prefix] = {
            "generation": sel["generation_record_sha256"],
            "promotion": inst["promotion_record_sha256"],
            "lineage": signed_record_sha256(b["lineage"]) if b["lineage"] else None,
            "standing": inst.get("standing_record_sha256"),
        }
    return out

def raw_receipt_file_hashes(state_dir: Path, bundles: dict[str, dict[str, Any]]) -> dict[str, dict[str, str | None]]:
    """RAW sha256 over the exact receipt files on disk (literal file bytes)
    for every historical receipt class: generation receipt, promotion
    receipt, pre-existing standing receipt, lineage receipt. Unlike the
    canonical signed-record hashes, any whitespace or reformatting change to
    a file changes these digests. The new REOPEN(gen1) standing record is
    new evidence and is bound separately in reopen_evidence; it is not part
    of the historical set."""
    out: dict[str, dict[str, str | None]] = {}
    for prefix, b in bundles.items():
        sel = b["selection"]
        inst = b["installation"]
        paths = {
            "generation": Path(sel["generation_record"]),
            "promotion": Path(inst["promotion_record"]),
            "standing": Path(inst["standing_record"]) if inst.get("standing_record") else None,
            "lineage": state_dir / f"{prefix}_lineage.json",
        }
        out[prefix] = {
            k: (sha256_file(p) if p is not None and p.exists() else None)
            for k, p in paths.items()
        }
    return out

def historical_files_unchanged(pre: dict[str, Any], post: dict[str, Any]) -> bool:
    """Literal byte-identity of every historical receipt file: the full
    path->raw-sha256 map must be byte-identical."""
    return pre == post

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
    record_phase_pid(state_dir, "checkpoint")
    key = (repo / ".airlock" / "verification.key").read_bytes()
    bundles = {p: load_bundle(state_dir, p) for p in ("rootU", "gen1", "gen2", "gen3")}

    try:
        projection = project_bundles(bundles, repo, key)
    except EvidenceError as exc:
        raise PreconditionFailure(f"pre-REOPEN lineage projection failed: {exc}", "LINEAGE_BINDING_FAILURE") from exc

    standings = {b["lesson"]["lesson_id"]: projection[b["lesson"]["lesson_id"]].status for b in bundles.values()}
    lesson_ids = {b["lesson"]["lesson_id"] for b in bundles.values()}
    if any(s != "inherited" for s in standings.values()):
        raise PreconditionFailure(f"pre-REOPEN standings not all inherited: {standings}", "CHECKPOINT_NOT_ESTABLISHED")
    established_ids = {m.lesson_id for m in established(list(projection.values()))}
    if established_ids != lesson_ids:
        raise PreconditionFailure(f"pre-REOPEN established set wrong: {sorted(established_ids)}", "CHECKPOINT_NOT_ESTABLISHED")

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
        raise PreconditionFailure("lineage record set changed between minting and checkpoint", "LINEAGE_BINDING_FAILURE")
    checkpoint = {
        "phase": "checkpoint",
        "process_pid": os.getpid(),
        "pre_reopen_standings": standings,
        "pre_reopen_established": sorted(established_ids),
        "historical_receipt_hashes": _receipt_hashes(state_dir, bundles),
        "historical_receipt_file_hashes": raw_receipt_file_hashes(state_dir, bundles),
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
    record_phase_pid(state_dir, "reopen")
    key = (repo / ".airlock" / "verification.key").read_bytes()
    bundles = {p: load_bundle(state_dir, p) for p in ("rootU", "gen1", "gen2", "gen3")}
    checkpoint = read_json(state_dir / "checkpoint.json")
    gen1 = bundles["gen1"]

    # Re-verify every precondition from disk in this fresh process.
    try:
        projection = project_bundles(bundles, repo, key)
    except EvidenceError as exc:
        raise PreconditionFailure(f"lineage binding failure before REOPEN: {exc}", "LINEAGE_BINDING_FAILURE") from exc
    standings = {b["lesson"]["lesson_id"]: projection[b["lesson"]["lesson_id"]].status for b in bundles.values()}
    if any(s != "inherited" for s in standings.values()):
        raise PreconditionFailure(f"reopen precondition: standings not all inherited: {standings}", "CHECKPOINT_NOT_ESTABLISHED")
    ref_hashes, policy_hashes = _installed_hashes(repo, bundles)
    if ref_hashes != checkpoint["installed_ref_hashes"] or policy_hashes != checkpoint["installed_policy_hashes"]:
        raise PreconditionFailure("installed state moved between checkpoint and REOPEN", "INSTALLED_REF_MUTATION")

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
        raise PreconditionFailure("forged REOPEN was unexpectedly accepted", "REOPEN_NOT_OBSERVED")

    # Controlled support loss for gen1's promotion evidence.
    support = Path(gen1["installation"]["support_witness"])
    if support.exists():
        raise PreconditionFailure("REOPEN control requires gen1's support witness to be absent", "REOPEN_NOT_OBSERVED")

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

    # Restart boundary: the REOPEN process terminates here. It does NOT spawn
    # reproject. The orchestrator dispatches run_phase(..., "reopen", ...)
    # then run_phase(..., "reproject", ...) as two separate sequential fresh
    # processes (frozen sequence steps 10-11). Reprojection reconstructs
    # everything it needs from persisted disk evidence plus the internal
    # phase-token authorization.

def phase_reproject(state_path: Path) -> None:
    """Fresh process: reload every record from disk, reproject twice
    (determinism), require the propagated standings, compute the gen4
    admission probe (never executed), verify history is byte-identical,
    decide the verdict, and write the receipt."""
    state = read_json(state_path)
    repo = Path(state["repo"])
    state_dir = Path(state["state_dir"])
    record_phase_pid(state_dir, "reproject")
    # The complete 12-phase process map must be present and all distinct
    # before the receipt binds it.
    phase_pids = require_distinct_phase_pids(state_dir)
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
        raise PreconditionFailure("lineage record set changed between checkpoint and reprojection", "LINEAGE_BINDING_FAILURE")

    try:
        run_a = project_lineage_memories(
            generations, lineage_records, installed_policies, key
        )
        run_b = project_lineage_memories(
            generations, lineage_records, installed_policies, key
        )
    except EvidenceError as exc:
        raise PreconditionFailure(f"lineage binding failure at reprojection: {exc}", "LINEAGE_BINDING_FAILURE") from exc
    snap = lambda proj: {lid: proj[lid].to_dict() for lid in sorted(proj)}  # noqa: E731
    deterministic = json.dumps(snap(run_a), sort_keys=True) == json.dumps(snap(run_b), sort_keys=True)

    by_lesson = {b["lesson"]["lesson_id"]: b["prefix"] for b in bundles.values()}
    standings = {by_lesson[lid]: mem.status for lid, mem in run_a.items() if lid in by_lesson}
    gen1_questioned = standings.get("gen1") == "questioned"
    if not gen1_questioned:
        raise PreconditionFailure(
            f"valid REOPEN did not question gen1 (status={standings.get('gen1')}); propagation question is moot",
            "REOPEN_NOT_OBSERVED")
    for lid, mem in run_a.items():
        if lid in by_lesson and mem.to_dict()["installed_state_action"] != "NONE":
            raise PreconditionFailure(f"{by_lesson[lid]} standing acquired rollback authority", "LINEAGE_BINDING_FAILURE")

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
        raise PreconditionFailure(f"gen4 probe lineage failure: {exc}", "LINEAGE_BINDING_FAILURE") from exc

    final_receipts = _receipt_hashes(state_dir, bundles)
    # gen1's REOPEN standing is new post-checkpoint evidence; it is bound
    # separately in reopen_evidence, not in the historical-receipt comparison.
    final_receipts["gen1"]["standing"] = checkpoint["historical_receipt_hashes"]["gen1"]["standing"]

    # RAW byte identity: the exact historical receipt files on disk
    # (generation, promotion, pre-existing standing, lineage) must be
    # byte-identical to what checkpoint froze. A whitespace-only reformat
    # changes the raw digest even when canonical parsing is unchanged.
    raw_final = raw_receipt_file_hashes(state_dir, bundles)
    raw_pre = checkpoint["historical_receipt_file_hashes"]
    receipts_byte_identical = historical_files_unchanged(raw_pre, raw_final)

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
        receipts_byte_identical=receipts_byte_identical,
        deterministic=deterministic,
        gen1_questioned=gen1_questioned,
        standings=standings,
        gen4_probe=probe_disposition,
    )

    lineage_summary = read_json(state_dir / "lineage.json")
    receipt = {
        "schema": "airlock.rsi-005.result.v1",
        "experiment": "RSI-005 lineage-aware inheritance",
        "verdict": verdict,
        "cause_code": cause_code,
        # Complete scientific-package bindings: exactly which harness,
        # runner, preregistration, Airlock base, Verified Memory, and Git
        # HEAD produced this receipt. The normalized runner hash is the
        # prereg-bound canonical identity; the file hash is the literal
        # bytes that executed.
        "airlock_base_sha": AIRLOCK_BASE_MAIN,
        "qualified_harness_sha256": QUALIFIED_HARNESS_SHA256,
        "qualified_harness_source_commit": QUALIFIED_HARNESS_COMMIT,
        "scientific_runner_normalized_sha256": normalized_runner_sha256(),
        "scientific_runner_file_sha256": sha256_file(Path(__file__).resolve()),
        "preregistration_sha256": sha256_file(PREREG_PATH),
        "verified_memory_sha": VERIFIED_MEMORY_COMMIT,
        "verified_memory_evidence_py_sha256": EVIDENCE_PY_SHA256,
        "execution_head_sha": _execution_head_sha(),
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
            "fresh_process": len(
                {checkpoint["process_pid"], reopen["process_pid"], os.getpid()}
            ) == 3,
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
        "historical_receipt_file_hashes": {
            "checkpoint": raw_pre,
            "final": raw_final,
            "byte_identical": receipts_byte_identical,
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
        "phase_process_pids": phase_pids,
        "phase_pids_distinct": len(set(phase_pids.values())) == len(FRESH_PROCESS_PHASES),
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
        raise PreconditionFailure(f"receipt failed binding validation: {problems}", "RECEIPT_MUTATION")
    write_json(state_dir / "result.json", receipt)

def primary_gate(argv: list[str]) -> bool:
    """The explicit execution gate. The primary sequence is encoded but never
    invoked unless this returns True. Default invocation stays closed."""
    return EXECUTE_PRIMARY_FLAG in argv

def _phase_cause_from_stderr(stderr: str, phase: str) -> tuple[str, str]:
    """Extract (message, cause_code) from a phase child's stderr. The child
    prints CAUSE_CODE=<code> on its own stderr line; the code must be one of
    the preregistered CAUSE_CODES. Fail closed (harness error, no verdict)
    if the code is absent or invalid: cause classification is never guessed
    from message substrings."""
    cause = ""
    for line in stderr.splitlines():
        if line.startswith("CAUSE_CODE="):
            cause = line[len("CAUSE_CODE="):].strip()
    if cause not in CAUSE_CODES:
        raise RuntimeError(
            f"RSI-005 phase {phase} reported a precondition failure without a "
            f"valid cause code (stderr: {stderr[-500:]!r})"
        )
    first = stderr.strip().splitlines()[0] if stderr.strip() else phase
    return first, cause


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
        # The phase reported a preregistered precondition failure with an
        # explicit cause code; preserve it through to the orchestrator.
        message, cause = _phase_cause_from_stderr(cp.stderr, phase)
        raise PreconditionFailure(message, cause)
    if cp.returncode != 0:
        raise RuntimeError(
            f"RSI-005 phase {phase} failed ({cp.returncode})\nstdout:\n{cp.stdout}\nstderr:\n{cp.stderr}"
        )

def normalized_runner_sha256() -> str:
    """The documented canonicalized runner hash: SHA-256 of this file's
    bytes with the single PREREG_SHA256 assignment line replaced by 64
    zeros before hashing. This breaks the mutual prereg<->runner binding so
    both hold simultaneously: the preregistration binds this normalized
    value as scientific_runner_sha256, while the literal file-byte hash
    (sha256_file of this file) is bound separately as
    scientific_runner_file_sha256. The two are deliberately distinct."""
    src = Path(__file__).resolve().read_text(encoding="utf-8")
    canonical = re.sub(
        r'^PREREG_SHA256 = "[^"]*"$',
        'PREREG_SHA256 = "' + "0" * 64 + '"',
        src,
        flags=re.M,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _execution_head_sha() -> str:
    """Exactly one lowercase 40-char Git HEAD SHA, or fail closed.

    There is no UNKNOWN escape hatch: if Git HEAD cannot be resolved or is
    malformed, the scientific primary must not begin. That is a
    pre-primary/harness failure, never a substitute value."""
    try:
        head = sh("git", "rev-parse", "HEAD",
                  cwd=str(Path(__file__).resolve().parents[2])).strip()
    except RuntimeError as exc:
        raise RuntimeError(f"RSI-005 cannot resolve execution Git HEAD: {exc}") from exc
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise RuntimeError(f"RSI-005 execution Git HEAD malformed: {head!r}")
    return head


def _prereg_bound_runner_sha256() -> str:
    """The normalized scientific-runner hash frozen in the preregistration
    file (bindings.scientific_runner_sha256). The prereg file itself is the
    authority; no hard-coded constant, so no second circular binding."""
    try:
        doc = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
        bound = doc["bindings"]["scientific_runner_sha256"]
    except (OSError, ValueError, KeyError, TypeError):
        return ""
    return bound if isinstance(bound, str) else ""


def _prereg_runner_binding_problems() -> list[str]:
    """Fail closed unless the executing runner's normalized hash equals the
    prereg-bound normalized runner hash. The prereg file was already
    hash-verified against PREREG_SHA256 before this runs."""
    bound = _prereg_bound_runner_sha256()
    if not re.fullmatch(r"[0-9a-f]{64}", bound):
        return ["prereg-bound scientific_runner_sha256 is missing or malformed"]
    if normalized_runner_sha256() != bound:
        return [
            "executing scientific runner's normalized hash does not match "
            "the prereg-bound scientific_runner_sha256"
        ]
    return []


def _static_package_identities() -> dict[str, str]:
    """Static identities of the exact scientific package that executed:
    which harness, which runner, which preregistration, which Airlock base,
    which Verified Memory, and which Git HEAD. Bound in both the successful
    receipt and INCONCLUSIVE terminal evidence. The execution HEAD is
    mandatory and exact: _execution_head_sha() fails closed (no UNKNOWN)
    if Git HEAD cannot be resolved, so INCONCLUSIVE evidence likewise
    requires an exact 40-char HEAD; a mid-run resolution failure surfaces
    as a harness error, never a substitute value."""
    return {
        "airlock_base_sha": AIRLOCK_BASE_MAIN,
        "qualified_harness_sha256": QUALIFIED_HARNESS_SHA256,
        "qualified_harness_source_commit": QUALIFIED_HARNESS_COMMIT,
        "scientific_runner_normalized_sha256": normalized_runner_sha256(),
        "scientific_runner_file_sha256": sha256_file(Path(__file__).resolve()),
        "preregistration_sha256": sha256_file(PREREG_PATH),
        "verified_memory_sha": VERIFIED_MEMORY_COMMIT,
        "verified_memory_evidence_py_sha256": EVIDENCE_PY_SHA256,
        "execution_head_sha": _execution_head_sha(),
    }


def inconclusive_result(exc: PreconditionFailure, state_dir: Path | None) -> dict:
    """INCONCLUSIVE terminal evidence. The cause code comes directly off
    the exception (explicit, never substring-derived) and the same static
    package identities bound in the successful receipt are preserved here,
    so a first authorized run that ends INCONCLUSIVE still records exactly
    which harness, runner, preregistration, Verified Memory, and Git HEAD
    executed."""
    return {
        "schema": "airlock.rsi-005.result.v1",
        "experiment": "RSI-005 lineage-aware inheritance",
        "verdict": VERDICT_INCONCLUSIVE,
        "cause_code": exc.cause_code,
        "reason": str(exc),
        **_static_package_identities(),
    }

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
            "RSI-005 self-check FAILED - stopping before execution:\n"
            + "\n".join(f"  - {p}" for p in problems)
        )
    root = Path(tempfile.mkdtemp(prefix="airlock-rsi-005-"))
    script = Path(__file__).resolve()
    state_dir: Path | None = None
    try:
        state = h.build_fixture(root)
        state_path = root / "state.json"
        state_dir = Path(state["state_dir"])
        env = h._phase_env(state)

        # Scientific shim ownership: the qualified harness installs an inert
        # placeholder generator and owns fixture/state/token/Nightshift-entry.
        # The scientific package owns candidate shims. rootU's selection runs
        # under ROOTU_SHIM; later phases rebind the generator via _write_shim
        # with their parent's exact installed policy bytes baked in.
        _write_shim(Path(state["hermes_executable"]), ROOTU_SHIM)

        # RSI-005 contact boundary: the orchestration layer NEVER writes the
        # primary-contact marker and NEVER calls Nightshift directly. The
        # marker is created only by the qualified harness's nightshift_entry()
        # immediately before run_nightshift is entered, inside the first
        # selection phase. From that moment the primary is in motion and
        # anti-rescue is in effect for RSI-005.
        #
        # Unpredictable internal phase token: --phase is internal-only. The
        # qualified harness primitive mints the token into the temporary
        # state and it is bound into each phase subprocess's environment;
        # phase dispatch refuses to run without the matching token, before
        # any Nightshift contact.
        phase_token = h.write_phase_token(state_dir)
        env[h.PHASE_TOKEN_ENV] = phase_token

        for phase in (
            "select-rootU", "install-rootU",
            "select-gen1", "install-gen1",
            "select-gen2", "install-gen2",
            "select-gen3", "install-gen3",
            "mint-lineage", "checkpoint",
        ):
            run_phase(script, phase, state_path, env)

        # Controlled support loss for gen1's promotion evidence, then REOPEN in
        # its own fresh process. The reopen process terminates after persisting
        # the REOPEN evidence (frozen sequence step 10); reprojection is then
        # dispatched as a separate sequential fresh process from persisted
        # disk evidence (frozen sequence step 11).
        (state_dir / "gen1_support.witness").unlink()
        run_phase(script, "reopen", state_path, env)
        run_phase(script, "reproject", state_path, env)

        result = read_json(state_dir / "result.json")
        # All 12 phases must have run in distinct fresh processes, including
        # mint-lineage; the complete PID map is bound in the receipt.
        phase_pids = require_distinct_phase_pids(state_dir)
        if result.get("phase_process_pids") != phase_pids:
            raise PreconditionFailure("receipt phase-PID map does not match the recorded phase PIDs", "RECEIPT_MUTATION")
        if output is not None:
            write_json(output, result)
        return result
    except PreconditionFailure as exc:
        result = inconclusive_result(exc, state_dir)
        if output is not None:
            write_json(output, result)
        return result
    finally:
        shutil.rmtree(root, ignore_errors=True)

def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        description="RSI-005 lineage-aware inheritance (default: self-check only; primary gated)"
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
            print("RSI-005 self-check FAILED:")
            for p in problems:
                print(f"  - {p}")
            return 1
        print(
            "RSI-005 scientific self-check clean: qualified harness bytes bound, "
            "preregistration bytes frozen, base ancestry confirmed, Nightshift "
            "choke point exclusive. Primary NOT executed (pass --execute-primary "
            "only when authorized)."
        )
        return 0

    if args.phase:
        if args.state is None:
            parser.error("--state is required with --phase")
        # --phase is internal-only: the orchestrator mints an unpredictable
        # token into its temporary state and binds it into each phase
        # subprocess's environment. A direct external
        # --execute-primary --phase ... invocation cannot present the token
        # and is refused here, before any phase code (and therefore before
        # any Nightshift contact) runs.
        token_state = read_json(args.state)
        token_file = Path(token_state["state_dir"]) / ".phase_token"
        expected = token_file.read_text(encoding="utf-8").strip() if token_file.exists() else ""
        presented = os.environ.get(h.PHASE_TOKEN_ENV, "")
        if not expected or not presented or not secrets.compare_digest(presented, expected):
            parser.error("--phase is internal-only: missing or invalid orchestrator phase token")
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
            # map them to INCONCLUSIVE rather than a harness crash. The
            # explicit cause code travels on its own stderr line so the
            # parent can preserve it without substring inference.
            print(f"RSI-005 precondition failure in {args.phase}: {exc}", file=sys.stderr)
            print(f"CAUSE_CODE={exc.cause_code}", file=sys.stderr)
            return 42
        return 0

    try:
        result = orchestrate(args.output)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"RSI-005 harness error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0

def _verified_memory_installed_commit() -> str | None:
    """Resolve the installed openline-verified-memory distribution to the
    exact VCS commit it was installed from, via its direct_url.json
    provenance (PEP 610). Returns None when provenance is unavailable."""
    try:
        from importlib.metadata import distribution
        dist = distribution("openline-verified-memory")
        raw = dist.read_text("direct_url.json")
    except Exception:
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    return (payload.get("vcs_info") or {}).get("commit_id")


def _verified_memory_commit_problems() -> list[str]:
    """Fail closed unless the installed openline-verified-memory package
    resolves to the exact pinned commit AND its evidence.py bytes match the
    pinned hash. Bytes alone are not enough: the authorized primary will
    run locally, not only in CI, so provenance must be checked here too."""
    try:
        import openline_verified_memory as ovm
    except ImportError as exc:
        return [f"cannot import openline-verified-memory: {exc}"]
    try:
        evidence = Path(ovm.__file__).with_name("evidence.py")
        digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    except OSError as exc:
        return [f"cannot read installed openline-verified-memory evidence.py: {exc}"]
    problems: list[str] = []
    if digest != EVIDENCE_PY_SHA256:
        problems.append(
            "installed openline-verified-memory evidence.py does not match the pinned hash "
            f"{EVIDENCE_PY_SHA256[:12]}..."
        )
    commit = _verified_memory_installed_commit()
    if commit != VERIFIED_MEMORY_COMMIT:
        problems.append(
            "installed openline-verified-memory does not resolve to the pinned commit "
            f"{VERIFIED_MEMORY_COMMIT} (observed: {commit!r})"
        )
    return problems


def self_check() -> list[str]:
    """Non-executing verification of every frozen binding for the RSI-005
    scientific package. Returns a list of problems; empty means clean.
    Never dispatches phases, never touches Nightshift, never writes the
    primary-contact marker, never issues REOPEN."""
    problems: list[str] = list(h.self_check())

    # 1. The scientific runner binds to the QUALIFIED harness bytes: fail
    # closed unless run_rsi_005.py hashes exactly to the frozen value.
    harness_path = Path(h.__file__).resolve()
    try:
        harness_sha = sha256_file(harness_path)
    except OSError as exc:
        problems.append(f"cannot read qualified harness file: {exc}")
        harness_sha = ""
    if harness_sha and harness_sha != QUALIFIED_HARNESS_SHA256:
        problems.append(
            "qualified harness runner bytes do not match the frozen binding "
            f"{QUALIFIED_HARNESS_SHA256[:12]}..."
        )

    # 2. The frozen scientific preregistration bytes.
    try:
        prereg_sha = sha256_file(PREREG_PATH)
    except OSError as exc:
        problems.append(f"cannot read scientific preregistration: {exc}")
        prereg_sha = ""
    if prereg_sha and prereg_sha != PREREG_SHA256:
        problems.append(
            "RSI-005 scientific preregistration bytes do not match the frozen binding"
        )

    # 3. The scientific package builds on the merged qualified-harness main.
    try:
        sh(
            "git", "merge-base", "--is-ancestor", AIRLOCK_BASE_MAIN, "HEAD",
            cwd=str(Path(__file__).resolve().parents[2]),
        )
    except RuntimeError:
        problems.append(
            f"scientific base {AIRLOCK_BASE_MAIN} is not an ancestor of HEAD"
        )

    # 4. Structural: this file must contain no Nightshift call path except
    # the qualified harness's nightshift_entry().
    source = Path(__file__).read_text(encoding="utf-8")
    parsed = ast.parse(source)
    direct = [
        node for node in ast.walk(parsed)
        if isinstance(node, ast.Name) and node.id == "run_nightshift"
    ]
    if direct:
        problems.append(
            "scientific runner references run_nightshift directly; all Nightshift "
            "calls must go through h.nightshift_entry()"
        )

    # 5. Structural: the primary-contact marker is never written by this
    # file; only the qualified harness's nightshift_entry() writes it.
    def _is_marker_write(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "write_text"
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "PRIMARY_CONTACT_MARKER"
        )

    if any(_is_marker_write(node) for node in ast.walk(parsed)):
        problems.append(
            "scientific runner writes the primary-contact marker; "
            "only h.nightshift_entry() may"
        )

    # 6. Verified Memory provenance: the installed package must resolve to
    # the exact pinned commit AND its evidence.py must match the pinned
    # bytes. The authorized primary runs locally, not only in CI.
    problems.extend(_verified_memory_commit_problems())

    # 7. Prereg-bound normalized runner identity: the frozen preregistration
    # (already hash-verified above) binds bindings.scientific_runner_sha256;
    # the executing runner's normalized hash must equal it. The prereg file
    # itself is the authority (no hard-coded constant, no second circular
    # binding).
    problems.extend(_prereg_runner_binding_problems())

    # 8. Execution HEAD provenance: git rev-parse HEAD must resolve to
    # exactly one lowercase 40-char SHA before any primary phase dispatch.
    # Unresolvable or malformed HEAD is a pre-primary failure: the primary
    # must not begin, and no substitute value is invented.
    try:
        _execution_head_sha()
    except RuntimeError as exc:
        problems.append(str(exc))

    return problems

if __name__ == "__main__":
    raise SystemExit(main())
