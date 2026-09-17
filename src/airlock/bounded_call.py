"""BOUNDED-CALL-001: finite paid-call envelope + durable terminalization.

Frozen preregistration: ~/workspace/bounded-call-001/PREREGISTRATION.md
(sha256 4d55ea067ee37d979798f13a4e0ec8506866db278b6bdd49604a057f23f610a7).

Airlock-scoped capability. No daemon, no DB, no network, no paid contact.

Primitive (load-bearing ordering):
    RESERVED (durably fsync'd)
      -> CONTACT_ARMED (durably fsync'd)
      -> provider invocation may begin
      -> settle EXECUTED / PROVEN_NOT_ENTERED / INDETERMINATE.

CONTACT_ARMED means "from this point onward the provider may have observed
the request" -- not "the provider definitely received it". Crash with only
RESERVED durably written is mechanically PROVEN_NOT_ENTERED; crash after
durable CONTACT_ARMED without authenticated terminal evidence is
INDETERMINATE, and the reservation stays encumbered.

Every ordinary return path writes its terminal record before returning.
Abrupt death (SIGKILL) may prevent the final write; restart classifies
deterministically from durable state. There is no UNKNOWN_AND_UNRECORDED
state. Classification truth comes from durable state; exception class is
diagnostics, not truth.
"""

import hashlib
import json
import os
import time
import uuid
from decimal import Decimal

# ---------------------------------------------------------------------------
# Frozen pins (from the sealed preregistration, section 9).
# ---------------------------------------------------------------------------
PRICE_TABLE_SHA256 = (
    "f28a6f9ba243841489c483b072236535cbb24da13dccf37a6f0d133c37e6f970"
)
HERMES_PIN = "29112bef099274229cadff79cdff7bf7b99c4b77"

# ---------------------------------------------------------------------------
# States.
# ---------------------------------------------------------------------------
RESERVED = "RESERVED"
CONTACT_ARMED = "CONTACT_ARMED"
EXECUTED = "EXECUTED"
PROVEN_NOT_ENTERED = "PROVEN_NOT_ENTERED"
INDETERMINATE = "INDETERMINATE"
TERMINAL_STATES = frozenset({EXECUTED, PROVEN_NOT_ENTERED, INDETERMINATE})


class BoundedCallError(Exception):
    """Base for all BOUNDED-CALL-001 errors."""


class EnvelopeInvalid(BoundedCallError):
    """A cost-envelope field is unknown, unverified, unenforced, or unbounded."""


class BudgetExceeded(BoundedCallError):
    """Computed R_i exceeds the authorized budget: fail closed, pre-contact."""


class NotContactArmed(BoundedCallError):
    """Provider invocation attempted without durable CONTACT_ARMED."""


class EnvelopeViolated(BoundedCallError):
    """Observed usage priced above the reserved R_i (preserved, then raised)."""


class ProvenNotEnteredSignal(BoundedCallError):
    """Adapter attestation: demonstrably pre-dispatch, no byte reached provider.

    This is authenticated evidence supplied by the provider adapter itself,
    not an inference from an exception class. The boundary still re-raises it
    after terminalizing, so a halt keeps its documented "let it propagate"
    semantics -- now with a durable terminal record, which PAYBACK-003 lacked.
    """

    def __init__(self, detail):
        super().__init__(detail)
        self.detail = detail


# ---------------------------------------------------------------------------
# Price table and R_i.
# ---------------------------------------------------------------------------
def _sha256_file(path):
    """sha256 hex of exact file bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_price_table(path, expected_sha256):
    """Load the frozen price table; refuse on any byte drift (fail closed)."""
    actual = _sha256_file(path)
    if actual != expected_sha256:
        raise EnvelopeInvalid("price-table sha mismatch: expected %s got %s" % (expected_sha256, actual))
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _require_int(env, name, minimum):
    """Mechanically enforced integer bound, or fail closed."""
    try:
        value = int(env[name])
    except (KeyError, TypeError, ValueError):
        raise EnvelopeInvalid("envelope.%s missing or not an integer" % name)
    if isinstance(env[name], bool) or value < minimum:
        raise EnvelopeInvalid("envelope.%s unbounded/invalid: %r" % (name, env[name]))
    return value


def _require_sha(env, name):
    """64-hex sha field, or fail closed."""
    value = env.get(name)
    try:
        valid = isinstance(value, str) and len(value) == 64
        int(value, 16)
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise EnvelopeInvalid("envelope.%s not a 64-hex sha" % name)
    return value


def validate_envelope(env):
    """Validate and bind every frozen cost-envelope field (prereg 3.2).

    Any required pricing/resource input that is unknown, unverified, not
    mechanically enforced, or unbounded raises EnvelopeInvalid BEFORE any
    RESERVED record is written.
    """
    if not isinstance(env, dict):
        raise EnvelopeInvalid("envelope must be a mapping")
    out = {}
    for name in ("provider", "model", "price_table_path"):
        value = env.get(name)
        if not isinstance(value, str) or not value:
            raise EnvelopeInvalid("envelope.%s missing or empty" % name)
        out[name] = value
    tier = env.get("tier")
    if tier is not None and (not isinstance(tier, str) or not tier):
        raise EnvelopeInvalid("envelope.tier invalid")
    out["tier"] = tier
    out["price_table_sha"] = _require_sha(env, "price_table_sha")
    out["config_sha"] = _require_sha(env, "config_sha")
    hermes_pin = env.get("hermes_pin")
    if hermes_pin != HERMES_PIN:
        raise EnvelopeInvalid("envelope.hermes_pin != frozen pin")
    out["hermes_pin"] = hermes_pin
    out["max_iterations"] = _require_int(env, "max_iterations", 1)
    out["max_api_attempts"] = _require_int(env, "max_api_attempts", 1)
    out["max_compression_attempts"] = _require_int(env, "max_compression_attempts", 0)
    out["max_input_tokens"] = _require_int(env, "max_input_tokens", 1)
    out["max_output_tokens"] = _require_int(env, "max_output_tokens", 1)
    table = load_price_table(out["price_table_path"], out["price_table_sha"])
    for key, akey in (("provider", "provider_aliases"), ("model", "model_aliases")):
        aliases = set(table.get(akey, []) + [table.get(key)])
        if out[key] not in aliases:
            raise EnvelopeInvalid("%s not in frozen table aliases" % key)
    required_tier = table.get("service_tier_required")
    if required_tier is None:
        if out["tier"] is not None:
            raise EnvelopeInvalid("table requires no tier; envelope sets one")
    elif out["tier"] != required_tier:
        raise EnvelopeInvalid("tier != table service_tier_required")
    return out


def _per_million(value):
    """Decimal dollars-per-token from a per-million-token rate string."""
    return Decimal(str(value)) / Decimal(1000000)


def _lc_multipliers(price_table):
    """Worst-case long-context multipliers: max input-side, and output."""
    lc = price_table["long_context"]
    in_mult = max(Decimal(str(lc[k])) for k in
                  ("input_multiplier", "cache_read_multiplier", "cache_write_multiplier"))
    return in_mult, Decimal(str(lc["output_multiplier"]))


def compute_R_i(envelope, price_table):
    """Frozen upper-bound equation (prereg 3.3).

    Accounts for every billable dimension under the permitted path:
    maximum input/context exposure (at the worst applicable input-side
    rate -- max of input/cache_read/cache_write, since a token is billed
    at most once at the highest applicable rate), maximum output tokens,
    number of model calls (iterations x attempts + summaries + compression),
    and the frozen long-context multipliers when the input bound reaches
    the table's long-context threshold.
    """
    rates = price_table["rates_per_million_tokens"]
    p_in = max(
        _per_million(rates["input_tokens"]),
        _per_million(rates["cache_read_tokens"]),
        _per_million(rates["cache_write_tokens"]),
    )
    p_out = _per_million(rates["output_tokens"])
    threshold = int(price_table["long_context"]["threshold_prompt_tokens_per_request"])
    if envelope["max_input_tokens"] >= threshold:
        in_mult, out_mult = _lc_multipliers(price_table)
        p_in, p_out = p_in * in_mult, p_out * out_mult
    c_calls = (
        (envelope["max_iterations"] + 1) * envelope["max_api_attempts"]
        + 2  # iteration-cap summary calls
        + envelope["max_compression_attempts"]
    )
    per_call = (
        Decimal(envelope["max_input_tokens"]) * p_in
        + Decimal(envelope["max_output_tokens"]) * p_out
    )
    return c_calls * per_call


def price_usage(usage, price_table):
    """Price observed usage at frozen table rates (actuals, not bounds)."""
    rates = price_table["rates_per_million_tokens"]
    in_tokens = int(usage.get("input_tokens", 0) or 0)
    out_tokens = int(usage.get("output_tokens", 0) or 0)
    cache_w = int(usage.get("cache_write_tokens", 0) or 0)
    threshold = int(price_table["long_context"]["threshold_prompt_tokens_per_request"])
    p_in, p_cw, p_out = _per_million(rates["input_tokens"]), _per_million(rates["cache_write_tokens"]), _per_million(rates["output_tokens"])
    if in_tokens >= threshold:
        in_mult, out_mult = _lc_multipliers(price_table)
        p_in, p_cw, p_out = p_in * in_mult, p_cw * in_mult, p_out * out_mult
    return Decimal(in_tokens) * p_in + Decimal(cache_w) * p_cw + Decimal(out_tokens) * p_out


# ---------------------------------------------------------------------------
# Crash-safe durable persistence.
# ---------------------------------------------------------------------------
class DurableStore:
    """One JSON record per invocation; every transition is atomic + fsync'd.

    Write protocol: serialize -> write temp file -> f.flush/fsync ->
    os.rename (atomic) -> fsync the directory. A record that exists on disk
    after a crash is therefore a complete, fsync'd state -- the property the
    RESERVED -> CONTACT_ARMED ordering proof depends on. No daemon, no DB.
    """

    def __init__(self, directory):
        self.directory = os.path.abspath(directory)
        os.makedirs(self.directory, exist_ok=True)

    def _path(self, invocation_id):
        if not invocation_id or "/" in invocation_id or invocation_id.startswith("."):
            raise BoundedCallError("bad invocation_id")
        return os.path.join(self.directory, invocation_id + ".json")

    def write(self, record):
        """Durably persist a full record; returns only after fsync."""
        path = self._path(record["invocation_id"])
        tmp = path + ".tmp"
        data = json.dumps(record, sort_keys=True).encode("utf-8")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            os.write(fd, data); os.fsync(fd)
        finally:
            os.close(fd)
        os.rename(tmp, path)
        dfd = os.open(self.directory, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)

    def read(self, invocation_id):
        """Disk is truth: always re-read; never trust cached memory."""
        with open(self._path(invocation_id), "r", encoding="utf-8") as f:
            return json.load(f)

    def list_records(self):
        """All records currently durable on disk."""
        out = []
        for name in sorted(os.listdir(self.directory)):
            if name.endswith(".json"):
                with open(os.path.join(self.directory, name), encoding="utf-8") as f:
                    out.append(json.load(f))
        return out


# ---------------------------------------------------------------------------
# Reservation (pre-contact gate).
# ---------------------------------------------------------------------------
def reserve(store, envelope, budget_usd, invocation_id=None):
    """Pre-contact gate: validate, bind, compute R_i, require R_i <= B.

    Writes RESERVED durably and returns a BoundedCall. Provider contact is
    NOT yet permitted: only arm() grants that, after its own durable write.
    Raises EnvelopeInvalid / BudgetExceeded before any provider contact.
    """
    env = validate_envelope(envelope)
    table = load_price_table(env["price_table_path"], env["price_table_sha"])
    r_i = compute_R_i(env, table)
    budget = Decimal(str(budget_usd))
    if r_i > budget:
        raise BudgetExceeded("R_i %s exceeds budget %s" % (r_i, budget))
    invocation_id = invocation_id or uuid.uuid4().hex
    record = {
        "invocation_id": invocation_id, "state": RESERVED,
        "envelope": env, "r_i": str(r_i), "budget_usd": str(budget),
        "pid": os.getpid(), "reserved_at": time.time(),
        "terminal_at": None, "settled_usd": None, "encumbered": True,
        "note": None, "evidence": None,
    }
    store.write(record)
    return BoundedCall(store, invocation_id)


# ---------------------------------------------------------------------------
# The bounded call: arm -> invoke, with a finally-grade outer boundary.
# ---------------------------------------------------------------------------
class BoundedCall:
    """One reserved paid call. arm() then invoke(); nothing else reaches provider."""

    def __init__(self, store, invocation_id):
        self._store = store
        self.invocation_id = invocation_id

    def _record(self):
        return self._store.read(self.invocation_id)

    def arm(self):
        """Durably write CONTACT_ARMED. Returns only after fsync.

        Provider invocation is structurally impossible before this returns:
        invoke() re-reads the on-disk state and refuses anything but
        CONTACT_ARMED.
        """
        rec = self._record()
        if rec["state"] != RESERVED:
            raise BoundedCallError("arm() requires RESERVED, found %s" % rec["state"])
        rec["state"] = CONTACT_ARMED
        rec["armed_at"] = time.time()
        self._store.write(rec)

    def invoke(self, provider_fn, *args, **kwargs):
        """Invoke the provider under the outer terminalization boundary.

        Refuses unless the DURABLE on-disk state is CONTACT_ARMED -- memory
        is never consulted, so no code path can reach the provider before
        the CONTACT_ARMED fsync completes.
        """
        rec = self._record()
        if rec["state"] != CONTACT_ARMED:
            raise NotContactArmed("refusing: durable state is %s" % rec["state"])
        return self._guarded(provider_fn, rec, args, kwargs)

    def _guarded(self, provider_fn, rec, args, kwargs):
        """Finally-grade outer boundary. State decides; exceptions diagnose.

        - ProvenNotEnteredSignal (adapter-attested pre-dispatch evidence) ->
          terminalize PROVEN_NOT_ENTERED, release, then re-raise so a halt
          keeps its documented "let it propagate" semantics.
        - Every other BaseException (transport failure, InfrastructureHalt,
          KeyboardInterrupt, SystemExit, ...) -> CONTACT_ARMED was durable
          and there is no authenticated terminal evidence, so terminalize
          INDETERMINATE (encumbered), then re-raise, preserving the original
          semantics (KeyboardInterrupt/SystemExit still propagate).
        - Ordinary return -> settle from observed usage.
        """
        try:
            result = provider_fn(*args, **kwargs)
        except ProvenNotEnteredSignal as e:
            self._terminal(PROVEN_NOT_ENTERED, settled=Decimal(0),
                           evidence={"attestation": e.detail})
            raise
        except BaseException as e:  # noqa: BLE001 -- boundary must not leak
            self._terminal(INDETERMINATE, note="during provider invocation: %r" % (e,))
            raise
        return self._settle_success(rec, result)

    def _settle_success(self, rec, result):
        """EXECUTED settlement. Settled charge never exceeds the reservation."""
        table = load_price_table(
            rec["envelope"]["price_table_path"],
            rec["envelope"]["price_table_sha"],
        )
        usage = result.get("usage") if isinstance(result, dict) else None
        r_i = Decimal(rec["r_i"])
        if usage is None:
            # Missing usage output: never release, never assume zero.
            # Authenticated evidence of execution exists (provider returned),
            # but the charge is unprovable below the reservation -> settle R_i.
            self._terminal(EXECUTED, settled=r_i,
                           note="usage unattested; settled at R_i")
            return result
        settled = price_usage(usage, table)
        if settled > r_i:
            # Bound violated by the provider path: preserve loudly, cap at R_i.
            self._terminal(EXECUTED, settled=r_i,
                           note="ENVELOPE_VIOLATED: observed usage priced %s > R_i %s"
                           % (settled, r_i),
                           evidence={"usage": usage})
            raise EnvelopeViolated("observed usage priced above R_i")
        self._terminal(EXECUTED, settled=settled, evidence={"usage": usage})
        return result

    def _terminal(self, state, settled=None, note=None, evidence=None):
        """Write the terminal record durably. Idempotent: never overwrite one."""
        rec = self._record()
        if rec["state"] in TERMINAL_STATES:
            return rec
        rec["state"] = state
        rec["terminal_at"] = time.time()
        if settled is not None:
            rec["settled_usd"] = str(settled)
        if note is not None:
            rec["note"] = note
        if evidence is not None:
            rec["evidence"] = evidence
        rec["encumbered"] = state == INDETERMINATE
        self._store.write(rec)
        return rec

    def reconcile(self, evidence):
        """Resolve INDETERMINATE only on authenticated evidence. Never infer.

        Evidence must carry this invocation_id and kind "executed" (with
        usage) or "not_entered". There is no timeout/auto-release path
        anywhere in this module: unauthenticated inference never releases an
        encumbrance.
        """
        rec = self._record()
        if rec["state"] != INDETERMINATE:
            raise BoundedCallError("reconcile applies only to INDETERMINATE")
        if not isinstance(evidence, dict):
            raise BoundedCallError("evidence must be a mapping")
        if evidence.get("invocation_id") != self.invocation_id:
            raise BoundedCallError("evidence invocation_id mismatch")
        kind = evidence.get("kind")
        if kind == "executed":
            table = load_price_table(
                rec["envelope"]["price_table_path"],
                rec["envelope"]["price_table_sha"],
            )
            settled = min(price_usage(evidence.get("usage") or {}, table),
                          Decimal(rec["r_i"]))
            self._terminal(EXECUTED, settled=settled, evidence=evidence)
        elif kind == "not_entered":
            self._terminal(PROVEN_NOT_ENTERED, settled=Decimal(0),
                           evidence=evidence)
        else:
            raise BoundedCallError("evidence kind must be executed|not_entered")
        return self._record()


# ---------------------------------------------------------------------------
# Restart recovery: classify deterministically from durable state.
# ---------------------------------------------------------------------------
def _pid_alive(pid):
    """Best-effort owner-liveness check (never trusted for classification)."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def recover(store):
    """Startup reconciliation over durable records.

    For each non-terminal record whose owner process is gone:
      RESERVED (no CONTACT_ARMED) -> PROVEN_NOT_ENTERED, released, $0.
      CONTACT_ARMED (no terminal evidence) -> INDETERMINATE, stays encumbered.
    Records of unknown state are left untouched (recorded, not classified).
    Never creates UNKNOWN_AND_UNRECORDED: every handled record terminalizes.
    """
    done = []
    for rec in store.list_records():
        if rec["state"] in TERMINAL_STATES:
            continue
        if _pid_alive(rec.get("pid")):
            continue
        call = BoundedCall(store, rec["invocation_id"])
        if rec["state"] == RESERVED:
            call._terminal(PROVEN_NOT_ENTERED, settled=Decimal(0),
                           note="restart recovery: durable RESERVED, no CONTACT_ARMED")
            done.append((rec["invocation_id"], PROVEN_NOT_ENTERED))
        elif rec["state"] == CONTACT_ARMED:
            call._terminal(INDETERMINATE,
                           note="restart recovery: durable CONTACT_ARMED, "
                                "no authenticated terminal evidence")
            done.append((rec["invocation_id"], INDETERMINATE))
    return done
