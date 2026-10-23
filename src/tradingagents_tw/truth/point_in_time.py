from __future__ import annotations

from datetime import datetime
from tradingagents_tw.contracts import Evidence


class LookaheadViolation(ValueError):
    pass


def assert_point_in_time(evidence: Evidence, cutoff: datetime) -> None:
    """INV-01: only information availability is bounded by the analysis cutoff.

    A scheduled event can be published/observed before the cutoff while its
    event_time/effective_at lies in the future. That is not lookahead.
    """
    if cutoff.utcoffset() is None:
        raise LookaheadViolation("analysis cutoff must be timezone-aware")
    if evidence.published_at > cutoff:
        raise LookaheadViolation("published_at is after analysis cutoff")
    if evidence.observed_at > cutoff:
        raise LookaheadViolation("observed_at is after analysis cutoff")
