"""RSI-006-Q5 Stage 2 scientific runner (pre-contact mechanism).

Runs the Q5 substrate-qualification science end to end: frozen Q3
mutant generation, frozen Q3 pytest observation boundaries, exact Q3
canonical records committed through Q4's durable transaction, Q3
discovery seals, the confirmation nonce, determinism reruns, and the
pure Q3-derived verdict -- all under Q5's receiver-owned execution
ledger, ContactGate, coordinator lock, and crash/resume semantics.

This module is the INTENTIONALLY SCIENTIFIC part of Q5. Unlike
``q5_adapter.py`` / ``execution_ledger.py`` (which stay substrate-free
and never import the mutation substrate), the runner imports Q3's
frozen ``observe`` / ``perturb`` / ``run_rsi_006_q3`` helpers read-only
and uses them directly -- no copies, no reimplementation, no indirect
import tricks. Q3, Q4, and ``proofs/`` are never modified. The Q5
self-check allowlists exactly these imports on this file (and on the
runner's fixture tests) and keeps forbidding them everywhere else.

Pre-contact status: building, testing, and reviewing this file performs
no scientific contact. Contact happens only when the runner is
explicitly invoked against a verified production environment receipt,
which requires Terrynce's authorization. Presence in the manifest is
not authorization.

Execution order (contact never moves):

  prepared -> Popen -> started -> ContactGate -> completion/timeout ->
  canonical bytes durable -> completion durable -> reconcile contact ->
  Q4 commit/adopt

Workers never mutate Q4; there is no second mutation/execution path.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

EXP_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXP_DIR.parent.parent
Q3_DIR = REPO_ROOT / "experiments" / "rsi-006-q3-substrate-qualification"
Q4_DIR = REPO_ROOT / "experiments" / "rsi-006-q4-durable-transaction"
for _d in (str(EXP_DIR), str(Q4_DIR), str(Q3_DIR)):
    if _d not in sys.path:
        sys.path.insert(0, _d)

import q5_adapter as qa
from contact import ContactGate
import stransaction as st
import environment_receipt as q5_receipt

# Frozen Q3 semantics, imported read-only. The runner reuses them
# directly; the Q5 self-check names exactly these modules as the
# runner's explicit scientific imports.
import observe as q3_observe
import perturb as q3_perturb
import run_rsi_006_q3 as q3_run
import pool_config as q3_pool

# The production wait ceiling is Q3's frozen RUN_TIMEOUT_S -- not the
# adapter's fixture default. Fail fast at import if Q3 ever changed it.
assert q3_observe.RUN_TIMEOUT_S == 120, \
    "frozen Q3 RUN_TIMEOUT_S changed; runner refuses to import"
WAIT_TIMEOUT_S = q3_observe.RUN_TIMEOUT_S

REPORT_SCHEMA = "airlock.rsi-006-q5.report.v1"
CONTACT_MARKER = "scientific-contact.json"
PRECONTACT_OUTCOME = "INCONCLUSIVE_RSI_006_Q5_PRECONDITION_FAILURE"
VERDICT_QUALIFIED = "QUALIFIED_RSI_006_Q5_SUBSTRATE"
VERDICT_NOT_QUALIFIED = "NOT_QUALIFIED_RSI_006_Q5_SUBSTRATE"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _code_hashes() -> dict:
    """Receipt execution-surface code hashes (same set as the fixtures)."""
    return {
        "stransaction.py": _sha256_file(Q4_DIR / "stransaction.py"),
        "execution_ledger.py": _sha256_file(EXP_DIR / "execution_ledger.py"),
        "q5_adapter.py": _sha256_file(EXP_DIR / "q5_adapter.py"),
    }


def kill_from_baseline(baseline: dict, outcomes: dict) -> bool:
    """Q3's kill classification, verbatim (observe.observe_mutant).

    True when any baseline outcome differs (a missing baseline test
    counts as a difference) or when the outcomes contain any test ID
    absent from the baseline. Kept as a named function so the parity
    tests can check it against Q3's frozen source directly.
    """
    kill = False
    for test_id, base_outcome in baseline.items():
        if outcomes.get(test_id, "<missing>") != base_outcome:
            kill = True
            break
    else:
        # Any test not in the baseline also counts as a behavior change.
        if set(outcomes) - set(baseline):
            kill = True
    return kill


def build_q3_completion(*, repo_name: str, mutant: dict, baseline: dict,
                        argv: list, python: str, run_dir: Path,
                        env: dict, env_overrides: dict, junit_path: Path,
                        evidence: dict) -> tuple[bytes, dict]:
    """Build exact Q3 canonical bytes + Q3 launch sidecar from evidence.

    This is the adapter's ``completion_builder``: it is invoked per
    completed observation process (including a timed-out child, which
    Q3 treats as a completed scientific observation) with the adapter's
    completed-process evidence. Scoring semantics are Q3's
    ``run_suite_once`` / ``observe_mutant``, reused directly:

    - timeout -> outcomes={}, kill=True, collection_error=False,
      timeout=True, disposition "timeout", exit_status None;
    - missing JUnit -> collection error, disposition
      "collection_error_no_junitxml";
    - unparseable JUnit -> collection error with the raw JUnit
      preserved, disposition "collection_error_unparseable_junitxml";
    - otherwise the parsed outcomes with Q3's kill classification.

    The launch sidecar is built by Q3's own frozen ``_launch_record``,
    so it is byte-shape-identical to a Q3 launch record.
    """
    timeout = bool(evidence["timeout"])
    junit_bytes: bytes | None = None
    disposition = "ok"
    outcomes: dict = {}
    collection_error = False
    if timeout:
        disposition = "timeout"
    else:
        if junit_path.is_file():
            junit_bytes = junit_path.read_bytes()
        if junit_bytes is None:
            disposition = "collection_error_no_junitxml"
            collection_error = True
        else:
            try:
                outcomes = q3_observe.parse_junitxml_bytes(junit_bytes)
            except ET.ParseError:
                disposition = "collection_error_unparseable_junitxml"
                collection_error = True
    kill = bool(collection_error or timeout)
    if not kill:
        kill = kill_from_baseline(baseline, outcomes)
    record = {
        "repo": repo_name,
        "mutant_id": mutant["mutant_id"],
        "operator": mutant["operator"],
        "site_key": mutant["site_key"],
        "seed": mutant["seed"],
        "outcomes": outcomes,
        "kill": kill,
        "collection_error": collection_error,
        "timeout": timeout,
    }
    outcome_bytes = q3_run.canonical_bytes(record)
    launch = q3_observe._launch_record(
        list(argv), python, Path(run_dir), dict(env), dict(env_overrides),
        evidence["started_utc"], evidence["ended_utc"],
        evidence["exit_status"], evidence["stdout"], evidence["stderr"],
        junit_bytes, disposition, child_pid=evidence["child_pid"])
    return outcome_bytes, launch


class _PreconditionFailure(Exception):
    """The static feasibility guard failed: pre-contact, no verdict.

    Carries the complete guard report so the pre-contact outcome can
    name exactly which repos failed without re-running the guard.
    """

    def __init__(self, message: str, guard_report: dict):
        super().__init__(message)
        self.guard_report = guard_report


def _production_confirmation_nonce_source() -> str:
    """Production confirmation-nonce source: 32 bytes of OS entropy.

    The single production source for the confirmation nonce. Fixture
    harnesses may inject a deterministic source through the
    ``confirmation_nonce_source`` constructor parameter (internal,
    test-only); there is no CLI flag and production never overrides it.
    """
    return os.urandom(32).hex()


class Stage2Runner:
    """The Q5 Stage 2 qualification core, parameterized for tests.

    Production ``main()`` binds the frozen production values (Q3 pool,
    Q3 budgets/seeds/thresholds, verified receipt bindings); the
    fixture harness binds a tiny local pool with small budgets. The
    code path is identical.
    """

    def __init__(self, *, stage2_dir: Path | str,
                 pool: dict[str, dict], pool_dir: Path | str,
                 budgets: dict[str, tuple], python: str,
                 receipt_path: Path | str, workers: int,
                 code_hashes: dict,
                 receipt_verifier=None,
                 wait_timeout_s: float = WAIT_TIMEOUT_S,
                 confirmation_nonce_source=None):
        self._stage2_dir = Path(stage2_dir)
        self._pool = pool
        self._pool_dir = Path(pool_dir)
        self._repo_names = list(pool.keys())
        self._budgets = budgets
        self._python = python
        self._receipt_path = Path(receipt_path)
        self._workers = workers
        self._code_hashes = code_hashes
        self._wait_timeout_s = wait_timeout_s
        # Internal, test-only injection point for the confirmation-nonce
        # source. Production always uses OS entropy (see
        # _production_confirmation_nonce_source); the fixture harness
        # passes a deterministic source so the crash/resume oracle can
        # compare runs under identical confirmation randomness. There is
        # no CLI flag and no production override path.
        self._confirmation_nonce_source = (
            confirmation_nonce_source or
            _production_confirmation_nonce_source)
        # The production verifier is the frozen receipt path; fixture
        # harnesses inject a stub returning the same (receipt, sha)
        # pair. The verifier performs NO baseline execution, NO test
        # runs, and NO mutation -- it re-probes and compares.
        self._receipt_verifier = (
            receipt_verifier or self._default_receipt_verifier)
        self._receipt: dict | None = None
        self._receipt_sha256: str | None = None
        self._baselines: dict[str, dict] = {}
        self._tree_hash_pre: dict[str, str] = {}
        self._tx = None
        self._prep: dict[str, dict] = {}
        self._mutants: dict[str, dict] = {}
        missing = [n for n in self._repo_names if n not in budgets]
        if missing:
            raise ValueError(f"budgets missing repos: {missing}")

    def _default_receipt_verifier(self) -> tuple[dict, str]:
        """Production verification: the frozen environment receipt."""
        received = q5_receipt.verify_production_receipt(
            self._receipt_path, pool_dir=self._pool_dir,
            python=self._python, stage2_work_dir=self._stage2_dir)
        return received, q5_receipt.receipt_sha256(self._receipt_path)

    def _verify_and_bind_receipt(self) -> None:
        """verify_production_receipt() before any scientific work."""
        received, sha = self._receipt_verifier()
        self._receipt = received
        self._receipt_sha256 = sha
        for name in self._repo_names:
            self._baselines[name] = received["baseline_vectors"][name]
            self._tree_hash_pre[name] = received["repos"][name]["tree_hash"]

    def _reverify_receipt(self) -> None:
        """Re-read and re-verify; post-contact drift stops, no verdict."""
        received, sha = self._receipt_verifier()
        if sha != self._receipt_sha256:
            raise st.TransactionError(
                "post-contact environment drift: receipt binding changed "
                f"{(self._receipt_sha256 or '')[:16]}... -> "
                f"{sha[:16]}...; no verdict, no rescue")

    # ------------------------------------------------------------------
    # static pre-contact guard
    # ------------------------------------------------------------------

    def _guard(self) -> dict:
        """Frozen Q3 static feasibility guard. No test execution."""
        guard_report = {}
        failures = []
        for name in self._repo_names:
            da_n, db_n, _, _ = self._budgets[name]
            assert da_n == db_n, f"{name}: halves must share one budget"
            result = q3_run.feasibility_guard(
                Path(self._pool[name]["package_dir"]), da_n)
            guard_report[name] = result
            if not result["passed"]:
                failures.append(
                    f"{name}: feasibility guard failed: only "
                    f"{len(result['qualifying_operators'])} operators reach "
                    f"10/half (< 3); Q-STAB unreachable before any test "
                    f"execution")
        if failures:
            raise _PreconditionFailure("; ".join(failures), guard_report)
        return guard_report

    def _write_precontact_outcome(self, exc: _PreconditionFailure) -> dict:
        """Narrowly named pre-contact outcome: no tx, no nonce, no contact."""
        self._stage2_dir.mkdir(parents=True, exist_ok=True)
        body = {
            "schema": REPORT_SCHEMA,
            "experiment": "RSI-006-Q5 substrate qualification",
            "stage": "pre-contact",
            "outcome": PRECONTACT_OUTCOME,
            "environment_receipt_sha256": self._receipt_sha256,
            "feasibility_guard": exc.guard_report,
            "precondition_failures": [str(exc)],
        }
        blob = (json.dumps(body, sort_keys=True, indent=1) + "\n") \
            .encode("utf-8")
        path = self._stage2_dir / "precontact-report.json"
        tmp = path.with_name(".tmp-precontact-report.json")
        tmp.write_bytes(blob)
        os.replace(tmp, path)
        return {"status": "precontact", "outcome": PRECONTACT_OUTCOME,
                "report_path": str(path)}
    # ------------------------------------------------------------------
    # transaction lifecycle
    # ------------------------------------------------------------------

    def _begin_or_open(self) -> bool:
        """Begin fresh, or open EXACTLY ONCE when resuming.

        Returns True when an existing journal was opened (a genuine
        resume). ``open()`` is never used as a refresh: it is called at
        most once per process lifetime, here.
        """
        journal_dir = self._stage2_dir / "journal"
        if journal_dir.is_dir() and any(journal_dir.iterdir()):
            self._tx = st.ScientificTransaction.open(
                self._stage2_dir, receipt_sha256=self._receipt_sha256,
                code_hashes=self._code_hashes)
            return True
        tx_nonce = os.urandom(32).hex()  # 256-bit, fresh per begin
        self._tx = st.ScientificTransaction.begin(
            self._stage2_dir, receipt_sha256=self._receipt_sha256,
            code_hashes=self._code_hashes, tx_nonce=tx_nonce)
        return False

    # ------------------------------------------------------------------
    # observation preparation: overlays before spawn, frozen Q3 boundary
    # ------------------------------------------------------------------

    @staticmethod
    def _obs_id(phase: str, mutant: dict) -> str:
        # Det-rerun transaction IDs stay distinct from the original
        # discovery IDs so Q4 duplicate protection remains true; the
        # canonical record keeps the original mutant metadata. The
        # ledger's ID charset forbids ":", so the separator is "-".
        if phase == "det-rerun":
            return f"det-rerun-{mutant['mutant_id']}"
        return mutant["mutant_id"]

    def _generate_discovery_mutants(self) -> None:
        """Deterministic generation: safe to re-run on resume."""
        for name in self._repo_names:
            cfg = self._pool[name]
            da_n, db_n, det_n, conf_n = self._budgets[name]
            assert da_n == db_n, f"{name}: halves must share one budget"
            pkg = Path(cfg["package_dir"])
            self._mutants[name] = {
                "A": q3_perturb.generate_mutants(pkg, q3_run.SEED_A, da_n,
                                                f"{name}-A"),
                "B": q3_perturb.generate_mutants(pkg, q3_run.SEED_B, db_n,
                                                f"{name}-B"),
                "det_n": det_n, "conf_n": conf_n,
            }

    def _prepare_observation(self, repo_name: str, mutant: dict,
                             phase: str) -> None:
        """Prepare one observation's overlay + pytest boundary, pre-spawn.

        Mirrors Q3 ``observe_mutant``'s prep: copy the package to an
        overlay, apply the mutant with the frozen ``perturb``
        generator (the pinned repo is never mutated), and construct the
        exact Q3 pytest argv/env/cwd. The adapter's ``Popen`` becomes
        the actual pytest process.
        """
        tx_obs_id = self._obs_id(phase, mutant)
        safe = tx_obs_id.replace(":", "_").replace("/", "_")
        cfg = self._pool[repo_name]
        package_dir = Path(cfg["package_dir"])
        prep_root = self._stage2_dir / "prep" / phase
        overlay_root = prep_root / f"ov-{safe}"
        run_dir = prep_root / f"run-{safe}"
        shutil.rmtree(overlay_root, ignore_errors=True)
        shutil.rmtree(run_dir, ignore_errors=True)
        overlay_pkg = overlay_root / package_dir.name
        shutil.copytree(package_dir, overlay_pkg)
        q3_perturb.apply_mutant(package_dir, mutant, overlay_pkg)
        run_dir.mkdir(parents=True)
        junit_path = run_dir / "results.xml"
        repo_root = Path(cfg["repo_root"])
        # Byte-identical to Q3 run_suite_once's argv construction.
        argv = [self._python, "-m", "pytest", "-q", "-p",
                "no:cacheprovider", "--tb=no",
                f"--junitxml={junit_path}", "--rootdir", str(repo_root),
                str(Path(cfg["tests_dir"]))]
        env = dict(os.environ)
        env_overrides = {"PYTHONDONTWRITEBYTECODE": "1",
                         "PYTHONPATH": str(overlay_root)}
        env.update(env_overrides)
        self._prep[tx_obs_id] = {
            "repo_name": repo_name, "mutant": mutant,
            "baseline": self._baselines[repo_name],
            "run_dir": run_dir, "junit_path": junit_path,
            "python": self._python, "argv": argv, "env": env,
            "env_overrides": env_overrides,
            "overlay_root": overlay_root,
        }

    def _cleanup_prep(self, tx_obs_id: str) -> None:
        prep = self._prep.pop(tx_obs_id, None)
        if prep is None:
            return
        shutil.rmtree(prep["overlay_root"], ignore_errors=True)
        shutil.rmtree(prep["run_dir"], ignore_errors=True)

    def _spawn_for(self, observation_id: str):
        prep = self._prep[observation_id]

        def spawn(exec_nonce: str):
            return subprocess.Popen(
                prep["argv"], cwd=str(prep["run_dir"]), env=prep["env"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        return spawn

    def _builder(self, observation_id: str,
                 evidence: dict) -> tuple[bytes, dict]:
        prep = self._prep[observation_id]
        return build_q3_completion(
            repo_name=prep["repo_name"], mutant=prep["mutant"],
            baseline=prep["baseline"], argv=prep["argv"],
            python=prep["python"], run_dir=prep["run_dir"], env=prep["env"],
            env_overrides=prep["env_overrides"],
            junit_path=prep["junit_path"], evidence=evidence)

    def _run_phase(self, coord: qa.Coordinator,
                   items: list[tuple[str, dict]], phase: str,
                   crash_points: dict | None = None) -> list:
        """Prepare pending observations, run them, journal serially."""
        wanted = [self._obs_id(phase, m) for _, m in items]
        pending = set(self._tx.pending(wanted))
        work = [(r, m) for r, m in items
                if self._obs_id(phase, m) in pending]
        for repo_name, mutant in work:
            self._prepare_observation(repo_name, mutant, phase)
        observations = [(self._obs_id(phase, m), phase) for _, m in work]
        if not observations:
            return []

        def _unreachable(exec_nonce: str):  # pragma: no cover
            raise AssertionError("spawn_for covers all observations")

        applied = coord.run_all(
            observations=observations, spawn=_unreachable,
            spawn_for=self._spawn_for,
            argv_for=lambda obs_id: self._prep[obs_id]["argv"],
            completion_builder=self._builder,
            crash_points=crash_points or {},
            max_workers=self._workers)
        for row in applied:
            if row["status"] in ("committed", "adopted",
                                 "skipped_committed"):
                self._cleanup_prep(row["observation_id"])
        return applied
    # ------------------------------------------------------------------
    # phases
    # ------------------------------------------------------------------

    def _discovery(self, coord: qa.Coordinator,
                   crash_points: dict | None = None) -> None:
        """Frozen seeds/budgets; pending IDs only."""
        items = [(name, m) for name in self._repo_names
                 for m in self._mutants[name]["A"] + self._mutants[name]["B"]]
        crash = dict(crash_points or {})
        adapter_crash: dict = {}
        if crash.pop("after_first_contact", False) and items:
            # Crash after the first observation's completion is durable
            # -- contact genuinely occurred during it. Resume adopts
            # the exact first outcome; nothing re-executes.
            first_id = self._obs_id("discovery", items[0][1])
            adapter_crash[first_id] = "after_completion"
        if crash.pop("partial_discovery", False) and items:
            # Crash after a mid-discovery observation's completion is
            # durable. Resume adopts the completed members and runs the
            # rest; nothing completed re-executes.
            mid_id = self._obs_id("discovery", items[len(items) // 2][1])
            adapter_crash[mid_id] = "after_completion"
        for key, window in crash.items():
            if not key.startswith("after_"):
                adapter_crash[key] = window
        self._run_phase(coord, items, "discovery", adapter_crash)

    def _load_record(self, tx_obs_id: str) -> dict:
        """Reconstruct a Q3 record from its verified Q4 artifact.

        The artifact bytes are hash-checked against the journal-bound
        digest: a torn or tampered artifact fails closed here, never
        silently.
        """
        path = (self._stage2_dir / "artifacts" / "observations"
                / f"{tx_obs_id}.json")
        blob = path.read_bytes()
        digest = hashlib.sha256(blob).hexdigest()
        committed = self._tx.observations.get(tx_obs_id)
        if committed != digest:
            raise st.TransactionError(
                f"observation artifact {tx_obs_id} failed verification: "
                f"artifact sha256 {digest} != journal-bound {committed}")
        return json.loads(blob)

    def _seals(self, _crash_hook=None) -> None:
        """Exact Q3 discovery seals, committed after all members."""
        for name in self._repo_names:
            muts = self._mutants[name]
            a_ids = sorted(m["mutant_id"] for m in muts["A"])
            b_ids = sorted(m["mutant_id"] for m in muts["B"])
            member_ids = a_ids + b_ids
            records = [self._load_record(mid) for mid in member_ids]
            seal = hashlib.sha256(
                q3_run.discovery_seal_input(records)).hexdigest()
            existing = self._tx.seals.get(name)
            if existing is not None:
                # An existing seal must recompute identically; a
                # mismatch is journal/artifact divergence: fail closed.
                if existing["seal"] != seal:
                    raise st.TransactionError(
                        f"{name}: discovery seal recompute mismatch: "
                        f"journal {existing['seal']} != recomputed {seal}")
            else:
                self._tx.commit_discovery_seal(
                    repo=name, seal=seal, member_ids=member_ids)
            if _crash_hook is not None:
                _crash_hook(f"after_seal:{name}")

    def _confirmation_nonce(self, _crash_hook=None) -> str:
        """The confirmation nonce: committed once, reused on resume.

        Generated (via the confirmation-nonce source -- 32 bytes of OS
        entropy in production) only after every discovery seal is
        committed, and before any confirmation mutant is generated --
        the seed stays ``RSI-006-Q3-confirmation-{nonce}``.
        """
        nonce = self._tx.nonce
        if nonce is None:
            nonce = self._confirmation_nonce_source()
            self._tx.commit_nonce(nonce_hex=nonce)
            if _crash_hook is not None:
                _crash_hook("after_nonce")
        return nonce

    def _generate_confirmation_mutants(self, nonce: str) -> None:
        """Deterministic in the nonce: safe to re-run on resume."""
        for name in self._repo_names:
            cfg = self._pool[name]
            conf_n = self._mutants[name]["conf_n"]
            pkg = Path(cfg["package_dir"])
            self._mutants[name]["C"] = q3_perturb.generate_mutants(
                pkg, f"RSI-006-Q3-confirmation-{nonce}", conf_n,
                f"{name}-C")

    def _confirmation(self, coord: qa.Coordinator, nonce: str,
                      crash_points: dict | None = None) -> None:
        """Frozen confirmation budgets; pending IDs only."""
        self._generate_confirmation_mutants(nonce)
        items = [(name, m) for name in self._repo_names
                 for m in self._mutants[name]["C"]]
        crash = dict(crash_points or {})
        adapter_crash: dict = {}
        if crash.pop("mid_confirmation", False) and items:
            # Crash after a mid-phase confirmation observation's
            # completion is durable. Resume adopts it; earlier members
            # are committed (skipped), later members run fresh.
            mid_id = self._obs_id("confirmation", items[len(items) // 2][1])
            adapter_crash[mid_id] = "after_completion"
        for key, window in crash.items():
            if not key.startswith("after_"):
                adapter_crash[key] = window
        self._run_phase(coord, items, "confirmation", adapter_crash)

    def _det_reruns(self, coord: qa.Coordinator,
                    crash_points: dict | None = None) -> None:
        """First det_n discovery-A mutants, rerun for determinism."""
        items = []
        for name in self._repo_names:
            det_n = self._mutants[name]["det_n"]
            items += [(name, m)
                      for m in self._mutants[name]["A"][:det_n]]
        adapter_crash = {k: v for k, v in dict(crash_points or {}).items()
                         if not k.startswith("after_")}
        self._run_phase(coord, items, "det-rerun", adapter_crash)
    # ------------------------------------------------------------------
    # evaluation and verdict (pure Q3)
    # ------------------------------------------------------------------

    def _evaluate(self) -> dict:
        """Q3 metrics + repository-integrity evaluation, unchanged.

        Mirrors Q3 ``qualify_science`` step 6 exactly: the metric
        functions (``kill_rate``, ``op_kill_rates``, ``spearman``), the
        frozen ``THRESH`` thresholds, the canonical-byte determinism
        comparison, and the Q-INTACT tree-hash check are Q3's own. Every
        input is a committed Q4 observation record: no re-execution,
        no recompute of pytest.
        """
        THRESH = q3_run.THRESH
        causes: list[str] = []
        repos: dict[str, dict] = {}
        for name in self._repo_names:
            entry: dict = {"tree_hash_pre": self._tree_hash_pre[name]}
            mutants = self._mutants[name]
            disc_ids = sorted(m["mutant_id"]
                              for m in mutants["A"] + mutants["B"])
            conf_ids = sorted(m["mutant_id"] for m in mutants["C"])
            disc = [self._load_record(mid) for mid in disc_ids]
            conf = [self._load_record(mid) for mid in conf_ids]

            # Determinism: canonical-byte equality of each rerun with
            # its original discovery record.
            det_ids = [m["mutant_id"] for m in mutants["A"][:mutants["det_n"]]]
            agree = 0
            for mid in det_ids:
                original = self._load_record(mid)
                rerun = self._load_record(f"det-rerun-{mid}")
                if q3_run.canonical_bytes(original) == \
                        q3_run.canonical_bytes(rerun):
                    agree += 1
            det_agreement = agree / len(det_ids) if det_ids else 0.0

            kr = q3_run.kill_rate(disc)
            entry["n_discovery"] = len(disc)
            entry["n_confirmation"] = len(conf)
            entry["kill_rate_discovery"] = kr
            entry["kill_rate_confirmation"] = q3_run.kill_rate(conf)
            entry["det_rerun_agreement"] = det_agreement
            entry["collection_error_rate"] = sum(
                1 for o in disc if o["collection_error"]) / len(disc)
            entry["discovery_seal"] = self._tx.seals[name]["seal"]

            rec_a = [self._load_record(mid) for mid in sorted(
                m["mutant_id"] for m in mutants["A"])]
            rec_b = [self._load_record(mid) for mid in sorted(
                m["mutant_id"] for m in mutants["B"])]
            op_a = q3_run.op_kill_rates(rec_a)
            op_b = q3_run.op_kill_rates(rec_b)
            op_c = q3_run.op_kill_rates(conf)
            entry["op_kill_rates"] = {"A": op_a, "B": op_b,
                                     "confirmation": op_c}
            ca = Counter(o["operator"] for o in rec_a)
            cb = Counter(o["operator"] for o in rec_b)
            shared = [op for op in op_a
                      if ca[op] >= THRESH["stab_min_per_half"]
                      and cb.get(op, 0) >= THRESH["stab_min_per_half"]]
            entry["stab_operators"] = shared
            if len(shared) >= THRESH["stab_min_operators"]:
                xs = [op_a[op] for op in shared]
                ys = [op_b[op] for op in shared]
                entry["stab_spearman"] = q3_run.spearman(xs, ys)
                entry["stab_max_abs_diff"] = max(
                    abs(a - b) for a, b in zip(xs, ys))
            else:
                entry["stab_spearman"] = None
                entry["stab_max_abs_diff"] = None

            # --- threshold checks (Q3 step 6, verbatim) ---
            if det_agreement < THRESH["qdet_agreement"]:
                causes.append(f"{name}: Q-DET agreement "
                              f"{det_agreement} < 1.0")
            if not (THRESH["kill_rate_lo"] <= kr <= THRESH["kill_rate_hi"]):
                causes.append(f"{name}: Q-SIG kill rate {kr:.3f} outside "
                              f"[0.05, 0.95]")
            if len(shared) < THRESH["stab_min_operators"]:
                causes.append(f"{name}: Q-STAB only {len(shared)} qualifying "
                              f"operators (< 3)")
            else:
                if entry["stab_max_abs_diff"] > THRESH["stab_abs_tol"]:
                    causes.append(
                        f"{name}: Q-STAB max |dA-dB| "
                        f"{entry['stab_max_abs_diff']:.3f} > 0.25")
                if entry["stab_spearman"] < THRESH["stab_spearman_min"]:
                    causes.append(
                        f"{name}: Q-STAB spearman "
                        f"{entry['stab_spearman']:.3f} < 0.7")
            for op in shared:
                if abs(op_c.get(op, 0.0) - (op_a[op] + op_b[op]) / 2) > \
                        THRESH["fresh_op_tol"]:
                    causes.append(f"{name}: Q-FRESH operator {op} drifted")
            if abs(entry["kill_rate_confirmation"] - kr) > \
                    THRESH["fresh_overall_tol"]:
                causes.append(f"{name}: Q-FRESH overall kill rate drifted")
            if entry["collection_error_rate"] >= \
                    THRESH["collection_error_max"]:
                causes.append(f"{name}: collection-error rate "
                              f"{entry['collection_error_rate']:.3f} "
                              f">= 0.10")

            # --- Q-INTACT: the pinned repo must be byte-identical to the
            # receipt-bound tree hash. The runner only ever mutates
            # overlays; a mismatch here fails qualification.
            cfg_post = q3_run.tree_hash(Path(self._pool[name]["repo_root"]))
            entry["tree_hash_post"] = cfg_post
            entry["repo_intact"] = cfg_post == self._tree_hash_pre[name]
            if not entry["repo_intact"]:
                causes.append(f"{name}: Q-INTACT tree hash changed")
            repos[name] = entry
        return {"outcome": "NOT_QUALIFIED" if causes else "QUALIFIED",
                "causes": causes, "repos": repos,
                "thresholds": dict(THRESH)}

    def _verdict(self, evaluation: dict, _crash_hook=None) -> dict:
        """Receipt re-verified before verdict; drift stops with none.

        The verdict artifact/journal gap is Q4's own: ``commit_verdict``
        writes the canonical report artifact first, then the journal
        entry. A crash in the gap leaves a report file with no entry,
        which ``open`` ignores; resume recomputes deterministically
        from committed artifacts and the identical canonical bytes are
        written again.
        """
        self._reverify_receipt()
        if self._tx.verdict is not None:
            return self._tx.verdict
        outcome = evaluation["outcome"]
        terminal = (VERDICT_QUALIFIED if outcome == "QUALIFIED"
                    else VERDICT_NOT_QUALIFIED)
        self._tx.commit_verdict(verdict=terminal, report=evaluation,
                                _crash_hook=_crash_hook)
        return self._tx.verdict

    # ------------------------------------------------------------------
    # final report: receipt, committed artifacts, seals, nonce, frozen
    # constants only
    # ------------------------------------------------------------------

    def _report(self, evaluation: dict, verdict: dict,
                guard_report: dict, duration_s: float) -> dict:
        members = []
        observations = []
        for name in self._repo_names:
            for phase, key in (("discovery", "A"), ("discovery", "B"),
                               ("confirmation", "C"), ("det-rerun", None)):
                mutants = (self._mutants[name][key] if key else
                           self._mutants[name]["A"][:self._mutants[name]["det_n"]])
                for m in mutants:
                    mid = self._obs_id(phase, m)
                    observations.append({
                        "observation_id": mid,
                        "mutant_id": m["mutant_id"],
                        "artifact_sha256": self._tx.observations[mid],
                        "exec_nonce": self._exec_nonce_of(mid),
                    })
        contact = self._tx.contact_event
        report = {
            "schema": REPORT_SCHEMA,
            "experiment": "RSI-006-Q5 substrate qualification",
            "stage": "complete",
            "environment_receipt_sha256": self._receipt_sha256,
            "feasibility_guard": guard_report,
            "evaluation": evaluation,
            "verdict": {"terminal": verdict["verdict"],
                        "report_digest": verdict["report_digest"],
                        "evaluation": evaluation},
            "discovery_seals": [
                {"repo": name,
                 "seal": self._tx.seals[name]["seal"],
                 "member_ids": [m["mutant_id"]
                                for m in self._tx.seals[name]["members"]]}
                for name in self._repo_names],
            "confirmation_nonce": self._tx.nonce,
            "observations": observations,
            "contact_entries": [contact] if contact else [],
            "restart_count": self._tx.restart_count,
            "results_digest": self._tx.results_digest(),
            "duration_s": duration_s,
        }
        blob = (json.dumps(report, sort_keys=True, indent=1) + "\n") \
            .encode("utf-8")
        path = self._stage2_dir / "report.json"
        tmp = path.with_name(".tmp-report.json")
        tmp.write_bytes(blob)
        os.replace(tmp, path)
        return {"status": "complete", "terminal": verdict["verdict"],
                "report_path": str(path), "evaluation": evaluation}

    def _exec_nonce_of(self, observation_id: str) -> str:
        """The exec_nonce naming the physical execution, from the ledger."""
        from execution_ledger import ledger_dir
        path = (ledger_dir(self._stage2_dir)
                / f"{observation_id}.started.json")
        return json.loads(path.read_bytes())["exec_nonce"]

    # ------------------------------------------------------------------
    # the one contact-bearing path
    # ------------------------------------------------------------------

    def run(self, crash_points: dict | None = None) -> dict:
        """Execute (or resume) the full qualification.

        Fresh-run order is fixed:

        1. ``verify_production_receipt()`` -- before any scientific
           state;
        2. the static feasibility guard -- still pre-contact, so a
           guard failure writes a pre-contact outcome with no
           transaction, no nonce, no mutants, and no contact;
        3. the nonblocking coordinator lock, held for the whole
           scientific lifetime;
        4. receipt re-verification under the lock;
        5. exactly one ``begin()`` (fresh) or one ``open()`` (resume);
        6. on resume, ``reconcile_contact()`` IMMEDIATELY -- before
           mutant generation or any other work;
        7. deterministic mutant generation, then the phases.

        Crash points (test-only): phase-level keys ``after_discovery``,
        ``after_seal:<repo>``, ``after_nonce``, ``after_confirmation``,
        ``after_det_rerun``, ``pre_verdict``, ``verdict_gap``;
        ``after_first_contact`` crashes after the first discovery
        observation's completion is durable (contact genuinely occurred
        during it); ``partial_discovery`` crashes after a mid-discovery
        observation's completion is durable;
        ``mid_confirmation`` crashes mid-confirmation-phase. Any other
        key is a per-observation adapter crash window, passed through
        to the coordinator.
        """
        started = time.time()
        self._verify_and_bind_receipt()
        try:
            guard_report = self._guard()
        except _PreconditionFailure as exc:
            return self._write_precontact_outcome(exc)
        with qa.interprocess_lock(self._stage2_dir):
            self._reverify_receipt()
            crash = dict(crash_points or {})

            def crash_hook(point: str):
                if crash.pop(point, False):
                    raise qa._Crash

            # The lock covers the whole transaction lifetime: exactly
            # one begin() or one open() happens here, under the lock.
            resumed = self._begin_or_open()
            contact = ContactGate(self._stage2_dir / "contact_marker.json")
            coord = qa.Coordinator(
                work_dir=self._stage2_dir, tx=self._tx, gate=contact,
                receipt_sha256=self._receipt_sha256,
                code_hashes=self._code_hashes,
                wait_timeout_s=self._wait_timeout_s)
            # Resume ordering: open() exactly once above, then
            # reconcile_contact() immediately -- before mutant
            # generation or any other work -- so a won-but-unjournaled
            # contact is journaled before anything new is applied.
            coord.reconcile_contact()
            # Mutant generation is pure and deterministic (and
            # confirmation mutants are deterministic in the committed
            # nonce): regenerating on resume yields the identical sets,
            # so evaluation and the existing-verdict path have the full
            # plan without re-execution.
            self._generate_discovery_mutants()
            if self._tx.verdict is not None:
                # Existing verdict: no execution, no mutants, no
                # contact. (``resumed`` is always True on this path: a
                # verdict implies a prior journal.)
                _ = resumed
                nonce = self._confirmation_nonce()
                self._generate_confirmation_mutants(nonce)
                evaluation = self._evaluate()
                return self._report(evaluation, self._tx.verdict,
                                    {"note": "existing-verdict"}, 0.0)
            self._discovery(coord, crash)
            crash_hook("after_discovery")
            self._seals(lambda point: crash_hook(point))
            nonce = self._confirmation_nonce(
                lambda point: crash_hook(point))
            self._confirmation(coord, nonce, crash)
            crash_hook("after_confirmation")
            self._det_reruns(coord, crash)
            crash_hook("after_det_rerun")
            evaluation = self._evaluate()
            crash_hook("pre_verdict")
            verdict = self._verdict(
                evaluation, lambda: crash_hook("verdict_gap"))
            return self._report(evaluation, verdict, guard_report,
                                time.time() - started)


# ----------------------------------------------------------------------
# production entry point
# ----------------------------------------------------------------------

def _production_pool_layout(pool_dir: Path) -> dict[str, dict]:
    """The frozen four-repo pool as pure path layout.

    Stage 2 consumes Stage 1's existing, receipt-verified pool: no
    cloning, no fetching, no checkout mutation. ``repo_cfg`` is pure
    path layout; the pinned-SHA/tree-hash verification lives in the
    production environment receipt, which the runner verifies (and
    re-verifies under the lock) before any scientific work.
    """
    pool: dict[str, dict] = {}
    for entry in q3_pool.POOL:
        pool[entry["name"]] = q3_run.repo_cfg(entry, pool_dir / entry["name"])
    return pool


def main() -> None:
    ap = argparse.ArgumentParser(
        description="RSI-006-Q5 Stage 2: durable substrate qualification "
                    "(irreversible once started; requires a verified "
                    "production environment receipt)")
    ap.add_argument("--receipt", required=True, type=Path,
                    help="frozen production environment receipt")
    ap.add_argument("--pool-dir", required=True, type=Path,
                    help="directory holding the four pinned repo checkouts")
    ap.add_argument("--python", required=True,
                    help="receipt-bound interpreter for pytest workers")
    ap.add_argument("--work-dir", required=True, type=Path,
                    help="the one fixed Stage 2 directory beneath the "
                         "receipt-bound durable root")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    runner = Stage2Runner(
        stage2_dir=args.work_dir,
        pool=_production_pool_layout(args.pool_dir),
        pool_dir=args.pool_dir,
        budgets=q3_run.BUDGETS,
        python=args.python,
        receipt_path=args.receipt,
        workers=args.workers,
        code_hashes=_code_hashes(),
    )
    result = runner.run()
    print(json.dumps({
        "status": result["status"],
        "terminal": result.get("terminal"),
        "outcome": result.get("outcome"),
        "report_path": result["report_path"],
    }, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
