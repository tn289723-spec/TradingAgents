"""Synthetic operator audit tests: cadence never implies complete PIT coverage."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from tradingagents_tw.truth.capture_operator import (
    AppendOnlyPollJournal, capture_poll,
)

BASE = datetime(2026, 10, 24, 0, tzinfo=timezone.utc)


def ticks(*values):
    iterator = iter(values)
    return lambda: next(iterator)


def success(root, start):
    return capture_poll(root, fetch_bytes=lambda: b"[]",
                        clock=ticks(start, start + timedelta(seconds=1),
                                    start + timedelta(seconds=2),
                                    start + timedelta(seconds=3)))


def test_successive_daily_polls_are_only_observations(tmp_path):
    first = success(tmp_path, BASE)
    second = success(tmp_path, BASE + timedelta(hours=24))
    assert first.outcome == second.outcome == "SUCCESS"
    assert first.cadence_state == "NO_BASELINE"
    assert second.cadence_state == "OBSERVED"
    assert second.previous_poll_hash == first.poll_hash
    assert AppendOnlyPollJournal(tmp_path).latest() == second
    assert "coverage" not in second.model_fields
    assert "attestation" not in second.model_fields


def test_failed_fetch_and_missed_poll_remain_visible(tmp_path):
    first = success(tmp_path, BASE)

    def broken():
        raise ConnectionError("do not persist this secret-bearing error")

    start = BASE + timedelta(hours=32)
    failure = capture_poll(tmp_path, fetch_bytes=broken,
                           clock=ticks(start, start + timedelta(seconds=1),
                                       start + timedelta(seconds=2)))
    assert failure.outcome == "ERROR"
    assert failure.failure_code == "CAPTURE_FAILED"
    assert failure.observation_hash is None
    assert failure.cadence_state == "GAP_OR_FAILURE"
    assert "secret-bearing" not in json.dumps(failure.model_dump(mode="json"))
    third = success(tmp_path, BASE + timedelta(hours=48))
    assert third.cadence_state == "GAP_OR_FAILURE"
    assert third.previous_poll_hash == failure.poll_hash
    assert AppendOnlyPollJournal(tmp_path).latest() == third
    assert first.poll_hash != third.poll_hash


def test_invalid_feed_is_error_not_empty_success(tmp_path):
    start = BASE
    record = capture_poll(tmp_path, fetch_bytes=lambda: b"{}",
                          clock=ticks(start, start + timedelta(seconds=1),
                                      start + timedelta(seconds=2),
                                      start + timedelta(seconds=3)))
    assert record.outcome == "ERROR"
    assert record.observation_hash is None


def test_journal_rejects_tamper_missing_middle_and_forged_cadence(tmp_path):
    first = success(tmp_path, BASE)
    second = success(tmp_path, BASE + timedelta(hours=24))
    journal = AppendOnlyPollJournal(tmp_path)
    path = journal.objects / (first.poll_hash + ".json")
    original = path.read_text(encoding="utf-8")
    tampered = json.loads(original)
    tampered["cadence_state"] = "OBSERVED"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError):
        journal.latest()
    path.write_text(original, encoding="utf-8")
    path.unlink()
    with pytest.raises(ValueError, match="chain mismatch"):
        journal.latest()
    assert second.previous_poll_hash == first.poll_hash


def test_out_of_order_clock_does_not_append(tmp_path):
    success(tmp_path, BASE)
    with pytest.raises(ValueError, match="clock"):
        capture_poll(tmp_path, fetch_bytes=lambda: b"[]",
                     clock=ticks(BASE - timedelta(seconds=1)))
    assert len(list(AppendOnlyPollJournal(tmp_path).objects.glob("*.json"))) == 1


def test_append_requires_current_predecessor(tmp_path):
    first = success(tmp_path, BASE)
    second = success(tmp_path, BASE + timedelta(hours=24))
    with pytest.raises(ValueError, match="extend current chain"):
        AppendOnlyPollJournal(tmp_path).append(first)
    assert second == AppendOnlyPollJournal(tmp_path).latest()
