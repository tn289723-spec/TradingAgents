"""Synthetic prospective feed tests; do not assert real PIT coverage."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from tradingagents_tw.truth.feed_capture import (
    AppendOnlyFeedArchive, MAX_RESPONSE_BYTES, capture_twse_feed,
)

START = datetime(2026, 10, 24, 1, tzinfo=timezone.utc)
END = START + timedelta(seconds=2)


def clock_sequence(*values):
    iterator = iter(values)
    return lambda: next(iterator)


def test_exact_raw_bytes_and_immutable_receipt(tmp_path):
    archive = AppendOnlyFeedArchive(tmp_path)
    raw = b'[ { "Code": "2330", "Date": "1151024" } ]'
    receipt = capture_twse_feed(
        archive, fetch_bytes=lambda: raw, clock=clock_sequence(START, END))
    assert receipt.started_at == START
    assert receipt.observed_at == END
    assert receipt.raw_bytes() == raw
    assert archive.read(receipt.receipt_hash) == receipt
    assert archive.append(receipt) == receipt.receipt_hash
    path = archive.objects / (receipt.receipt_hash + ".json")
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["body_sha256"] = "0" * 64
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        archive.read(receipt.receipt_hash)
    with pytest.raises(ValueError, match="digest mismatch"):
        archive.append(receipt)


def test_empty_feed_is_unattested_observation(tmp_path):
    receipt = capture_twse_feed(
        AppendOnlyFeedArchive(tmp_path), fetch_bytes=lambda: b"[]",
        clock=clock_sequence(START, END))
    assert receipt.raw_bytes() == b"[]"
    assert not hasattr(receipt, "coverage")
    assert not hasattr(receipt, "published_at")


@pytest.mark.parametrize("body", [
    b"", b"not-json", b"{}", b"[1]", b"\xff", b"x" * (MAX_RESPONSE_BYTES + 1),
])
def test_invalid_feed_does_not_write_receipt(tmp_path, body):
    archive = AppendOnlyFeedArchive(tmp_path)
    with pytest.raises(ValueError):
        capture_twse_feed(archive, fetch_bytes=lambda: body,
                          clock=clock_sequence(START, END))
    assert list(archive.objects.iterdir()) == []


def test_clock_and_fetch_failure_do_not_claim_success(tmp_path):
    archive = AppendOnlyFeedArchive(tmp_path)
    with pytest.raises(ValueError, match="clock"):
        capture_twse_feed(archive, fetch_bytes=lambda: b"[]",
                          clock=clock_sequence(END, START))
    with pytest.raises(ValueError, match="clock"):
        capture_twse_feed(archive, fetch_bytes=lambda: b"[]",
                          clock=clock_sequence(START.replace(tzinfo=None), END))
    def broken_fetch():
        raise ConnectionError("offline")
    with pytest.raises(ConnectionError):
        capture_twse_feed(archive, fetch_bytes=broken_fetch,
                          clock=clock_sequence(START, END))
    assert list(archive.objects.iterdir()) == []


def test_read_rejects_untrusted_filename(tmp_path):
    archive = AppendOnlyFeedArchive(tmp_path)
    with pytest.raises(ValueError, match="invalid"):
        archive.read("../outside")
