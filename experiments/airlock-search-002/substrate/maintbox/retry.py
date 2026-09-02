from __future__ import annotations

def retry_delays(attempts: int, base: float = 0.5) -> list[float]:
    if attempts <= 0:
        return [base]
    return [base * (2 ** i) for i in range(attempts)]
