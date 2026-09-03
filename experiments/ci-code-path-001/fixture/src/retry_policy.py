"""Small retry policy with the deliberate boundary bug used by CI-CODE-PATH-001."""


def may_retry(failures_seen: int, retry_budget: int) -> bool:
    """Return whether another attempt remains after ``failures_seen`` failures."""
    if failures_seen < 1:
        raise ValueError("failures_seen must include the initial failed attempt")
    if retry_budget < 0:
        raise ValueError("retry_budget must be non-negative")
    return failures_seen <= retry_budget + 1

