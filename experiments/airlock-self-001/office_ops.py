from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal


def first_over_budget(values: Iterable[int], limit: int) -> int | None:
    """Return the first index whose cumulative total exceeds limit."""
    total = 0
    found: int | None = None
    for index, value in enumerate(values):
        total += value
        if total > limit and found is None:
            found = index
    return found


def invoice_total(cents: Iterable[int]) -> int:
    """Return a stable integer total for invoice line items."""
    return sum(cents)


def discount_amount(subtotal_cents: int, basis_points: int) -> int:
    """Round a basis-point discount down to whole cents."""
    return (subtotal_cents * basis_points) // 10_000
