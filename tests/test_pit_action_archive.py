"""Offline synthetic PIT archive tests; not proof of a historical exchange archive."""
from datetime import date, datetime, timedelta
import json
from zoneinfo import ZoneInfo

import pytest

from tradingagents_tw.truth.archive import (
    AppendOnlyActionArchive, build_attestation, capture_action, verify_archive_coverage,
)

TZ = ZoneInfo("Asia/Taipei")
START, END = date(2026, 10, 22), date(2026, 10, 23)
CUTOFF = datetime(2026, 10, 23, 20, tzinfo=TZ)


def action(*, revision="r1", supersedes=None, observed_hour=18, payload=None):
    observed = datetime(2026, 10, 23, observed_hour, tzinfo=TZ)
    return capture_action(
        market="TWSE", symbol="2330", source="TWSE_OPENAPI", event_key="exdiv:2330:2026-10-23",
        revision_id=revision, supersedes_revision_id=supersedes,
        raw_payload=payload or {"event_date": "2026-10-23", "cash_dividend": 2},
        published_at=observed - timedelta(minutes=10), clock=lambda: observed,
    )


def manifest(records=(), *, coverage="COMPLETE", capture_start=None, observed=None):
    return build_attestation(
        market="TWSE", symbol="2330", start_date=START, end_date=END,
        analysis_cutoff=CUTOFF,
        capture_started_at=capture_start or datetime(2026, 10, 21, tzinfo=TZ),
        capture_ended_at=CUTOFF, observed_at=observed or CUTOFF,
        coverage=coverage, record_hashes=tuple(sorted(r.record_hash for r in records)),
        attestation_id="fixture-independent-attestor",
    )


def verify(m, records=(), trusted=True):
    return verify_archive_coverage(
        m, records, market="TWSE", symbol="2330", start=START, end=END, cutoff=CUTOFF,
        trusted_attestation=(lambda _: True) if trusted else None,
    )


def test_synthetic_complete_no_action_requires_external_attestation():
    m = manifest()
    assert verify(m) == ()
    assert m.attestation_hash == manifest().attestation_hash
    with pytest.raises(ValueError, match="unverified"):
        verify(m, trusted=False)


def test_append_only_capture_integrity_and_valid_action(tmp_path):
    archive = AppendOnlyActionArchive(tmp_path)
    first = action()
    assert archive.append(first) == first.record_hash
    assert archive.append(first) == first.record_hash
    assert archive.read(first.record_hash) == first
    assert verify(manifest((first,)), (first,)) == (first,)
    path = archive.objects / (first.record_hash + ".json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["raw_payload"]["cash_dividend"] = 999
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        archive.read(first.record_hash)


def test_linear_revision_resolves_only_latest():
    first = action()
    second = action(revision="r2", supersedes="r1", observed_hour=19,
                    payload={"event_date": "2026-10-23", "cash_dividend": 3})
    assert verify(manifest((first, second)), (first, second)) == (second,)


@pytest.mark.parametrize("failure", ["partial", "unknown", "late", "gap", "untrusted", "missing", "wrong-board"])
def test_coverage_fails_closed(failure):
    first = action()
    m = manifest((first,))
    records = (first,)
    if failure in ("partial", "unknown"):
        m = manifest((first,), coverage=failure.upper())
    elif failure == "late":
        records = (action(observed_hour=21),)
        m = manifest(records)
    elif failure == "gap":
        m = manifest((first,), capture_start=datetime(2026, 10, 22, 1, tzinfo=TZ))
    elif failure == "missing":
        records = ()
    elif failure == "wrong-board":
        first = action()
        records = (first.model_copy(update={"market": "TPEX"}),)
    with pytest.raises(ValueError):
        verify(m, records, trusted=failure != "untrusted")


@pytest.mark.parametrize("mutation", ["duplicate-revision", "fork", "missing-root", "changed-date"])
def test_conflicting_revision_lineage_blocks(mutation):
    first = action()
    if mutation == "duplicate-revision":
        second = action(revision="r1", observed_hour=19,
                        payload={"event_date": "2026-10-23", "cash_dividend": 3})
    elif mutation == "fork":
        second = action(revision="r2", supersedes="wrong", observed_hour=19)
    elif mutation == "missing-root":
        second = action(revision="r2", supersedes="r1", observed_hour=19)
        first = second
        records = (second,)
        with pytest.raises(ValueError, match="missing initial"):
            verify(manifest(records), records)
        return
    else:
        second = action(revision="r2", supersedes="r1", observed_hour=19,
                        payload={"event_date": "2026-10-22", "cash_dividend": 3})
    records = (first, second)
    with pytest.raises(ValueError):
        verify(manifest(records), records)


def test_capture_cannot_claim_future_publication_or_naive_clock():
    with pytest.raises(ValueError, match="publication"):
        capture_action(market="TWSE", symbol="2330", source="TWSE_OPENAPI",
                       event_key="x", revision_id="r1", raw_payload={"event_date": "2026-10-23"},
                       published_at=CUTOFF + timedelta(hours=1),
                       clock=lambda: CUTOFF)
    with pytest.raises(ValueError, match="timezone-aware"):
        capture_action(market="TWSE", symbol="2330", source="TWSE_OPENAPI",
                       event_key="x", revision_id="r1", raw_payload={},
                       clock=lambda: datetime(2026, 10, 23, 18))
