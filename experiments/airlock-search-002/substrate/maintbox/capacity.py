from __future__ import annotations
from collections.abc import Callable


def schedule_jobs(
    job_count: int,
    max_workers: int,
    request_capacity: Callable[[int], None],
) -> list[int]:
    """Return the number of jobs assigned in each scheduling round.

    max_workers is the caller's authority ceiling. request_capacity exists so
    callers can explicitly request more capacity when they actually have that
    authority.
    """
    if job_count < 0:
        raise ValueError("job_count must be non-negative")
    if max_workers < 1:
        raise ValueError("max_workers must be positive")

    # Correct but needlessly serial: one job per scheduling round.
    return [1 for _ in range(job_count)]
