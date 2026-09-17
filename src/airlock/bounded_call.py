"""BOUNDED-CALL-001 replacement apparatus (PRECONTACT-AMENDMENT-001).

Implements the amended precontact contract: the corrected conservative R_i,
mechanically established driver exclusions, HMAC-authenticated
reconciliation with key separation, and durable RESERVED -> CONTACT_ARMED
ordering. The sole provider-call path is the one-shot invoke_bounded();
the raw agent is never returned to callers. This module performs no
qualification and makes no paid contact.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

from .verification import ensure_key, sign, verify_signature

HERMES_PIN = "29112bef099274229cadff79cdff7bf7b99c4b77"
PROVIDER = "openai-api"
PROVIDER_ALIASES = ("openai", "openai-api")
MODEL = "gpt-5.6-sol"
MODEL_ALIASES = ("gpt-5.6", "gpt-5.6-sol")
A_SLOT = 12
C_MODEL = 1050000
OUTPUT_CAP = 32768
PREREG_SHA = "4d55ea067ee37d979798f13a4e0ec8506866db278b6bdd49604a057f23f610a7"
AMENDMENT_SHA = "d18e214be19c9923fbb5d80609087cdb1fdc7bb22469cdb564e48837658a386d"
PRICE_TABLE_SHA = "f28a6f9ba243841489c483b072236535cbb24da13dccf37a6f0d133c37e6f970"

P_IN = Decimal("4")
P_READ = Decimal("0.40")
P_WRITE = Decimal("5")
P_OUT = Decimal("20")
LC_IN_MULT = Decimal("2")
LC_OUT_MULT = Decimal("1.5")
LC_THRESHOLD = 272000
_M = Decimal("1000000")

_WORST_INPUT_RATE = max(P_IN * LC_IN_MULT, P_READ * LC_IN_MULT, P_WRITE * LC_IN_MULT)
_P_CALL = (Decimal(C_MODEL) * _WORST_INPUT_RATE
           + Decimal(OUTPUT_CAP) * P_OUT * LC_OUT_MULT) / _M
assert _P_CALL == Decimal("11.48304"), "frozen P_call derivation drifted"
P_CALL = Decimal("11.48304")

BUCKETS = ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens")
_MISSING = object()

# Frozen minimal tool surface. The production agent is constructed with an
# explicit EMPTY toolset allowlist: enabled_toolsets=[] resolves through the
# pinned Hermes toolset machinery (model_tools._compute_tool_definitions,
# `enabled_toolsets is not None` branch) to zero tools. No tool can then
# initiate an auxiliary model/provider call (vision_analyze's auxiliary
# vision router, image_generate's FAL submission, browser_vision's
# auxiliary-vision fallback, delegate_task's subagent forks are all
# unreachable: the model is never offered them). The empty surface is the
# primitive's frozen surface; BOUNDED-CALL-001 is a single bounded
# prompt->response call and requires no tools.
TOOLSETS_ENABLED = ()
FROZEN_TOOL_NAMES = ()


class GateRefused(Exception):
    """Pre-contact refusal. Terminal; never silently passed."""


class PinMismatch(Exception):
    """Hermes checkout is not the pinned commit."""


class EvidenceRejected(Exception):
    """Reconciliation evidence failed the frozen predicate."""


def compute_r_i(max_iterations):
    """Frozen: R_i = (12 * max_iterations + 2) * $11.48304, exact Decimal."""
    if not isinstance(max_iterations, int) or isinstance(max_iterations, bool):
        raise GateRefused("max_iterations must be an int")
    if max_iterations < 1:
        raise GateRefused("max_iterations must be positive")
    return (A_SLOT * max_iterations + 2) * P_CALL


def price_usage(usage):
    """Price the four mutually exclusive buckets; reasoning stays inside output.

    Prompt exposure is derived from the buckets (input + cache_read +
    cache_write); long-context multipliers apply iff it exceeds 272000.
    """
    prompt_tokens = (usage["input_tokens"] + usage["cache_read_tokens"]
                     + usage["cache_write_tokens"])
    mult_in = LC_IN_MULT if prompt_tokens > LC_THRESHOLD else Decimal(1)
    mult_out = LC_OUT_MULT if prompt_tokens > LC_THRESHOLD else Decimal(1)
    return (
        usage["input_tokens"] * P_IN * mult_in
        + usage["cache_read_tokens"] * P_READ * mult_in
        + usage["cache_write_tokens"] * P_WRITE * mult_in
        + usage["output_tokens"] * P_OUT * mult_out
    ) / _M


def frozen_config_text():
    """Exact bytes of the adapter-owned Hermes config that make the bound true."""
    return ("agent:\n  api_max_retries: 1\n  compression:\n    enabled: false\n"
            "auxiliary:\n  background_review:\n    enabled: false\n")


def write_driver_config(home):
    """Write the frozen config; return its sha256. Deterministic bytes."""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    text = frozen_config_text()
    (home / "config.yaml").write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_hermes_pin(hermes_path):
    out = subprocess.run(
        ["git", "-C", str(hermes_path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True)
    if out.stdout.strip() != HERMES_PIN:
        raise PinMismatch("Hermes checkout is not the pinned commit")


@contextlib.contextmanager
def _isolated_home(home):
    """Scope a bounded provider window to the isolated Hermes home.

    The active Hermes home selects the plugin manager, the config, and
    the .env for the whole window (construct -> verify invariants ->
    run_conversation -> extract usage), so the ambient operator profile
    can never become active after CONTACT_ARMED: pinned Hermes resolves
    its plugin manager from the current home on every lifecycle hook
    (plugins._delivery_manager -> get_plugin_manager -> _plugin_home_key
    -> get_hermes_home), with lazy discovery on first hook.

    HERMES_ENABLE_PROJECT_PLUGINS is neutralized in the window because
    project-plugin discovery is cwd-scoped (./.hermes/plugins/), not
    home-scoped. Both variables are restored in the finally clause.
    """
    saved = {k: os.environ.get(k) for k in ("HERMES_HOME", "HERMES_ENABLE_PROJECT_PLUGINS")}
    os.environ["HERMES_HOME"] = str(home)
    os.environ.pop("HERMES_ENABLE_PROJECT_PLUGINS", None)
    try:
        yield
    finally:
        for key, val in saved.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


def _build_agent(hermes_path, home, max_iterations, api_key):
    """Mechanically instantiate the pinned Hermes path. Returns the agent.

    Module-private: callers never receive the raw agent. The one-shot
    invoke_bounded() owns the sole provider call made through it.

    Does not invoke the agent (no paid contact here). The reconciliation key
    is never accepted by this function and never forwarded: the signature
    carries no key parameter by construction, so the worker cannot receive
    signing authority through arguments, environment, config, or API surface.
    """
    verify_hermes_pin(hermes_path)
    home = Path(home)
    config_hash = write_driver_config(home)
    env_path = home / ".env"
    env_path.write_text("OPENAI_API_KEY=<redacted>", encoding="utf-8")
    os.chmod(env_path, 0o600)
    with _isolated_home(home):
        root = str(hermes_path)
        if root not in sys.path:
            sys.path.insert(0, root)
        from run_agent import AIAgent
        agent = AIAgent(
            api_key=api_key,
            provider=PROVIDER,
            model=MODEL,
            max_iterations=max_iterations,
            max_tokens=OUTPUT_CAP,
            fallback_model=None,
            enabled_toolsets=list(TOOLSETS_ENABLED),
            api_mode="chat_completions",
            skip_background_review=True,
        )
        if agent._api_max_retries != 1:
            raise GateRefused("Hermes application retry not at single-attempt setting")
        if agent.compression_enabled:
            raise GateRefused("Hermes compression not disabled")
        if agent._fallback_chain:
            raise GateRefused("Hermes fallback chain not empty")
        if not agent.skip_background_review:
            raise GateRefused("Hermes background review not disabled")
        _assert_frozen_tool_surface(agent)
        agent._bounded_call_config_hash = config_hash
    return agent


def _assert_frozen_tool_surface(agent):
    """Fail closed unless the resolved tool surface is exactly the frozen one.

    Reads the actual resolved surface (agent.tools plus the registry name
    set), not the requested selection: an unexpected tool, a differently
    expanding toolset, or any model-calling auxiliary tool present refuses.
    Exercised in qualification against offline stand-ins (no paid contact).
    """
    resolved = [t.get("function", {}).get("name") for t in agent.tools or []]
    if resolved != list(FROZEN_TOOL_NAMES) or getattr(agent, "valid_tool_names", None):
        raise GateRefused("tool surface is not the frozen surface: %r" % (resolved,))


def _extract_usage(result):
    """Extract billing counters from the top level of a pinned Hermes result.

    Pinned turn_finalizer() returns input/output/cache_read/cache_write as
    top-level keys of the result dict. Fail closed: a non-mapping result, or
    any counter missing, non-integer, boolean, or negative, refuses. Never
    substitutes zero for missing live telemetry. Exercised in qualification
    against an offline synthetic fixture shaped like pinned finalizer
    output (no paid contact).
    """
    if not isinstance(result, dict):
        raise GateRefused("Hermes result is not a mapping")
    usage = {}
    for bucket in BUCKETS:
        value = result.get(bucket, _MISSING)
        if value is _MISSING or type(value) is not int or value < 0:
            raise GateRefused("bad live billing counter: %s" % bucket)
        usage[bucket] = value
    return usage


def production_provider_factory(*, log_path, invocation_id, hermes_path, home,
                                api_key):
    """Zero-arg factory for the real pinned-Hermes provider call.

    Every envelope value -- max_iterations, provider, model, Hermes pin,
    output cap, driver config -- is derived from the durable RESERVED record
    and frozen constants. The caller supplies only operator infrastructure
    (checkout path, prepared home, credential); no duplicate unconstrained
    envelope value is accepted, so reserving K=3 cannot run K=30.
    """
    recs = [r for r in _read_log(log_path) if r.get("invocation_id") == invocation_id]
    reserved = [r for r in recs if r.get("state") == "RESERVED"]
    if not reserved:
        raise GateRefused("no durable RESERVED for invocation")
    bound = reserved[0]
    frozen = (("hermes_pin", HERMES_PIN), ("provider", PROVIDER),
              ("model", MODEL), ("output_cap", OUTPUT_CAP))
    if any(bound.get(field) != value for field, value in frozen):
        raise GateRefused("RESERVED envelope field drifted from frozen")
    max_iterations = bound.get("max_iterations")
    if type(max_iterations) is not int or max_iterations < 1:
        raise GateRefused("RESERVED max_iterations not a positive int")
    def factory():
        agent = _build_agent(hermes_path, home, max_iterations, api_key)
        def call(prompt):
            # The provider call executes under the SAME isolated home bound
            # before RESERVED: pinned Hermes resolves its plugin manager
            # from the current home on every lifecycle hook during
            # run_conversation, so the ambient profile must not become
            # active here. Restoration happens in _isolated_home's finally.
            with _isolated_home(home):
                return _extract_usage(agent.run_conversation(prompt))
        return call
    return factory


def _verify_config_binding(home, config_hash):
    """The bound config SHA must equal the frozen bytes, and the on-disk
    config.yaml must hash to the same value. Checked before CONTACT_ARMED."""
    expected = hashlib.sha256(frozen_config_text().encode("utf-8")).hexdigest()
    if config_hash != expected:
        raise GateRefused("RESERVED config hash is not the frozen config")
    on_disk = Path(home) / "config.yaml"
    if (not on_disk.exists()
            or hashlib.sha256(on_disk.read_bytes()).hexdigest() != expected):
        raise GateRefused("driver config on disk does not match bound hash")


def invoke_bounded(*, log_path, invocation_id, home, prompt, provider_factory):
    """One-shot provider invocation bound to the durable reservation.

    Verifies durable RESERVED and the bound config SHA, atomically claims
    CONTACT_ARMED under an advisory file lock (fsync), then makes the sole
    provider call through provider_factory, a zero-arg callable returning
    call(prompt) -> usage dict. The raw agent is never returned to callers.
    A second invocation under the same ID refuses before provider contact,
    even across concurrent processes.
    """
    recs = [r for r in _read_log(log_path) if r.get("invocation_id") == invocation_id]
    reserved = [r for r in recs if r.get("state") == "RESERVED"]
    if not reserved:
        raise GateRefused("no durable RESERVED for invocation")
    _verify_config_binding(home, reserved[0]["config_hash"])
    surface = (reserved[0].get("toolsets_enabled"), reserved[0].get("tool_names"))
    if surface != (list(TOOLSETS_ENABLED), list(FROZEN_TOOL_NAMES)):
        raise GateRefused("RESERVED tool-surface binding drifted from frozen")
    _claim_contact_armed(log_path, invocation_id)
    call_provider = provider_factory()
    return call_provider(prompt)


def _append_record(log_path, record):
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return record


def _read_log(log_path):
    path = Path(log_path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def precontact_gate(*, max_iterations, budget, model, provider,
                    price_table_sha, hermes_pin):
    """If-and-only-if pre-contact gate. Returns the bound RESERVED fields."""
    if model not in MODEL_ALIASES:
        raise GateRefused("model not in frozen table aliases")
    if provider not in PROVIDER_ALIASES:
        raise GateRefused("provider not in frozen table aliases")
    if price_table_sha != PRICE_TABLE_SHA:
        raise GateRefused("price-table SHA mismatch")
    if hermes_pin != HERMES_PIN:
        raise GateRefused("Hermes pin mismatch")
    r_i = compute_r_i(max_iterations)
    if r_i > budget:
        raise GateRefused("R_i exceeds authorized budget")
    return {
        "prereg_sha": PREREG_SHA,
        "amendment_sha": AMENDMENT_SHA,
        "price_table_sha": PRICE_TABLE_SHA,
        "hermes_pin": HERMES_PIN,
        "provider": PROVIDER,
        "model": MODEL,
        "max_iterations": max_iterations,
        "a_slot": A_SLOT,
        "c_calls": A_SLOT * max_iterations + 2,
        "c_model": C_MODEL,
        "output_cap": OUTPUT_CAP,
        "p_call": str(P_CALL),
        "r_i": str(r_i),
        "budget": str(budget),
        "toolsets_enabled": list(TOOLSETS_ENABLED),
        "tool_names": list(FROZEN_TOOL_NAMES),
    }


def reserve(log_path, invocation_id, bound, config_hash):
    """Durably write RESERVED, binding the exact driver config SHA.

    The config is generated and verified before RESERVED; fsync before return.
    """
    record = {"state": "RESERVED", "invocation_id": invocation_id,
              "config_hash": config_hash}
    record.update(bound)
    return _append_record(log_path, record)


def _claim_contact_armed(log_path, invocation_id):
    """Atomically claim the one-shot under an advisory file lock.

    Read -> verify unused -> append/fsync CONTACT_ARMED holds LOCK_EX, so
    two concurrent processes cannot consume the same reservation. The lock
    is released before any provider construction or factory entry.
    """
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            recs = [json.loads(line) for line in handle if line.strip()]
            if any(r.get("state") == "CONTACT_ARMED"
                   and r.get("invocation_id") == invocation_id for r in recs):
                raise GateRefused("invocation already used: one-shot")
            handle.write(json.dumps({"state": "CONTACT_ARMED",
                                     "invocation_id": invocation_id},
                                    sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def recover(log_path, invocation_id):
    """Post-crash recovery from the durable log alone.

    Unknown invocation (no durable RESERVED) is an error, never a
    classification. Before CONTACT_ARMED: PROVEN_NOT_ENTERED (the entry mark
    was never durably written, so no provider invocation could have begun).
    After CONTACT_ARMED with no verified resolution: INDETERMINATE.
    """
    recs = [r for r in _read_log(log_path) if r.get("invocation_id") == invocation_id]
    if not any(r.get("state") == "RESERVED" for r in recs):
        raise GateRefused("unknown invocation: no durable RESERVED")
    if not any(r.get("state") == "CONTACT_ARMED" for r in recs):
        return "PROVEN_NOT_ENTERED"
    return "INDETERMINATE"


def resolve(log_path, invocation_id, authority):
    """Return the verified signed payload, or None if absent/unverifiable."""
    recs = [r for r in _read_log(log_path) if r.get("invocation_id") == invocation_id]
    for record in recs:
        if record.get("state") == "RESOLVED":
            return authority.verify(record["resolution"], invocation_id)
    return None


class ReconciliationAuthority:
    """Holds the reconciliation key. The driver never sees this object.

    The signature proves an authorized authority issued the resolution; it
    does not prove provider truth. Signing happens only after the frozen
    evidence predicate succeeds.
    """

    def __init__(self, key_path):
        self._key = ensure_key(Path(key_path))

    def reconcile(self, *, invocation_id, log_path, usage):
        if not isinstance(usage, dict):
            raise EvidenceRejected("usage must be a mapping")
        for bucket in BUCKETS:
            value = usage.get(bucket, 0)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise EvidenceRejected("bad usage bucket: %s" % bucket)
        recs = [r for r in _read_log(log_path)
                if r.get("invocation_id") == invocation_id]
        reserved = [r for r in recs if r.get("state") == "RESERVED"]
        armed = any(r.get("state") == "CONTACT_ARMED" for r in recs)
        if not reserved or not armed:
            raise EvidenceRejected("no durable RESERVED -> CONTACT_ARMED")
        r_i = Decimal(reserved[0]["r_i"])
        prompt_tokens = (usage["input_tokens"] + usage["cache_read_tokens"]
                         + usage["cache_write_tokens"])
        observed = price_usage(usage)
        payload = {
            "invocation_id": invocation_id,
            "outcome": "EXECUTED",
            "usage": {bucket: usage.get(bucket, 0) for bucket in BUCKETS},
            "prompt_tokens": prompt_tokens,
            "observed_charge": str(observed),
            "r_i": str(r_i),
            "envelope_violation": observed > r_i,
        }
        record = sign(payload, self._key)
        _append_record(log_path, {"state": "RESOLVED",
                                  "invocation_id": invocation_id,
                                  "resolution": record})
        return record

    def verify(self, record, invocation_id):
        """Accept only correctly invocation-bound, untampered signatures."""
        if not isinstance(record, dict):
            raise EvidenceRejected("record must be a mapping")
        if not verify_signature(record, self._key):
            raise EvidenceRejected("bad signature")
        payload = record.get("payload", {})
        if payload.get("invocation_id") != invocation_id:
            raise EvidenceRejected("invocation not bound")
        return payload
