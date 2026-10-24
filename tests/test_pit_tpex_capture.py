"""Synthetic TPEx prospective-capture tests; never claim real PIT completeness."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tradingagents_tw.truth.capture_operator import capture_poll
from tradingagents_tw.truth.tpex_capture_operator import (
    AppendOnlyTPEXPollJournal,
    audit_tpex_poll_health,
    capture_tpex_poll,
)
from tradingagents_tw.truth.tpex_feed_capture import (
    AppendOnlyTPEXFeedArchive,
    MAX_RESPONSE_BYTES,
    TPEX_EXRIGHT_PREPOST_URL,
    capture_tpex_feed,
)

BASE = datetime(2026, 10, 24, 1, tzinfo=timezone.utc)


def tpex_row():
    return {
        "ExRrightsExDividendDate": "1151027",
        "SecuritiesCompanyCode": "6488",
        "CompanyName": "環球晶",
        "ExRrightsExDividend": "除息",
        "StockDividendRatio": "0.00000000",
        "SubscriptionRatioToNewSharesIssued": "0.00000000",
        "SubscriptionPricePerShare": "0.00",
        "CashDividend": "5.00000000",
        "AllocatedForPublicUnderwriting": "0",
        "SubscribedByEmployees": "0",
        "SubscribedByExistingShareholders": "0",
        "SubscribedProRataInThousandShares": "0.00000000",
    }


def body(rows=None):
    return json.dumps(rows if rows is not None else [tpex_row()],
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def test_tpex_exact_raw_bytes_and_independent_archive(tmp_path):
    raw = body()
    record = capture_tpex_feed(
        AppendOnlyTPEXFeedArchive(tmp_path),
        fetch_bytes=lambda: raw,
        clock=lambda: BASE,
    )
    assert record.endpoint == TPEX_EXRIGHT_PREPOST_URL
    assert record.source == "TPEX_OPENAPI"
    assert record.raw_bytes() == raw
    assert AppendOnlyTPEXFeedArchive(tmp_path).read(record.receipt_hash) == record
    assert (tmp_path / "tpex-feed-observations").is_dir()
    assert not (tmp_path / "feed-observations").exists()


def test_tpex_empty_array_is_observation_not_coverage(tmp_path):
    record = capture_tpex_feed(
        AppendOnlyTPEXFeedArchive(tmp_path),
        fetch_bytes=lambda: b"[]",
        clock=lambda: BASE,
    )
    assert record.raw_bytes() == b"[]"
    assert not hasattr(record, "coverage")
    assert not hasattr(record, "published_at")


@pytest.mark.parametrize("mutator", [
    lambda row: {k: v for k, v in row.items() if k != "SecuritiesCompanyCode"},
    lambda row: {**row, "CompanyName": ""},
    lambda row: {**row, "ExRrightsExDividendDate": "1150230"},
    lambda row: {**row, "ExRrightsExDividend": ""},
    lambda row: {k: v for k, v in row.items() if k != "CashDividend"},
    lambda row: {**row, "StockDividendRatio": None},
])
def test_tpex_schema_errors_never_write_success_receipt(tmp_path, mutator):
    archive = AppendOnlyTPEXFeedArchive(tmp_path)
    with pytest.raises(ValueError):
        capture_tpex_feed(
            archive,
            fetch_bytes=lambda: body([mutator(tpex_row())]),
            clock=lambda: BASE,
        )
    assert list(archive.objects.glob("*.json")) == []


@pytest.mark.parametrize("raw", [
    b"", b"{}", b"[1]", b'[{"error":"rate limited"}]', b"\xff",
    b"x" * (MAX_RESPONSE_BYTES + 1),
])
def test_tpex_invalid_envelopes_fail_closed(tmp_path, raw):
    archive = AppendOnlyTPEXFeedArchive(tmp_path)
    with pytest.raises(ValueError):
        capture_tpex_feed(archive, fetch_bytes=lambda: raw, clock=lambda: BASE)
    assert list(archive.objects.glob("*.json")) == []


def test_tpex_poll_chain_and_health_are_source_local(tmp_path):
    first = capture_tpex_poll(tmp_path, fetch_bytes=lambda: body(), clock=lambda: BASE)
    second_time = BASE + timedelta(hours=24)
    second = capture_tpex_poll(
        tmp_path, fetch_bytes=lambda: body(), clock=lambda: second_time
    )
    assert first.cadence_state == "NO_BASELINE"
    assert second.cadence_state == "OBSERVED"
    assert second.previous_poll_hash == first.poll_hash
    health = audit_tpex_poll_health(
        tmp_path, as_of=second_time + timedelta(hours=1)
    )
    assert health["status"] == "RECENT_UNATTESTED"
    assert health["coverage"] == "UNATTESTED"
    assert health["poll_count"] == 2

    # TWSE uses a separate chain in the same bounded archive root.
    twse = capture_poll(tmp_path, fetch_bytes=lambda: b"[]", clock=lambda: BASE)
    assert twse.source == "TWSE_OPENAPI"
    assert AppendOnlyTPEXPollJournal(tmp_path).latest() == second


def test_tpex_failed_fetch_is_auditable_error(tmp_path):
    record = capture_tpex_poll(
        tmp_path, fetch_bytes=lambda: b"{}", clock=lambda: BASE
    )
    assert record.outcome == "ERROR"
    assert record.observation_hash is None
    status = audit_tpex_poll_health(
        tmp_path, as_of=BASE + timedelta(hours=1)
    )
    assert status["status"] == "GAP_OR_FAILURE"
    assert status["coverage"] == "UNATTESTED"


def test_tpex_audit_is_read_only_without_directories(tmp_path):
    root = tmp_path / "missing"
    result = audit_tpex_poll_health(root, as_of=BASE)
    assert result["status"] == "NO_BASELINE"
    assert not root.exists()


def test_scheduled_workflow_captures_and_audits_both_sources():
    root = Path(__file__).resolve().parents[1]
    capture = (root / ".github" / "workflows" / "pit-capture.yml").read_text(
        encoding="utf-8"
    )
    health = (root / ".github" / "workflows" / "pit-health.yml").read_text(
        encoding="utf-8"
    )
    assert "tradingagents_tw.truth.capture_operator" in capture
    assert "tradingagents_tw.truth.tpex_capture_operator" in capture
    assert "steps.twse_poll.outputs.exit_code" in capture
    assert "steps.tpex_poll.outputs.exit_code" in capture
    assert "git add -A -- data/pit" in capture
    assert "tradingagents_tw.truth.capture_operator" in health
    assert "tradingagents_tw.truth.tpex_capture_operator" in health
    assert "contents: write" not in health


@pytest.mark.parametrize("twse_ok,tpex_ok", [
    (True, True), (True, False), (False, True), (False, False),
])
def test_first_dual_source_poll_persists_both_outcomes_without_unrelated_files(
    tmp_path, twse_ok, tpex_ok,
):
    """An independent source failure must not erase either audit receipt.

    Exercise the actual bounded Git staging path used by the scheduled workflow.
    Synthetic responses are only transport fixtures, never PIT coverage proof.
    """
    import subprocess

    archive_root = tmp_path / "data" / "pit"
    twse = capture_poll(
        archive_root,
        fetch_bytes=lambda: b"[]" if twse_ok else b"{}",
        clock=lambda: BASE,
    )
    tpex = capture_tpex_poll(
        archive_root,
        fetch_bytes=lambda: body() if tpex_ok else b"{}",
        clock=lambda: BASE + timedelta(minutes=1),
    )

    assert twse.outcome == ("SUCCESS" if twse_ok else "ERROR")
    assert tpex.outcome == ("SUCCESS" if tpex_ok else "ERROR")
    assert audit_tpex_poll_health(
        archive_root, as_of=BASE + timedelta(hours=1)
    )["status"] == ("RECENT_UNATTESTED" if tpex_ok else "GAP_OR_FAILURE")

    from tradingagents_tw.truth.capture_operator import audit_poll_health
    assert audit_poll_health(
        archive_root, as_of=BASE + timedelta(hours=1)
    )["status"] == ("RECENT_UNATTESTED" if twse_ok else "GAP_OR_FAILURE")

    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github" / "workflows" / "pit-capture.yml"
    ).read_text(encoding="utf-8")
    assert workflow.index("Persist immutable receipts") < workflow.index(
        "Surface failed observations after audit persistence"
    )
    assert "git add -A -- data/pit" in workflow

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "unrelated.txt").write_text("do not stage", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-A", "--", "data/pit"], cwd=tmp_path, check=True
    )
    staged = set(subprocess.check_output(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path, text=True,
    ).splitlines())
    expected = {
        f"data/pit/poll-records/{twse.poll_hash}.json",
        f"data/pit/tpex-poll-records/{tpex.poll_hash}.json",
    }
    if twse_ok:
        expected.add(
            f"data/pit/feed-observations/{twse.observation_hash}.json"
        )
    if tpex_ok:
        expected.add(
            f"data/pit/tpex-feed-observations/{tpex.observation_hash}.json"
        )
    assert staged == expected
