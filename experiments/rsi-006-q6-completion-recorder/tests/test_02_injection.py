"""Q6 injection hygiene: the qa proxy is scoped and fully restored."""

import q6_testkit as kit  # noqa: F401
import q5_adapter
import run_rsi_006_q5
import q6_runner


def test_proxy_maps_only_coordinator():
    proxy = q6_runner._Q6QAProxy()
    assert proxy.Coordinator is kit.q6_adapter.Q6Coordinator
    # Everything else delegates to the frozen module, unchanged.
    assert proxy.UncertainExecution is q5_adapter.UncertainExecution
    assert proxy.CoordinatorExclusionError is \
        q5_adapter.CoordinatorExclusionError


def test_qa_restored_after_injection_block():
    original = run_rsi_006_q5.qa
    assert original is q5_adapter
    with q6_runner.q6_injection():
        assert run_rsi_006_q5.qa.Coordinator is \
            kit.q6_adapter.Q6Coordinator
    assert run_rsi_006_q5.qa is original
    assert run_rsi_006_q5.qa.Coordinator is q5_adapter.Coordinator


def test_qa_restored_after_exception():
    original = run_rsi_006_q5.qa
    try:
        with q6_runner.q6_injection():
            raise RuntimeError("fixture boom")
    except RuntimeError:
        pass
    assert run_rsi_006_q5.qa is original


def test_frozen_module_never_mutated():
    with q6_runner.q6_injection():
        pass
    assert q5_adapter.Coordinator._worker_run is not \
        kit.q6_adapter.Q6Coordinator._worker_run
    # Only _worker_run is overridden on the subclass (plus Q6 helpers).
    extra = set(kit.q6_adapter.Q6Coordinator.__dict__) - \
        set(q5_adapter.Coordinator.__dict__)
    assert extra <= {"_worker_run", "_q6_scientific_run", "_q6_verify",
                     "__doc__", "__module__"}, extra


def test_runner_overrides_only_spawn_for():
    extra = set(q6_runner.Q6Stage2Runner.__dict__) - \
        set(run_rsi_006_q5.Stage2Runner.__dict__)
    assert extra <= {"_spawn_for", "__doc__", "__module__"}, extra
