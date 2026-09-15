"""RSI-006-Q4 durable scientific-transaction layer.

Successor to the RSI-006-Q3 contact boundary. Q3 bound the irreversible
scientific authorization to one process and one volatile work directory:
when the host died mid-run, the contact marker, observations, seals, and
nonce evidence died with it, and the protocol had no continuation
semantics -- the run could neither resume nor produce a verdict. The
frozen Q3 close-out (proofs/rsi-006-q3/) records exactly that failure.

Q4 adds one thing and nothing else: a durable, receiver-owned scientific
transaction. The transaction journals every phase transition atomically
(temp file + fsync + rename + fsync of the containing directory) into a
work directory that MUST NOT live under ephemeral /tmp. Journal entries
form a SHA-256 hash chain; every artifact is content-bound by SHA-256.
After a process/host crash, reopening the transaction verifies all
bindings and resumes only missing work under the same transaction ID:
completed observations are never rerun, and no nonce, seed, threshold,
budget, pin, operator, or scoring value changes on resume. Corrupted or
incomplete checkpoint state fails closed -- no verdict, no resume.

This module is substrate-agnostic: it knows nothing about mutants,
repositories, or pytest. It journals opaque canonical observation bytes
keyed by mutant ID. All Q3 scientific constants (seeds, budgets,
thresholds, operators, pins, scoring, confirmation semantics) are owned
by the Q3 spec and modules; this layer never redefines them and never
imports the substrate.

Durability contract (what "atomic" means here):
  - every journal entry and every artifact is written to a temp file in
    its final directory, flushed, fsynced, atomically renamed over its
    final name, and then the containing directory is fsynced;
  - a crash at any instant leaves either the complete entry/artifact or
    nothing observable: stale temp files are ignored and cleaned on open;
  - the journal entry is the commit point. An artifact file with no
    journal entry binding it is not committed and is never treated as
    evidence on resume.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Mapping

TX_SCHEMA = "airlock.rsi-006-q4.scientific-transaction.v1"

# Directories treated as ephemeral: durable transaction state must not
# live under any of them.
EPHEMERAL_ROOTS = ("/tmp", "/var/tmp", "/dev/shm")

# Journal entry types.
T_BEGIN = "tx_begin"
T_RESTART = "restart"
T_CONTACT = "contact"
T_OBSERVATION = "observation"
T_OBSERVATION_ADOPTED = "observation_adopted"
T_SEAL = "discovery_seal"
T_NONCE = "nonce"
T_VERDICT = "verdict"

_GENESIS_PREV = "GENESIS"


class TransactionError(RuntimeError):
    """Base class: the transaction cannot proceed safely."""


class CheckpointCorrupt(TransactionError):
    """Journal chain or artifact bindings do not verify. Fail closed."""


class BindingMismatch(TransactionError):
    """Resume-time bindings (receipt, code hashes) drifted. Fail closed."""


class DuplicateWork(TransactionError):
    """An attempt to commit work that is already committed. Rejected."""


class OrphanUnverifiable(TransactionError):
    """Orphan outcome evidence failed verification, so the outcome cannot
    be proven. Adoption is refused and the resume fails closed. Raised
    when the evidence is incomplete, the transaction/observation/binding
    checks fail, the artifact digest does not match, or the execution
    receipt is torn."""


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------

def canonical_bytes(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _valid_tx_nonce(tx_nonce: object) -> bool:
    return (isinstance(tx_nonce, str) and len(tx_nonce) == 64
            and all(c in "0123456789abcdef" for c in tx_nonce))


def derive_txid(receipt_sha256: str, code_hashes: Mapping[str, str],
                tx_nonce: str) -> str:
    """Derive the receiver-owned transaction ID.

    Binds the environment receipt, the Q4 code hashes, and the
    receiver-owned authorization-instance nonce. The nonce is created
    before contact and persisted in tx_begin; resume recovers the same
    value, so the ID is stable across restarts but distinct for every
    fresh authorization -- two transactions with identical receipt/code
    bindings still get different IDs. No clock involved.
    """
    if not _valid_tx_nonce(tx_nonce):
        raise TransactionError(
            "tx_nonce must be a 256-bit hex value (64 lowercase hex chars)")
    h = hashlib.sha256()
    h.update(b"RSI-006-Q4-TX\x00")
    h.update(b"authorization-instance\x00" + tx_nonce.encode("utf-8")
             + b"\x00")
    h.update(receipt_sha256.encode("utf-8") + b"\x00")
    for name in sorted(code_hashes):
        h.update(name.encode("utf-8") + b"\x00"
                 + code_hashes[name].encode("utf-8") + b"\x00")
    return h.hexdigest()


def _fsync_dir(d: Path) -> None:
    fd = os.open(str(d), os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write(path: Path, data: bytes) -> None:
    """Write bytes atomically and durably.

    Temp file in the same directory + fsync + atomic rename + fsync of
    the directory. After this returns, the bytes are on stable storage
    under the final name; a crash before it returns leaves either the
    complete file or nothing (the temp name is never a valid entry).
    """
    path = Path(path)
    tmp = path.parent / f".tmp-{os.getpid()}-{time.time_ns()}"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.rename(tmp, path)
    _fsync_dir(path.parent)


def _work_dir_ok(work_dir: Path) -> Path:
    """Resolve the work dir and refuse ephemeral locations. Fail closed."""
    resolved = Path(work_dir).resolve()
    for root in EPHEMERAL_ROOTS:
        try:
            resolved.relative_to(Path(root).resolve())
        except ValueError:
            continue
        raise TransactionError(
            f"durable transaction state must not live under ephemeral "
            f"{root}: {resolved}")
    return resolved


# --------------------------------------------------------------------------
# transaction
# --------------------------------------------------------------------------

class ScientificTransaction:
    """A durable scientific transaction over a crash-safe work directory.

    Use ``begin`` for a new transaction, ``open`` to resume after a
    process/host crash. ``open`` verifies the journal hash chain, the
    receipt/code bindings, and every committed artifact before returning;
    anything that does not verify raises and the transaction fails
    closed.
    """

    def __init__(self, work_dir: Path, *, txid: str, tx_nonce: str):
        self._work_dir = work_dir
        self._journal_dir = work_dir / "journal"
        self._artifacts_dir = work_dir / "artifacts"
        self._obs_dir = self._artifacts_dir / "observations"
        self._launch_dir = self._artifacts_dir / "launches"
        self._evidence_dir = self._artifacts_dir / "adoption_evidence"
        self._txid = txid
        self._tx_nonce = tx_nonce
        # Rebuilt from the journal on open; appended to on begin.
        self._entries: list[dict] = []
        self._contact: dict | None = None
        self._observations: dict[str, str] = {}   # mutant_id -> digest
        self._obs_phase: dict[str, str] = {}      # mutant_id -> phase
        self._obs_payloads: dict[str, dict] = {}  # mutant_id -> journal payload
        self._seals: dict[str, dict] = {}          # repo -> seal entry payload
        self._nonce: str | None = None
        self._verdict: dict | None = None
        self._restarts = 0
        self._receipt_sha256: str | None = None
        self._code_hashes: dict[str, str] | None = None

    # -- construction ----------------------------------------------------

    @classmethod
    def begin(cls, work_dir: Path | str, *, receipt_sha256: str,
              code_hashes: Mapping[str, str],
              tx_nonce: str) -> "ScientificTransaction":
        """Create a new transaction. The ID is derived before any contact.

        ``tx_nonce`` is the receiver-owned authorization-instance value
        (256-bit hex): fresh per authorization, created before contact,
        bound into the transaction ID and persisted in tx_begin. The
        receiver owns its generation; the layer validates and binds it.
        """
        resolved = _work_dir_ok(work_dir)
        journal_dir = resolved / "journal"
        if journal_dir.exists() and any(journal_dir.iterdir()):
            raise TransactionError(
                f"journal already exists at {journal_dir}: use open() to "
                f"resume, refusing to begin a second transaction here")
        txid = derive_txid(receipt_sha256, dict(code_hashes), tx_nonce)
        tx = cls(resolved, txid=txid, tx_nonce=tx_nonce)
        tx._journal_dir.mkdir(parents=True, exist_ok=True)
        tx._artifacts_dir.mkdir(parents=True, exist_ok=True)
        tx._obs_dir.mkdir(parents=True, exist_ok=True)
        tx._launch_dir.mkdir(parents=True, exist_ok=True)
        tx._evidence_dir.mkdir(parents=True, exist_ok=True)
        tx._clean_tmps()
        tx._append(T_BEGIN, {
            "schema": TX_SCHEMA,
            "txid": tx._txid,
            "tx_nonce": tx_nonce,
            "receipt_sha256": receipt_sha256,
            "code_hashes": dict(code_hashes),
        })
        tx._receipt_sha256 = receipt_sha256
        tx._code_hashes = dict(code_hashes)
        return tx

    @classmethod
    def open(cls, work_dir: Path | str, *, receipt_sha256: str,
             code_hashes: Mapping[str, str]) -> "ScientificTransaction":
        """Resume an existing transaction after a crash.

        Verifies, in order: work-dir durability, journal chain integrity,
        receipt/code bindings, and every committed artifact. The
        authorization-instance nonce is recovered from the verified
        tx_begin entry and the transaction ID re-derived from it, so a
        resumed transaction can only ever continue the authorization it
        began with. Appends a ``restart`` entry only after all
        verification passes. Any failure raises and the transaction
        fails closed: no resume, no verdict.
        """
        resolved = _work_dir_ok(work_dir)
        journal_dir = resolved / "journal"
        if not journal_dir.is_dir():
            raise TransactionError(
                f"no transaction journal at {journal_dir}")
        tx = cls(resolved, txid="", tx_nonce="")
        tx._clean_tmps()
        tx._load_and_verify_chain()
        # Recover the authorization-instance value from the verified
        # tx_begin before the transaction ID can be re-derived.
        tx_nonce = tx._entries[0]["payload"].get("tx_nonce")
        if not _valid_tx_nonce(tx_nonce):
            raise CheckpointCorrupt(
                "tx_begin carries no valid authorization-instance nonce: "
                "cannot re-derive the transaction ID")
        tx._tx_nonce = tx_nonce
        tx._txid = derive_txid(receipt_sha256, dict(code_hashes), tx_nonce)
        tx._verify_bindings(receipt_sha256, dict(code_hashes))
        tx._rebuild_state()
        tx._verify_artifacts()
        tx._append(T_RESTART, {"txid": tx._txid})
        return tx

    # -- journal mechanics ------------------------------------------------

    def _entry_digest(self, seq: int, prev: str, etype: str,
                      payload: dict, ts: float) -> str:
        return sha256_bytes(canonical_bytes({
            "seq": seq, "prev": prev, "type": etype,
            "payload": payload, "ts": ts,
        }))

    def _append(self, etype: str, payload: dict) -> dict:
        seq = len(self._entries) + 1
        prev = self._entries[-1]["digest"] if self._entries else _GENESIS_PREV
        ts = time.time()
        digest = self._entry_digest(seq, prev, etype, payload, ts)
        entry = {"seq": seq, "prev": prev, "type": etype,
                 "payload": payload, "ts": ts, "digest": digest}
        blob = canonical_bytes(entry) + b"\n"
        _atomic_write(self._journal_dir / f"{seq:08d}.json", blob)
        self._entries.append(entry)
        self._apply(entry)
        return entry

    def _clean_tmps(self) -> None:
        for d in (self._journal_dir, self._artifacts_dir,
                  self._obs_dir, self._launch_dir, self._evidence_dir):
            if not d.is_dir():
                continue
            for p in d.iterdir():
                if p.name.startswith(".tmp-"):
                    p.unlink()

    def _load_and_verify_chain(self) -> None:
        files = sorted(self._journal_dir.glob("[0-9]*.json"))
        if not files:
            raise CheckpointCorrupt("journal is empty")
        prev = _GENESIS_PREV
        for i, path in enumerate(files, start=1):
            try:
                entry = json.loads(path.read_bytes())
            except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
                raise CheckpointCorrupt(
                    f"journal entry {path.name} unreadable: {e}")
            for field in ("seq", "prev", "type", "payload", "ts", "digest"):
                if field not in entry:
                    raise CheckpointCorrupt(
                        f"journal entry {path.name} missing field {field}")
            if entry["seq"] != i or entry["prev"] != prev:
                raise CheckpointCorrupt(
                    f"journal chain broken at {path.name}: seq/prev mismatch")
            recomputed = self._entry_digest(
                entry["seq"], entry["prev"], entry["type"],
                entry["payload"], entry["ts"])
            if recomputed != entry["digest"]:
                raise CheckpointCorrupt(
                    f"journal entry {path.name} digest mismatch: tampered?")
            prev = entry["digest"]
            self._entries.append(entry)
        if self._entries[0]["type"] != T_BEGIN:
            raise CheckpointCorrupt("journal does not start with tx_begin")

    def _verify_bindings(self, receipt_sha256: str,
                         code_hashes: dict[str, str]) -> None:
        begin_payload = self._entries[0]["payload"]
        if begin_payload.get("schema") != TX_SCHEMA:
            raise CheckpointCorrupt("tx_begin schema mismatch")
        if begin_payload.get("receipt_sha256") != receipt_sha256:
            raise BindingMismatch(
                "environment receipt binding drifted since tx_begin: "
                "refusing to resume")
        if begin_payload.get("code_hashes") != code_hashes:
            raise BindingMismatch(
                "Q4 code-hash binding drifted since tx_begin: "
                "refusing to resume")
        if not _valid_tx_nonce(begin_payload.get("tx_nonce")):
            raise CheckpointCorrupt(
                "tx_begin authorization-instance nonce invalid")
        if begin_payload.get("tx_nonce") != self._tx_nonce:
            raise CheckpointCorrupt(
                "authorization-instance nonce mismatch on resume")
        if begin_payload.get("txid") != self._txid:
            raise CheckpointCorrupt("txid binding mismatch")
        self._receipt_sha256 = receipt_sha256
        self._code_hashes = code_hashes

    def _apply(self, entry: dict) -> None:
        """Fold one verified entry into in-memory state."""
        p = entry["payload"]
        t = entry["type"]
        if t == T_CONTACT and self._contact is None:
            self._contact = p
        elif t == T_OBSERVATION or t == T_OBSERVATION_ADOPTED:
            self._observations[p["mutant_id"]] = p["digest"]
            self._obs_phase[p["mutant_id"]] = p["phase"]
            self._obs_payloads[p["mutant_id"]] = p
        elif t == T_SEAL:
            self._seals[p["repo"]] = p
        elif t == T_NONCE and self._nonce is None:
            self._nonce = p["nonce"]
        elif t == T_VERDICT and self._verdict is None:
            self._verdict = p
        elif t == T_RESTART:
            self._restarts += 1

    def _rebuild_state(self) -> None:
        for entry in self._entries:
            self._apply(entry)

    def _verify_artifacts(self) -> None:
        for mid, payload in self._obs_payloads.items():
            digest = payload["digest"]
            path = self._obs_dir / f"{mid}.json"
            try:
                blob = path.read_bytes()
            except OSError:
                raise CheckpointCorrupt(
                    f"committed observation {mid} artifact missing")
            if sha256_bytes(blob) != digest:
                raise CheckpointCorrupt(
                    f"committed observation {mid} artifact digest mismatch")
            # Launch/provenance sidecar: the journaled launch digest must
            # match the persisted sidecar on every resume, for ordinary
            # and adopted observations alike.
            launch_path = self._launch_dir / f"{mid}.json"
            try:
                launch_blob = launch_path.read_bytes()
            except OSError:
                raise CheckpointCorrupt(
                    f"committed observation {mid} launch sidecar missing")
            if sha256_bytes(launch_blob) != payload.get("launch_digest"):
                raise CheckpointCorrupt(
                    f"committed observation {mid} launch sidecar digest "
                    f"mismatch")
            # Adopted observations additionally bind the exact
            # orphan-evidence record relied upon at adoption time.
            if "evidence_digest" in payload:
                ev_path = self._evidence_dir / f"{mid}.json"
                try:
                    ev_blob = ev_path.read_bytes()
                except OSError:
                    raise CheckpointCorrupt(
                        f"adopted observation {mid} evidence artifact "
                        f"missing")
                if sha256_bytes(ev_blob) != payload["evidence_digest"]:
                    raise CheckpointCorrupt(
                        f"adopted observation {mid} evidence artifact "
                        f"digest mismatch")
        if self._verdict is not None:
            path = self._artifacts_dir / "report.json"
            try:
                blob = path.read_bytes()
            except OSError:
                raise CheckpointCorrupt("committed verdict report missing")
            if sha256_bytes(blob) != self._verdict["report_digest"]:
                raise CheckpointCorrupt("committed verdict report digest "
                                        "mismatch")
        # A report file with no verdict journal entry is NOT committed
        # (crash between artifact write and journal append): it is ignored
        # here and the driver recomputes the verdict deterministically.

    # -- read-only state --------------------------------------------------

    @property
    def txid(self) -> str:
        return self._txid

    @property
    def tx_nonce(self) -> str:
        """The receiver-owned authorization-instance value for this tx."""
        return self._tx_nonce

    @property
    def work_dir(self) -> Path:
        return self._work_dir

    @property
    def contact_event(self) -> dict | None:
        return dict(self._contact) if self._contact else None

    @property
    def observations(self) -> dict[str, str]:
        return dict(self._observations)

    @property
    def seals(self) -> dict[str, dict]:
        return {k: dict(v) for k, v in self._seals.items()}

    @property
    def nonce(self) -> str | None:
        return self._nonce

    @property
    def verdict(self) -> dict | None:
        return dict(self._verdict) if self._verdict else None

    @property
    def restart_count(self) -> int:
        return self._restarts

    @property
    def journal_length(self) -> int:
        return len(self._entries)

    def pending(self, planned_ids: list[str]) -> list[str]:
        """IDs from the plan with no committed observation. Never reruns."""
        return [mid for mid in planned_ids if mid not in self._observations]

    def results_digest(self) -> str:
        """Canonical digest over committed observations (order-independent)."""
        body = "|".join(f"{mid}:{self._observations[mid]}"
                        for mid in sorted(self._observations))
        return sha256_bytes(body.encode("utf-8"))

    # -- mutating operations (each one atomic + durable) -------------------

    def note_contact(self, *, mutant_id: str, child_pid: int) -> dict:
        """Record the single contact event, exactly once.

        The first call appends the contact entry durably and returns
        ``{"created": True, ...}``. Every later call -- including after a
        process/host restart -- is a no-op returning the original event
        with ``{"created": False, ...}``. The event survives restart
        because it lives in the journal, not in process memory.
        """
        if self._contact is not None:
            return {"created": False, "event": dict(self._contact)}
        entry = self._append(T_CONTACT, {
            "schema": "airlock.rsi-006-q4.scientific-contact.v1",
            "event": "scientific_contact",
            "txid": self._txid,
            "mutant_id": mutant_id,
            "receipt_sha256": self._receipt_sha256,
            "child_pid": child_pid,
        })
        return {"created": True, "event": dict(entry["payload"])}

    def commit_observation(self, *, mutant_id: str, phase: str,
                           canonical: bytes, launch: dict,
                           _crash_hook=None) -> str:
        """Durably commit one completed observation, by ID and digest.

        The canonical artifact is written atomically before the journal
        entry that binds its digest; the entry is the commit point.
        Re-committing an already-committed ID is rejected: completed
        observations are never rerun.

        ``_crash_hook`` is a test-only injection point invoked after the
        outcome artifact is durably renamed but before the journal entry
        binding its digest is appended. It is how the crash-injection
        fixtures exercise the commit gap. It must be None in real use.
        """
        if mutant_id in self._observations:
            raise DuplicateWork(
                f"observation {mutant_id} already committed: refusing "
                f"duplicate work")
        digest = sha256_bytes(canonical)
        launch_blob = canonical_bytes({
            **launch, "mutant_id": mutant_id, "phase": phase,
            "observation_digest": digest,
        })
        _atomic_write(self._obs_dir / f"{mutant_id}.json", canonical)
        if _crash_hook is not None:
            _crash_hook()
        _atomic_write(self._launch_dir / f"{mutant_id}.json",
                      launch_blob + b"\n")
        self._append(T_OBSERVATION, {
            "mutant_id": mutant_id,
            "phase": phase,
            "digest": digest,
            "launch_digest": sha256_bytes(launch_blob + b"\n"),
        })
        return digest

    def adopt_orphan_observation(self, *, mutant_id: str, phase: str,
                                 outcome_bytes: bytes,
                                 evidence: dict) -> str:
        """Adopt a durable orphan outcome left by a crashed execution or
        a crashed commit, without re-executing the observation.

        Two crash windows leave a completed outcome outside the journal:
        the process dies after the observation physically executes but
        before ``commit_observation`` runs (execution gap), or it dies
        inside ``commit_observation`` after the outcome artifact is
        renamed but before the journal entry binding its digest is
        appended (commit gap). Re-executing is not an option: for
        non-recomputable work a rerun is a second execution, not a retry.

        Adoption is allowed in exactly one way: the caller supplies the
        outcome bytes together with independently durable,
        transaction-bound evidence, and every check below passes. If any
        check fails, ``OrphanUnverifiable`` is raised and the resume
        fails closed -- the outcome cannot be proven, so it must not be
        silently re-derived.

        Verified before acceptance, in order:
          1. evidence is a complete record (all required fields present);
          2. evidence transaction ID equals this transaction's ID;
          3. evidence observation ID equals ``mutant_id`` and evidence
             phase equals ``phase``;
          4. evidence receipt and code-hash bindings equal this
             transaction's bindings (no drift across the crash);
          5. ``sha256(outcome_bytes)`` equals the outcome digest recorded
             in the evidence.

        The adopted observation is journaled as ``observation_adopted``
        (distinct from a fresh ``observation`` entry, so provenance is
        auditable), counts as committed for ``pending()`` /
        ``results_digest()``. The exact evidence record relied upon is
        persisted under ``artifacts/adoption_evidence/`` with its digest
        bound in the journal entry, and the adopted launch sidecar digest
        is bound too; outcome, launch, and evidence artifacts are all
        re-verified on every later resume. Adopting an already-committed
        ID is rejected as duplicate work.
        """
        if mutant_id in self._observations:
            raise DuplicateWork(
                f"observation {mutant_id} already committed: refusing "
                f"duplicate work")
        if not isinstance(evidence, dict):
            raise OrphanUnverifiable("orphan evidence is not a record")
        required = ("txid", "observation_id", "phase", "outcome_digest",
                    "receipt_sha256", "code_hashes")
        missing = [k for k in required if k not in evidence]
        if missing:
            raise OrphanUnverifiable(
                f"orphan evidence incomplete; missing fields: {missing}")
        if evidence["txid"] != self._txid:
            raise OrphanUnverifiable(
                "orphan evidence transaction ID does not match: refusing "
                "to adopt an outcome from another transaction")
        if evidence["observation_id"] != mutant_id:
            raise OrphanUnverifiable(
                "orphan evidence observation ID mismatch")
        if evidence["phase"] != phase:
            raise OrphanUnverifiable("orphan evidence phase mismatch")
        if evidence["receipt_sha256"] != self._receipt_sha256:
            raise OrphanUnverifiable(
                "orphan evidence receipt binding drifted: refusing adoption")
        if evidence["code_hashes"] != self._code_hashes:
            raise OrphanUnverifiable(
                "orphan evidence code-hash binding drifted: refusing "
                "adoption")
        digest = sha256_bytes(outcome_bytes)
        if digest != evidence["outcome_digest"]:
            raise OrphanUnverifiable(
                "orphan outcome artifact digest does not match the "
                "independently recorded digest: refusing adoption")
        launch = evidence.get("launch", {})
        if not isinstance(launch, dict):
            raise OrphanUnverifiable("orphan evidence launch is not a record")
        _atomic_write(self._obs_dir / f"{mutant_id}.json", outcome_bytes)
        # Persist the exact evidence record relied upon, as a
        # restart-verifiable artifact. evidence_digest in the journal
        # entry below binds it on every open().
        _atomic_write(self._evidence_dir / f"{mutant_id}.json",
                      canonical_bytes(evidence))
        launch_blob = canonical_bytes({
            **launch, "mutant_id": mutant_id, "phase": phase,
            "observation_digest": digest, "adopted": True,
        })
        launch_digest = sha256_bytes(launch_blob + b"\n")
        _atomic_write(self._launch_dir / f"{mutant_id}.json",
                      launch_blob + b"\n")
        self._append(T_OBSERVATION_ADOPTED, {
            "mutant_id": mutant_id,
            "phase": phase,
            "digest": digest,
            "launch_digest": launch_digest,
            "adopted_from": "orphan_evidence",
            "evidence_digest": sha256_bytes(canonical_bytes(evidence)),
        })
        return digest

    def commit_discovery_seal(self, *, repo: str, seal: str,
                              member_ids: list[str]) -> None:
        """Commit a discovery seal only after every member record is durable.

        The seal binds the ordered member digests; advancing past
        discovery requires every repo's seal committed first (the driver
        enforces the order; the journal is the evidence).
        """
        if repo in self._seals:
            raise DuplicateWork(
                f"discovery seal for {repo} already committed")
        missing = [m for m in member_ids if m not in self._observations]
        if missing:
            raise TransactionError(
                f"cannot seal {repo}: {len(missing)} member observations "
                f"not yet committed")
        members = [{"mutant_id": m, "digest": self._observations[m]}
                   for m in sorted(member_ids)]
        self._append(T_SEAL, {"repo": repo, "seal": seal, "members": members})

    def commit_nonce(self, *, nonce_hex: str) -> None:
        """Durably commit the confirmation nonce before any confirmation
        mutant is generated or dispatched. Exactly once per transaction:
        a resume reuses the committed nonce, never a new one."""
        if self._nonce is not None:
            raise DuplicateWork("confirmation nonce already committed: "
                                "refusing a second nonce")
        if len(nonce_hex) != 64 or any(
                c not in "0123456789abcdef" for c in nonce_hex):
            raise TransactionError("nonce must be 32 bytes hex")
        self._append(T_NONCE, {"nonce": nonce_hex})

    def commit_verdict(self, *, verdict: str, report: dict,
                       _crash_hook=None) -> None:
        """Commit the final verdict and report atomically.

        The report is written atomically first; the journal entry binding
        its digest is the commit point. A crash between the two leaves a
        report file with no entry, which ``open`` ignores: the driver
        recomputes the verdict deterministically and commits again.
        ``_crash_hook`` is test instrumentation only (crash-injection
        fixtures); it is never used by real drivers.
        """
        if self._verdict is not None:
            raise DuplicateWork("verdict already committed")
        blob = canonical_bytes({"txid": self._txid, "verdict": verdict,
                                "report": report})
        _atomic_write(self._artifacts_dir / "report.json", blob + b"\n")
        if _crash_hook is not None:
            _crash_hook()
        self._append(T_VERDICT, {
            "verdict": verdict,
            "report_digest": sha256_bytes(blob + b"\n"),
        })
