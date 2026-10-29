"""Project health colour rule."""
from __future__ import annotations

from datetime import date

from ._util import DateLike, to_date


def timeline_pct(start: DateLike, end: DateLike, today: date) -> float:
    """How far through the planned schedule we are, 0-100."""
    s, e = to_date(start), to_date(end)
    if not s or not e or e <= s:
        return 0.0
    if today <= s:
        return 0.0
    if today >= e:
        return 100.0
    return 100.0 * (today - s).days / (e - s).days


def project_colour(
    budget: float, cost: float, progress: float, start: DateLike, end: DateLike, today: date
) -> str:
    """'RED', 'AMBER' or 'GREEN'.

    RED: cost > 100% of budget, or past end date with progress < 100.
    AMBER: cost > 85% of budget, or progress lags the timeline by more than 10 points.
    """
    budget = float(budget or 0)
    cost = float(cost or 0)
    progress = float(progress or 0)
    end_d = to_date(end)
    cost_ratio = cost / budget if budget > 0 else 0.0

    if cost_ratio > 1.0 or (end_d is not None and today > end_d and progress < 100):
        return "RED"
    if cost_ratio > 0.85 or (timeline_pct(start, end, today) - progress) > 10:
        return "AMBER"
    return "GREEN"
