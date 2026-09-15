"""Deterministic crash-injection fixture driver for RSI-006-Q4.

Replays Q3's causal order against a fake substrate with outcomes as a
pure function of (seed, mutant_id):

  contact -> discovery -> seal -> nonce -> confirmation
  -> determinism reruns -> metrics -> verdict -> report

Termination is injected as a real ``os._exit(1)`` (no cleanup, no
finally -- the way a host loss kills a process) at the exact
instrumentation point named by ``--crash-point``. A fresh process
invocation with the same ``--work-dir`` then resumes the same
transaction via ``ScientificTransaction.open``.

Fixture-only deviations from a real Q4 run (all documented in
RSI_006_Q4_SPEC.md, none touching scientific constants):
  - fake repositories/mutants; outcomes are sha256-derived, not pytest;
  - the confirmation nonce is derived deterministically from the
    transaction ID so control and resumed runs are comparable; the
    transaction layer is nonce-agnostic and the real protocol keeps
    Q3's fresh-OS-entropy semantics.

With ``--exec-log`` the driver additionally maintains an independently
durable, append-only execution receipt OUTSIDE the Q4 journal
(``exec_log/exec_receipt.jsonl`` plus per-execution outcome artifacts),
recording every physical observation execution with an fsync. Each
recorded outcome carries a fresh random ``exec_nonce``, so a
re-execution is detectable by more than counting: the bytes differ.
Crash points ``execution_gap`` and ``commit_gap`` (with
``--crash-target MID``) kill the process after the outcome is durably
recorded but before the transaction commits it -- either before
``commit_observation`` runs at all, or inside it after the artifact
rename but before the journal append. On resume the driver adopts the
orphan via ``adopt_orphan_observation`` (verified) instead of
re-executing; unverifiable orphans fail closed.

Usage:
  python fixture_driver.py --work-dir DIR [--crash-point NAME]
                           [--exec-log] [--crash-target MID]

No real repositories, no real mutants, no scientific contact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

EXP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EXP_DIR))
import stransaction as st

REPOS = ["alpha", "beta"]
HALVES = ["A", "B"]
DISC_PER_HALF = 6
CONF_PER_REPO = 4
DET_PER_REPO = 2
FAKE_OPERATORS = ("OP_X", "OP_Y", "OP_Z")

FIXTURE_RECEIPT_SHA = st.sha256_bytes(b"RSI-006-Q4-FIXTURE-RECEIPT-V1")


def code_hashes() -> dict[str, str]:
    return {
        "stransaction.py": st.sha256_file(EXP_DIR / "stransaction.py"),
        "RSI_006_Q4_SPEC.md": st.sha256_file(EXP_DIR / "RSI_006_Q4_SPEC.md"),
    }


def discovery_ids(repo: str, half: str) -> list[str]:
    return [f"{repo}-{half}-{i:04d}" for i in range(DISC_PER_HALF)]


def confirmation_ids(repo: str) -> list[str]:
    return [f"{repo}-C-{i:04d}" for i in range(CONF_PER_REPO)]


def fake_record(mutant_id: str, phase: str, seed: str, repo: str,
                half: str | None = None,
                exec_nonce: str | None = None) -> dict:
    h = hashlib.sha256(f"{seed}\x00{mutant_id}".encode()).digest()
    rec = {
        "mutant_id": mutant_id,
        "repo": repo,
        "phase": phase,
        "operator": FAKE_OPERATORS[h[1] % len(FAKE_OPERATORS)],
        "kill": (h[0] % 10) < 5,
        "collection_error": False,
        "seed": seed,
    }
    if half is not None:
        rec["half"] = half
    if exec_nonce is not None:
        # Fresh randomness per physical execution. Makes a re-execution
        # detectable by outcome bytes, not just by counting executions.
        rec["exec_nonce"] = exec_nonce
    return rec


def seal_for(members: dict[str, bytes]) -> str:
    blob = b"\n".join(members[mid] for mid in sorted(members))
    return st.sha256_bytes(blob)


# --------------------------------------------------------------------------
# Independently durable execution log (outside the Q4 journal).
#
# Every physical observation execution appends one JSON line, fsync'd, to
# exec_log/exec_receipt.jsonl and stores its outcome bytes atomically at
# exec_log/outcomes/<mid>.json. This models "the work physically happened
# and left evidence outside the journal". On resume, observations that
# executed but were never committed are adopted from this evidence --
# never re-executed.
# --------------------------------------------------------------------------

def exec_log_dir(work_dir: Path) -> Path:
    return work_dir / "exec_log"


def append_exec_entry(work_dir: Path, entry: dict) -> None:
    d = exec_log_dir(work_dir)
    (d / "outcomes").mkdir(parents=True, exist_ok=True)
    line = st.canonical_bytes(entry) + b"\n"
    with open(d / "exec_receipt.jsonl", "ab") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def read_exec_log(work_dir: Path) -> tuple[list[dict], bool]:
    """Return (entries, torn).

    ``torn`` is True when the receipt is damaged: a missing trailing
    newline (crash mid-append) or an unparseable/malformed line. A torn
    receipt can hide a second execution of the target observation, so no
    orphan outcome can be proven from it.
    """
    p = exec_log_dir(work_dir) / "exec_receipt.jsonl"
    if not p.exists():
        return [], False
    raw = p.read_bytes()
    if not raw:
        return [], False
    torn = not raw.endswith(b"\n")
    lines = raw.splitlines()
    if torn:
        lines = lines[:-1]  # suspect tail excluded; still torn
    entries: list[dict] = []
    for ln in lines:
        if not ln.strip():
            continue
        try:
            e = json.loads(ln)
        except Exception:
            torn = True
            break
        if not isinstance(e, dict) or "observation_id" not in e:
            torn = True
            break
        entries.append(e)
    return entries, torn


def scan_and_adopt_orphans(tx: "st.ScientificTransaction", work_dir: Path,
                           plan: list[tuple[str, str]]) -> None:
    """Adopt durably-recorded orphan outcomes instead of re-executing.

    For every planned observation with no committed journal entry, check
    the independent execution receipt. If the observation physically
    executed, adopt its exact recorded outcome via
    ``adopt_orphan_observation`` (which verifies transaction ID,
    observation ID, receipt/code bindings, and artifact digest). If the
    receipt is torn, or an observation shows anything other than exactly
    one execution record, fail closed: the outcome cannot be proven.
    Observations with no execution record are left for fresh execution.
    """
    entries, torn = read_exec_log(work_dir)
    if not entries and not torn:
        return
    need_adoption = any(mid not in tx.observations for mid, _ in plan)
    if not need_adoption:
        return
    if torn:
        raise st.OrphanUnverifiable(
            "execution receipt is torn; an orphan outcome cannot be "
            "proven -- failing closed instead of re-executing")
    by_mid: dict[str, list[dict]] = {}
    for e in entries:
        by_mid.setdefault(e["observation_id"], []).append(e)
    for mid, phase in plan:
        if mid in tx.observations:
            continue
        cands = by_mid.get(mid, [])
        if not cands:
            continue  # never executed; the driver will execute it fresh
        if len(cands) != 1:
            raise st.OrphanUnverifiable(
                f"observation {mid} has {len(cands)} execution records: "
                f"cannot prove a single outcome -- failing closed")
        entry = cands[0]
        orphan_art = (tx.work_dir / "artifacts" / "observations"
                      / f"{mid}.json")
        if orphan_art.exists():
            # Commit gap: the crashed commit_observation left its durable
            # outcome artifact; verify it against the independent digest.
            outcome_bytes = orphan_art.read_bytes()
        else:
            # Execution gap: commit_observation never ran; the outcome
            # lives only in the independent execution log.
            outcome_bytes = (exec_log_dir(work_dir) / "outcomes"
                             / f"{mid}.json").read_bytes()
        tx.adopt_orphan_observation(mutant_id=mid, phase=phase,
                                    outcome_bytes=outcome_bytes,
                                    evidence=entry)


def execute_observation(tx: "st.ScientificTransaction", work_dir: Path,
                        mid: str, phase: str, record: dict,
                        exec_log_mode: bool, crash_target: str | None,
                        crash_point: str | None) -> bytes:
    """Execute one fake observation and commit it.

    In exec-log mode the physical execution is durably recorded outside
    the journal (outcome artifact + fsync'd receipt entry) before the
    transaction commit, so a crash in the execution/commit gap leaves
    independently verifiable evidence instead of an excuse to rerun.
    """
    outcome_bytes = st.canonical_bytes(record)
    if exec_log_mode:
        out_d = exec_log_dir(work_dir) / "outcomes"
        out_d.mkdir(parents=True, exist_ok=True)
        st._atomic_write(out_d / f"{mid}.json", outcome_bytes)
        append_exec_entry(work_dir, {
            "txid": tx.txid,
            "observation_id": mid,
            "phase": phase,
            "outcome_digest": st.sha256_bytes(outcome_bytes),
            "receipt_sha256": FIXTURE_RECEIPT_SHA,
            "code_hashes": code_hashes(),
            "launch": {"restart_count": tx.restart_count,
                       "pid": os.getpid()},
        })
        if crash_point == "execution_gap" and mid == crash_target:
            # The observation completed and its outcome is durably
            # recorded; die before commit_observation runs.
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(1)
    hook = None
    if crash_point == "commit_gap" and mid == crash_target:
        def hook() -> None:
            # Die inside commit_observation: after the outcome artifact
            # is durably renamed, before the journal entry binding its
            # digest is appended.
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(1)
    tx.commit_observation(
        mutant_id=mid, phase=phase, canonical=outcome_bytes,
        launch={"restart_count": tx.restart_count, "pid": os.getpid()},
        _crash_hook=hook)
    return outcome_bytes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--crash-point", default=None)
    ap.add_argument("--exec-log", action="store_true",
                    help="durably record every physical observation "
                         "execution outside the Q4 journal and adopt "
                         "orphans on resume instead of re-executing")
    ap.add_argument("--crash-target", default=None,
                    help="observation ID for the execution_gap/commit_gap "
                         "crash points")
    args = ap.parse_args()
    work_dir = Path(args.work_dir)
    exec_log_mode = args.exec_log

    def maybe_crash(point: str) -> None:
        if args.crash_point == point:
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(1)

    if (work_dir / "journal").is_dir():
        tx = st.ScientificTransaction.open(
            work_dir, receipt_sha256=FIXTURE_RECEIPT_SHA,
            code_hashes=code_hashes())
    else:
        tx = st.ScientificTransaction.begin(
            work_dir, receipt_sha256=FIXTURE_RECEIPT_SHA,
            code_hashes=code_hashes())

    # Launch metadata must record every restart, even when the resumed
    # process commits no new observations (e.g. crash at verdict time).
    if tx.restart_count >= 1:
        launches = tx.work_dir / "artifacts" / "launches"
        launches.mkdir(parents=True, exist_ok=True)
        st._atomic_write(
            launches / f"resume-{tx.restart_count}.json",
            st.canonical_bytes({"restart_count": tx.restart_count,
                                "pid": os.getpid(), "txid": tx.txid}))

    # Full observation plan, for orphan adoption on resume.
    plan: list[tuple[str, str]] = []
    for _repo in REPOS:
        for _half in HALVES:
            for _mid in discovery_ids(_repo, _half):
                plan.append((_mid, "discovery"))
    for _repo in REPOS:
        for _mid in confirmation_ids(_repo):
            plan.append((_mid, "confirmation"))
    for _repo in REPOS:
        for _mid in discovery_ids(_repo, "A")[:DET_PER_REPO]:
            plan.append((f"{_mid}-rerun", "det_rerun"))

    if exec_log_mode:
        # Adopt durably-recorded orphan outcomes; never re-execute.
        scan_and_adopt_orphans(tx, work_dir, plan)

    def fresh_nonce() -> str | None:
        return os.urandom(16).hex() if exec_log_mode else None

    # -- contact (exactly once, survives restart) -------------------------
    if tx.contact_event is None:
        r = tx.note_contact(mutant_id="fixture-contact-mutant-0001",
                            child_pid=os.getpid())
        assert r["created"] is True
        maybe_crash("after_contact")
    contact_mid = tx.contact_event["mutant_id"]

    # -- discovery ---------------------------------------------------------
    for repo in REPOS:
        for half in HALVES:
            seed = f"Q4-FIXTURE-discovery-{half}"
            for mid in tx.pending(discovery_ids(repo, half)):
                rec = fake_record(mid, "discovery", seed, repo, half,
                                  exec_nonce=fresh_nonce())
                execute_observation(tx, work_dir, mid, "discovery", rec,
                                    exec_log_mode, args.crash_target,
                                    args.crash_point)
        if repo not in tx.seals:
            members = {}
            for half in HALVES:
                for mid in discovery_ids(repo, half):
                    members[mid] = (tx.work_dir / "artifacts"
                                    / "observations" / f"{mid}.json"
                                    ).read_bytes()
            tx.commit_discovery_seal(
                repo=repo, seal=seal_for(members),
                member_ids=list(members))
    maybe_crash("after_discovery_seal")

    # -- nonce (committed before any confirmation work) --------------------
    if tx.nonce is None:
        nonce = st.sha256_bytes(b"Q4-FIXTURE-NONCE\x00"
                                + tx.txid.encode())
        tx.commit_nonce(nonce_hex=nonce)
        maybe_crash("after_nonce_commit")
    nonce = tx.nonce
    conf_seed = f"Q4-FIXTURE-confirmation-{nonce}"

    # -- confirmation ------------------------------------------------------
    conf_ids = [mid for repo in REPOS for mid in confirmation_ids(repo)]
    done_before = sum(1 for mid in conf_ids if mid in tx.observations)
    for mid in tx.pending(conf_ids):
        repo = mid.split("-C-")[0]
        rec = fake_record(mid, "confirmation", conf_seed, repo,
                          exec_nonce=fresh_nonce())
        execute_observation(tx, work_dir, mid, "confirmation", rec,
                            exec_log_mode, args.crash_target,
                            args.crash_point)
        done_before += 1
        if done_before == 3:
            maybe_crash("mid_confirmation")

    # -- determinism reruns -------------------------------------------------
    for repo in REPOS:
        seed = "Q4-FIXTURE-discovery-A"
        for mid in discovery_ids(repo, "A")[:DET_PER_REPO]:
            rid = f"{mid}-rerun"
            if rid not in tx.observations:
                rec = fake_record(rid, "det_rerun", seed, repo, "A",
                                  exec_nonce=fresh_nonce())
                execute_observation(tx, work_dir, rid, "det_rerun", rec,
                                    exec_log_mode, args.crash_target,
                                    args.crash_point)

    # -- metrics + verdict (pure function of committed records) ------------
    if tx.verdict is None:
        records = {}
        for p in (tx.work_dir / "artifacts" / "observations").glob("*.json"):
            import json as _json
            records[p.stem] = _json.loads(p.read_bytes())
        disc = [r for r in records.values() if r["phase"] == "discovery"]
        kr = sum(1 for r in disc if r["kill"]) / len(disc)
        agree = all(
            records[f"{mid}-rerun"]["kill"]
            == records[mid]["kill"]
            for repo in REPOS for mid in discovery_ids(repo, "A")[:DET_PER_REPO]
        )
        verdict = ("QUALIFIED_FIXTURE"
                   if 0.05 <= kr <= 0.95 and agree
                   else "NOT_QUALIFIED_FIXTURE")
        report = {
            "n_observations": len(records),
            "kill_rate_discovery": kr,
            "det_rerun_agreement": 1.0 if agree else 0.0,
            "results_digest": tx.results_digest(),
            "note": "deterministic fixture; no real substrate",
        }
        maybe_crash("before_verdict_commit")

        def _mid_commit_crash() -> None:
            maybe_crash("mid_verdict_commit")

        tx.commit_verdict(verdict=verdict, report=report,
                          _crash_hook=_mid_commit_crash)

    # -- summary ------------------------------------------------------------
    max_restart = 0
    for p in (tx.work_dir / "artifacts" / "launches").glob("*.json"):
        import json as _json
        max_restart = max(max_restart,
                          _json.loads(p.read_bytes())["restart_count"])
    canonical_digest = st.sha256_bytes(
        (tx.results_digest() + "|" + tx.verdict["verdict"]).encode())
    print(f"TXID={tx.txid}", flush=True)
    print(f"CONTACT_MID={contact_mid}", flush=True)
    print(f"NONCE={tx.nonce}", flush=True)
    print(f"CANONICAL_DIGEST={canonical_digest}", flush=True)
    print(f"VERDICT={tx.verdict['verdict']}", flush=True)
    print(f"MAX_RESTART_COUNT={max_restart}", flush=True)
    print(f"N_OBSERVATIONS={len(tx.observations)}", flush=True)


if __name__ == "__main__":
    main()
