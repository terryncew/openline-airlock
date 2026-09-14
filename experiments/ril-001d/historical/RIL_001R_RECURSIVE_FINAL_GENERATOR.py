"""Intentionally mediocre search-policy generator for RIL-001.

This policy does not edit code. It chooses up to five receiver-defined search tactics that the
protected worker turns into bounded guidance for the live agent. Accepted changes to this file
therefore change how later live-agent opportunities search for improvements.
"""
from __future__ import annotations


def choose_tactics(context):
    """Choose a focused workflow from the kind of evidence in the request."""
    text = str(context).lower()
    if any(term in text for term in ("latency", "throughput", "hot path", "slow", "allocation")):
        return ["inspect_repo", "run_baseline", "measure_hotspot", "small_patch", "preserve_invariants"]
    if any(term in text for term in ("intermittent", "nondeterministic", "timing", "sporadic", "race")):
        return ["inspect_repo", "run_baseline", "trace_failure", "adversarial_check", "preserve_invariants"]
    if any(term in text for term in ("upgrade", "schema migration", "format transition", "deprecation", "version boundary")):
        return ["inspect_repo", "read_docs", "read_tests", "compare_history", "preserve_invariants"]
    if any(term in text for term in ("constraint", "contract", "public api", "release promise", "migration rule")):
        return ["inspect_repo", "read_docs", "compare_history", "preserve_invariants", "small_patch"]
    if any(term in text for term in ("regression", "edge case", "unexpected", "parser bug", "wrong branch")):
        return ["inspect_repo", "run_baseline", "read_tests", "trace_failure", "adversarial_check"]
    return ["inspect_repo", "run_baseline", "read_tests", "small_patch", "preserve_invariants"]
