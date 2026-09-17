"""BOUNDED-CALL-001 qualification fixtures for the amended contract.

NOT EXECUTED. Importing this module runs nothing, and the file name matches
no test-discovery pattern, so broad discovery can never invoke Q1-Q6.
Each case encodes its amended-contract check exactly, against a real
durable log on real disk. The fake provider sits behind the same one-shot
invoke_bounded() wrapper that would own the real Hermes call, so the paid
path is what gets qualified. Q2/Q3 use real child processes and real SIGKILL.
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

from airlock import bounded_call as bc


def _tmp():
    return Path(tempfile.mkdtemp(prefix="bc001-"))


def _gate_fields(**overrides):
    fields = dict(max_iterations=3, budget=Decimal("500"), model="gpt-5.6-sol",
                  provider="openai-api", price_table_sha=bc.PRICE_TABLE_SHA,
                  hermes_pin=bc.HERMES_PIN)
    fields.update(overrides)
    return fields


def _reserve(invocation, **gate_overrides):
    """Config first, then gate, then durable RESERVED binding the config SHA."""
    tmp = _tmp()
    log = tmp / "log.jsonl"
    home = tmp / "home"
    config_hash = bc.write_driver_config(home)
    bound = bc.precontact_gate(**_gate_fields(**gate_overrides))
    bc.reserve(log, invocation, bound, config_hash)
    return tmp, log, home


def _kill_child_after(fn):
    pid = os.fork()
    if pid == 0:
        try:
            fn()
        finally:
            os.kill(os.getpid(), signal.SIGKILL)
    _, status = os.waitpid(pid, 0)
    assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL


def case_q1_gate_and_r_i():
    """Corrected R_i; every refusal terminal; provider runs only after arm; one-shot."""
    assert bc.compute_r_i(3) == Decimal("436.35552")
    bound = bc.precontact_gate(**_gate_fields())
    assert bound["r_i"] == "436.35552"
    assert bound["a_slot"] == 12 and bound["c_calls"] == 38
    assert bound["c_model"] == 1050000 and bound["output_cap"] == 32768
    assert bound["p_call"] == "11.48304"
    assert bound["prereg_sha"] == bc.PREREG_SHA
    assert bound["amendment_sha"] == bc.AMENDMENT_SHA
    for bad in (dict(budget=Decimal("1")), dict(model="gpt-9"),
                dict(provider="other"), dict(price_table_sha="0" * 64),
                dict(hermes_pin="0" * 40), dict(max_iterations=0)):
        try:
            bc.precontact_gate(**_gate_fields(**bad))
        except bc.GateRefused:
            pass
        else:
            raise AssertionError("gate failed to refuse %r" % (bad,))
    tmp, log, home = _reserve("q1-inv")
    calls = []

    def factory():
        calls.append("factory")
        def call(prompt):
            assert bc.recover(log, "q1-inv") == "INDETERMINATE"
            calls.append("call")
            return {b: 0 for b in bc.BUCKETS}
        return call

    usage = bc.invoke_bounded(log_path=log, invocation_id="q1-inv", home=home,
                              prompt="hi", provider_factory=factory)
    assert usage == {b: 0 for b in bc.BUCKETS}
    assert calls == ["factory", "call"]
    try:
        bc.invoke_bounded(log_path=log, invocation_id="q1-inv", home=home,
                          prompt="hi", provider_factory=factory)
    except bc.GateRefused:
        pass
    else:
        raise AssertionError("second invocation not refused")
    assert calls == ["factory", "call"]


def case_q1_concurrent_one_shot():
    """Two real processes race one reservation at a pipe barrier: exactly one
    provider-side sentinel fires, exactly one CONTACT_ARMED lands, the loser
    refuses pre-provider, the log stays parseable. No timing sleeps."""
    tmp, log, home = _reserve("q1-race")
    sentinel = tmp / "sentinel.log"
    barrier_r, barrier_w = os.pipe()

    def child_main():
        os.close(barrier_w)
        assert os.read(barrier_r, 1) == b""
        os.close(barrier_r)
        def factory():
            def call(prompt):
                with open(sentinel, "a", encoding="utf-8") as handle:
                    handle.write("provider-entry\n")
                return {b: 0 for b in bc.BUCKETS}
            return call
        try:
            bc.invoke_bounded(log_path=log, invocation_id="q1-race", home=home,
                              prompt="hi", provider_factory=factory)
        except bc.GateRefused:
            os._exit(42)
        os._exit(0)

    pids = []
    for _ in range(2):
        pid = os.fork()
        if pid == 0:
            try:
                child_main()
            finally:
                os._exit(1)
        pids.append(pid)
    os.close(barrier_w)
    os.close(barrier_r)
    codes = sorted(os.waitstatus_to_exitcode(os.waitpid(p, 0)[1]) for p in pids)
    assert codes == [0, 42], codes
    assert sentinel.read_text(encoding="utf-8").splitlines() == ["provider-entry"]
    recs = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    assert sum(1 for r in recs if r.get("state") == "CONTACT_ARMED"
               and r.get("invocation_id") == "q1-race") == 1


def case_q1_tool_surface_resolves_empty():
    """The production toolset selection resolves to exactly the frozen surface.

    Offline: drives the pinned Hermes toolset-resolution code path that
    _build_agent triggers (model_tools.get_tool_definitions with the exact
    production selection, pinned commit verified before import), plus the
    RESERVED binding. Asserts resolved tool defs == []. No provider/model
    call; the model is never offered any tool, so no tool can initiate an
    auxiliary model/provider call outside C_calls."""
    assert list(bc.TOOLSETS_ENABLED) == []
    assert list(bc.FROZEN_TOOL_NAMES) == []
    bound = bc.precontact_gate(**_gate_fields())
    assert bound["toolsets_enabled"] == [] and bound["tool_names"] == []
    pin_root = Path.home() / "workspace" / "vendor" / "hermes-pin"
    out = subprocess.run(["git", "-C", str(pin_root), "rev-parse", "HEAD"],
                         capture_output=True, text=True, check=True)
    assert out.stdout.strip() == bc.HERMES_PIN, "Hermes pin checkout mismatch"
    sys.path.insert(0, str(pin_root))
    try:
        from model_tools import get_tool_definitions
        resolved = get_tool_definitions(
            enabled_toolsets=list(bc.TOOLSETS_ENABLED),
            disabled_toolsets=None, quiet_mode=True)
    finally:
        sys.path.remove(str(pin_root))
    assert resolved == [], resolved


def _surface_agent(names):
    class _A:
        pass
    agent = _A()
    agent.tools = [{"type": "function", "function": {"name": n}} for n in names]
    agent.valid_tool_names = set(names)
    return agent


def case_q1_tool_surface_refusals():
    """The fail-closed surface check accepts the frozen empty surface and
    refuses any other: at minimum vision_analyze (auxiliary vision router),
    image_generate (FAL image-model provider call), delegate_task (subagent
    forks), a mixed model-calling surface, and any unrelated tool. Offline
    stand-ins; no provider/model call."""
    bc._assert_frozen_tool_surface(_surface_agent([]))
    for bad in (["vision_analyze"], ["image_generate"], ["delegate_task"],
                ["vision_analyze", "image_generate"], ["read_file"]):
        try:
            bc._assert_frozen_tool_surface(_surface_agent(bad))
        except bc.GateRefused:
            pass
        else:
            raise AssertionError("tool surface %r not refused" % (bad,))


def case_q1_tool_surface_binding_reverified():
    """RESERVED binds the frozen tool surface; a drifted binding refuses
    before CONTACT_ARMED and the factory is never entered. Offline."""
    tmp, log, home = _reserve("q1-surface")
    recs = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    reserved = [r for r in recs if r.get("state") == "RESERVED"][0]
    assert reserved["toolsets_enabled"] == [] and reserved["tool_names"] == []
    tampered = dict(reserved, toolsets_enabled=["vision"],
                    tool_names=["vision_analyze"])
    log.write_text(json.dumps(tampered, sort_keys=True) + "\n", encoding="utf-8")

    def factory():
        raise AssertionError("factory entered despite drifted tool surface")

    try:
        bc.invoke_bounded(log_path=log, invocation_id="q1-surface", home=home,
                          prompt="hi", provider_factory=factory)
    except bc.GateRefused:
        pass
    else:
        raise AssertionError("drifted tool surface not refused pre-arm")
    assert bc.recover(log, "q1-surface") == "PROVEN_NOT_ENTERED"


def _ambient_with_sentinel_plugin():
    """An ambient operator profile carrying sentinel plugin configuration.

    Its config.yaml enables a sentinel plugin and its plugins/ directory
    exists. If this profile ever became the active Hermes home during the
    bounded provider window, pinned plugin discovery would see it. The
    fixture never executes plugin discovery itself (no third-party code
    loads); it asserts the home-selection seam only.
    """
    ambient = _tmp()
    (ambient / "plugins").mkdir(parents=True)
    (ambient / "config.yaml").write_text(
        "plugins:\n  enabled:\n    - sentinel-plugin\n", encoding="utf-8")
    return ambient


def _run_production_window(invocation, ambient, agent_cls):
    """Drive the REAL production_provider_factory through invoke_bounded
    with _build_agent stubbed to a fake agent (no Hermes construction, no
    network, no model call). The fake run_conversation records the
    environment the production provider closure actually executes under.
    Returns (seen, usage_or_exception)."""
    tmp, log, home = _reserve(invocation)
    seen = {}

    class _FakeAgent(agent_cls):
        def run_conversation(self, prompt):
            seen["home"] = os.environ.get("HERMES_HOME")
            seen["project_plugins"] = os.environ.get(
                "HERMES_ENABLE_PROJECT_PLUGINS")
            return super().run_conversation(prompt)

    real_build = bc._build_agent
    bc._build_agent = lambda *a, **k: _FakeAgent()
    saved = {k: os.environ.get(k)
             for k in ("HERMES_HOME", "HERMES_ENABLE_PROJECT_PLUGINS")}
    os.environ["HERMES_HOME"] = str(ambient)
    os.environ["HERMES_ENABLE_PROJECT_PLUGINS"] = "1"
    try:
        factory = bc.production_provider_factory(
            log_path=log, invocation_id=invocation,
            hermes_path=tmp / "hermes", home=home, api_key="fake")
        try:
            usage = bc.invoke_bounded(
                log_path=log, invocation_id=invocation, home=home,
                prompt="hi", provider_factory=factory)
        except Exception as exc:  # noqa: BLE001 - the raise-path is the assertion
            return seen, exc, saved, tmp, home
        return seen, usage, saved, tmp, home
    finally:
        bc._build_agent = real_build
        for key, val in saved.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


class _RecordingAgent:
    def run_conversation(self, prompt):
        return {b: 0 for b in bc.BUCKETS}


class _RaisingAgent:
    def run_conversation(self, prompt):
        raise RuntimeError("synthetic provider failure")


def case_q1_runtime_home_scoped():
    """The provider window executes under the isolated bounded-call home.

    Construction and provider execution both observe the SAME isolated home
    bound before RESERVED; the ambient profile (carrying sentinel plugin
    config) is restored only after the provider closure returns. A second
    run proves restoration also happens when the closure raises. Offline:
    fake provider behind invoke_bounded, no network, no model call.
    """
    ambient = _ambient_with_sentinel_plugin()
    # The seam itself: both the construction window (inside _build_agent)
    # and the provider window (inside the production call closure) run
    # through _isolated_home, so assert its contract directly.
    home_probe = _tmp() / "probe-home"
    home_probe.mkdir(parents=True)
    before = os.environ.get("HERMES_HOME")
    with bc._isolated_home(home_probe):
        assert os.environ.get("HERMES_HOME") == str(home_probe)
        assert os.environ.get("HERMES_ENABLE_PROJECT_PLUGINS") is None
    assert os.environ.get("HERMES_HOME") == before
    seen, usage, saved, _, home = _run_production_window(
        "q1-home", ambient, _RecordingAgent)
    assert usage == {b: 0 for b in bc.BUCKETS}
    assert seen["home"] == str(home), seen
    assert seen["home"] != str(ambient), seen
    assert seen["project_plugins"] is None, seen
    assert os.environ.get("HERMES_HOME") == saved["HERMES_HOME"]
    assert (os.environ.get("HERMES_ENABLE_PROJECT_PLUGINS")
            == saved["HERMES_ENABLE_PROJECT_PLUGINS"])
    seen2, exc, saved2, _, home2 = _run_production_window(
        "q1-home-raise", ambient, _RaisingAgent)
    assert isinstance(exc, RuntimeError), exc
    assert seen2["home"] == str(home2), seen2
    assert seen2["home"] != str(ambient), seen2
    assert os.environ.get("HERMES_HOME") == saved2["HERMES_HOME"]
    assert (os.environ.get("HERMES_ENABLE_PROJECT_PLUGINS")
            == saved2["HERMES_ENABLE_PROJECT_PLUGINS"])


def case_q1_runtime_home_negative():
    """A sentinel ambient plugin profile can never become the active
    runtime profile during the bounded provider window.

    The ambient HERMES_HOME enables a sentinel plugin; the production
    provider closure must still execute under the isolated home, so pinned
    lifecycle-hook dispatch (which resolves the plugin manager from the
    current home) can never discover the sentinel. Home-selection seam
    only; no plugin code is loaded.
    """
    ambient = _ambient_with_sentinel_plugin()
    seen, usage, saved, tmp, home = _run_production_window(
        "q1-homeneg", ambient, _RecordingAgent)
    assert usage == {b: 0 for b in bc.BUCKETS}
    assert seen["home"] == str(home), seen
    assert seen["home"] != str(ambient), seen
    assert (ambient / "config.yaml").read_text(encoding="utf-8").find(
        "sentinel-plugin") >= 0
    assert seen["project_plugins"] is None, seen


def case_q2_pre_arm_death_proven_not_entered():
    """Real SIGKILL after durable RESERVED, before CONTACT_ARMED."""
    tmp, log, home = _reserve("q2-inv")

    def child():
        pass  # RESERVED already durable; dies before any invocation

    _kill_child_after(child)
    assert bc.recover(log, "q2-inv") == "PROVEN_NOT_ENTERED"
    try:
        bc.recover(log, "no-such-invocation")
    except bc.GateRefused:
        pass
    else:
        raise AssertionError("unknown invocation classified instead of error")


def case_q3_post_arm_death_indeterminate():
    """Real SIGKILL inside the provider window, after CONTACT_ARMED."""
    tmp, log, home = _reserve("q3-inv")

    def child():
        def factory():
            def call(prompt):
                os.kill(os.getpid(), signal.SIGKILL)
            return call
        bc.invoke_bounded(log_path=log, invocation_id="q3-inv", home=home,
                          prompt="hi", provider_factory=factory)

    _kill_child_after(child)
    assert bc.recover(log, "q3-inv") == "INDETERMINATE"


def case_q4_signed_reconciliation():
    """Only correctly invocation-bound, untampered signatures verify."""
    tmp, log, home = _reserve("q4-inv")
    usage = {"input_tokens": 1000, "cache_read_tokens": 200000,
             "cache_write_tokens": 500, "output_tokens": 300}

    def factory():
        return lambda prompt: dict(usage)

    got = bc.invoke_bounded(log_path=log, invocation_id="q4-inv", home=home,
                            prompt="hi", provider_factory=factory)
    assert got == usage
    auth = bc.ReconciliationAuthority(tmp / "rec.key")
    record = auth.reconcile(invocation_id="q4-inv", log_path=log, usage=got)
    payload = auth.verify(record, "q4-inv")
    assert payload["outcome"] == "EXECUTED"
    assert payload["prompt_tokens"] == 201500
    assert payload["envelope_violation"] is False
    tampered = {"alg": "HMAC-SHA256",
                "payload": dict(record["payload"], observed_charge="0.01"),
                "signature": record["signature"]}
    for bad, label in ((tampered, "tampered"), ({"payload": record["payload"]}, "unsigned"),
                       ("not-a-record", "non-mapping")):
        try:
            auth.verify(bad, "q4-inv")
        except bc.EvidenceRejected:
            pass
        else:
            raise AssertionError("%s record verified" % label)
    try:
        auth.verify(record, "other-invocation")
    except bc.EvidenceRejected:
        pass
    else:
        raise AssertionError("wrong-invocation record verified")
    assert bc.resolve(log, "q4-inv", auth)["invocation_id"] == "q4-inv"


def _hermes_result_fixture(**overrides):
    """Offline synthetic shaped exactly like pinned turn_finalizer output.

    Pinned agent/turn_finalizer.py builds the result dict with the billing
    counters as top-level keys (input/output/cache_read/cache_write). No
    paid call is needed to prove extraction against this shape.
    """
    result = {
        "final_response": "done",
        "last_reasoning": None,
        "messages": [],
        "api_calls": 3,
        "completed": True,
        "turn_exit_reason": "completed",
        "failed": False,
        "partial": False,
        "interrupted": False,
        "response_transformed": False,
        "pre_transform_response": None,
        "response_previewed": False,
        "model": "gpt-5.6-sol",
        "provider": "openai-api",
        "base_url": "",
        "input_tokens": 12345,
        "output_tokens": 678,
        "cache_read_tokens": 91011,
        "cache_write_tokens": 1213,
        "reasoning_tokens": 0,
        "prompt_tokens": 104569,
        "completion_tokens": 678,
        "total_tokens": 105247,
        "last_prompt_tokens": 0,
        "estimated_cost_usd": 0.0,
        "cost_status": "ok",
        "cost_source": "live",
        "service_tier": None,
        "session_id": "fixture",
    }
    result.update(overrides)
    return result


def case_q5_accounting_and_over_envelope():
    """272K boundary derived mechanically from buckets; over-envelope preserved."""
    at = {"input_tokens": 272000, "cache_read_tokens": 0,
          "cache_write_tokens": 0, "output_tokens": 0}
    over_line = {"input_tokens": 272001, "cache_read_tokens": 0,
                 "cache_write_tokens": 0, "output_tokens": 0}
    assert bc.price_usage(at) == Decimal("1.088")
    assert bc.price_usage(over_line) == Decimal("2.176008")
    cache_heavy = {"input_tokens": 0, "cache_read_tokens": 200000,
                   "cache_write_tokens": 73000, "output_tokens": 10}
    assert bc.price_usage(cache_heavy) == Decimal("0.8903")
    extracted = bc._extract_usage(_hermes_result_fixture())
    assert extracted == {"input_tokens": 12345, "cache_read_tokens": 91011,
                         "cache_write_tokens": 1213, "output_tokens": 678}
    assert bc.price_usage(extracted) == bc.price_usage(
        {"input_tokens": 12345, "cache_read_tokens": 91011,
         "cache_write_tokens": 1213, "output_tokens": 678})
    missing = _hermes_result_fixture()
    del missing["cache_write_tokens"]
    for bad in (missing,
                _hermes_result_fixture(input_tokens=True),
                _hermes_result_fixture(output_tokens=-1),
                _hermes_result_fixture(cache_read_tokens=1.5),
                "not-a-mapping"):
        try:
            bc._extract_usage(bad)
        except bc.GateRefused:
            pass
        else:
            raise AssertionError("extraction failed closed on %r" % (bad,))
    tmp, log, home = _reserve("q5-inv", max_iterations=1, budget=Decimal("200"))
    big = {"input_tokens": 0, "cache_read_tokens": 0,
           "cache_write_tokens": 0, "output_tokens": 10 ** 9}

    def factory():
        return lambda prompt: dict(big)

    got = bc.invoke_bounded(log_path=log, invocation_id="q5-inv", home=home,
                            prompt="hi", provider_factory=factory)
    auth = bc.ReconciliationAuthority(tmp / "rec.key")
    record = auth.reconcile(invocation_id="q5-inv", log_path=log, usage=got)
    payload = record["payload"]
    assert payload["outcome"] == "EXECUTED"
    assert payload["envelope_violation"] is True
    assert Decimal(payload["observed_charge"]) == Decimal("30000")
    assert Decimal(payload["observed_charge"]) > Decimal(payload["r_i"])
    assert payload["r_i"] == "160.76256"


def case_q6_no_self_release():
    """Provider-shaped failures cannot release a CONTACT_ARMED reservation."""
    tmp, log, home = _reserve("q6-inv")
    auth = bc.ReconciliationAuthority(tmp / "rec.key")

    class InfrastructureHalt(Exception):
        """PAYBACK-003 halt shape: must stay INDETERMINATE after CONTACT_ARMED."""

    def factory():
        def call(prompt):
            raise InfrastructureHalt("halt inside provider window")
        return call

    try:
        bc.invoke_bounded(log_path=log, invocation_id="q6-inv", home=home,
                          prompt="hi", provider_factory=factory)
    except InfrastructureHalt:
        pass
    else:
        raise AssertionError("provider halt swallowed")
    assert bc.recover(log, "q6-inv") == "INDETERMINATE"
    for fake in ({"invocation_id": "q6-inv", "outcome": "PROVEN_NOT_ENTERED"},
                 InfrastructureHalt("not entered")):
        try:
            auth.verify(fake, "q6-inv")
        except bc.EvidenceRejected:
            pass
        else:
            raise AssertionError("self-attestation released the reservation")
    assert bc.resolve(log, "q6-inv", auth) is None
    tmp2, log2, home2 = _reserve("q6-pre")
    try:
        auth.reconcile(invocation_id="q6-pre", log_path=log2,
                        usage={b: 0 for b in bc.BUCKETS})
    except bc.EvidenceRejected:
        pass
    else:
        raise AssertionError("reconcile signed without CONTACT_ARMED")


CASES = (case_q1_gate_and_r_i, case_q1_concurrent_one_shot,
         case_q1_tool_surface_resolves_empty, case_q1_tool_surface_refusals,
         case_q1_tool_surface_binding_reverified,
         case_q1_runtime_home_scoped, case_q1_runtime_home_negative,
         case_q2_pre_arm_death_proven_not_entered,
         case_q3_post_arm_death_indeterminate, case_q4_signed_reconciliation,
         case_q5_accounting_and_over_envelope, case_q6_no_self_release)
