from __future__ import annotations

from datetime import datetime
from tradingagents_tw.contracts import Evidence


class LookaheadViolation(ValueError):
    pass


def assert_point_in_time(evidence: Evidence, cutoff: datetime) -> None:
    """INV-01: evidence must have been published and observed by the cutoff."""
    if evidence.published_at > cutoff:
        raise LookaheadViolation("published_at is after analysis cutoff")
    if evidence.observed_at > cutoff:
        raise LookaheadViolation("observed_at is after analysis cutoff")
    if evidence.effective_at and evidence.effective_at > cutoff:
        raise LookaheadViolation("effective_at is after analysis cutoff")
