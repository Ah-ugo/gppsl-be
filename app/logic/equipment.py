"""Equipment rules: deploy blocking, utilisation and overdue returns."""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from ._util import DateLike, to_date

BLOCKING_STATUSES_MESSAGE = {
    "deployed": "Equipment is already deployed",
    "in_transit": "Equipment is in transit",
    "maintenance": "Equipment is in maintenance",
}


def service_hours_remaining(equipment: dict[str, Any]) -> float:
    """Hours left before the next service is due (negative when overdue)."""
    interval = float(equipment.get("service_interval_hours") or 0)
    used = float(equipment.get("run_hours") or 0) - float(equipment.get("last_service_hours") or 0)
    return interval - used


def can_deploy(
    equipment: dict[str, Any],
    today: date,
    bookings: list[dict[str, Any]],
    start: DateLike = None,
    end: DateLike = None,
) -> list[str]:
    """Return a list of human-readable blocking reasons. Empty list means OK to deploy.

    bookings: other bookings for this item, each with start_date and expected_return
    (an open booking with no expected_return is treated as running forever).
    start/end: requested window; defaults to today..today.
    """
    reasons: list[str] = []

    status = equipment.get("status", "available")
    if status != "available":
        reasons.append(BLOCKING_STATUSES_MESSAGE.get(status, f"Equipment status is '{status}', not available"))

    interval = equipment.get("service_interval_hours")
    if interval and service_hours_remaining(equipment) <= 0:
        used = float(equipment.get("run_hours") or 0) - float(equipment.get("last_service_hours") or 0)
        reasons.append(
            f"Service overdue: {used:.0f} run hours since last service (interval {float(interval):.0f}). Cannot deploy"
        )

    for cert in equipment.get("certificates") or []:
        expiry = to_date(cert.get("expiry_date"))
        if expiry is not None and expiry < today:
            reasons.append(
                f"Certificate '{cert.get('name', 'unnamed')}' expired on {expiry.strftime('%d/%m/%Y')}"
            )

    window_start = to_date(start) or today
    window_end = to_date(end) or window_start
    for booking in bookings or []:
        b_start = to_date(booking.get("start_date"))
        b_end = to_date(booking.get("expected_return")) or date.max
        if booking.get("actual_return"):
            continue
        if b_start is None:
            continue
        if b_start <= window_end and window_start <= b_end:
            reasons.append(
                f"Overlapping booking {b_start.strftime('%d/%m/%Y')} to "
                f"{'open-ended' if b_end == date.max else b_end.strftime('%d/%m/%Y')}"
            )
    return reasons


def utilisation_pct(items: list[dict[str, Any]]) -> float:
    """Percentage of equipment currently deployed (rounded to 1 dp). Empty list gives 0."""
    if not items:
        return 0.0
    deployed = sum(1 for i in items if i.get("status") == "deployed")
    return round(100.0 * deployed / len(items), 1)


def overdue_rentals(rentals: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """Rentals not yet returned whose expected return date is before today."""
    out = []
    for rental in rentals:
        if rental.get("actual_return"):
            continue
        expected = to_date(rental.get("expected_return"))
        if expected is not None and expected < today:
            out.append(rental)
    return out


def rental_income(rate_type: str, rate: float, start: DateLike, end: DateLike) -> float:
    """Income for a rental. rate_type is 'daily', 'weekly', 'monthly' or 'fixed'.

    Days are counted inclusively with a minimum of one day.
    """
    s, e = to_date(start), to_date(end)
    days = max(1, (e - s).days + 1) if s and e else 1
    if rate_type == "daily":
        return round(rate * days, 2)
    if rate_type == "weekly":
        return round(rate * (-(-days // 7)), 2)
    if rate_type == "monthly":
        return round(rate * (-(-days // 30)), 2)
    return round(float(rate), 2)
