from datetime import datetime, timezone
import pytest
from pydantic import ValidationError
from tradingagents_tw.contracts import Evidence, EvidenceStatus, GateStatus
from tradingagents_tw.truth import LookaheadViolation, assert_point_in_time, assess_evidence

UTC = timezone.utc


def ev(published: int, observed: int, *, effective: int | None = None) -> Evidence:
    return Evidence(
        evidence_id="e1",
        evidence_type="OHLCV",
        source="TWSE",
        published_at=datetime(2026, 10, 23, published, tzinfo=UTC),
        observed_at=datetime(2026, 10, 23, observed, tzinfo=UTC),
        effective_at=(
            datetime(2026, 10, 23, effective, tzinfo=UTC)
            if effective is not None
            else None
        ),
        content_hash="abc",
        revision_id="r1",
        status=EvidenceStatus.VERIFIED,
        payload={"close": 100},
    )


def test_point_in_time_passes_when_known_by_cutoff():
    assert_point_in_time(ev(6, 7), datetime(2026, 10, 23, 8, tzinfo=UTC))


def test_point_in_time_blocks_future_evidence():
    with pytest.raises(LookaheadViolation):
        assert_point_in_time(ev(9, 9), datetime(2026, 10, 23, 8, tzinfo=UTC))


def test_known_future_effective_event_is_not_lookahead():
    evidence = ev(6, 7, effective=10)
    assert_point_in_time(evidence, datetime(2026, 10, 23, 8, tzinfo=UTC))
    assert evidence.effective_at == datetime(2026, 10, 23, 10, tzinfo=UTC)


def test_evidence_rejects_naive_information_timestamps():
    with pytest.raises(ValidationError, match="timezone-aware"):
        Evidence(
            evidence_id="naive",
            evidence_type="OHLCV",
            source="TWSE",
            published_at=datetime(2026, 10, 23, 6),
            observed_at=datetime(2026, 10, 23, 7),
            content_hash="abc",
            revision_id="r1",
            status=EvidenceStatus.VERIFIED,
            payload={},
        )


def test_critical_missing_cannot_be_averaged_away():
    result = assess_evidence(
        coverage=99,
        freshness="PASS",
        provenance="PASS",
        critical_missing=("LATEST_MATERIAL_EVENT",),
    )
    assert result.decision_gate == GateStatus.DEGRADED


def test_unresolved_conflict_blocks():
    result = assess_evidence(
        coverage=100,
        freshness="PASS",
        provenance="PASS",
        unresolved_conflicts=("CLOSE_PRICE_MISMATCH",),
    )
    assert result.decision_gate == GateStatus.BLOCKED
