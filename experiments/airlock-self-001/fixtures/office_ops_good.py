from __future__ import annotations

from collections.abc import Iterable


def first_over_budget(values: Iterable[int], limit: int) -> int | None:
    total = 0
    for index, value in enumerate(values):
        total += value
        if total > limit:
            return index
    return None


def invoice_total(cents: Iterable[int]) -> int:
    return sum(cents)


def discount_amount(subtotal_cents: int, basis_points: int) -> int:
    return (subtotal_cents * basis_points) // 10_000
