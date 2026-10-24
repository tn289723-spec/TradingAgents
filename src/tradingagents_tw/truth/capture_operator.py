"""Operational prospective TWSE polling with append-only, *unattested* audit receipts.

A scheduled poll proves only that a fetch was attempted. Even successful consecutive
polls do not establish point-in-time completeness or independent coverage attestation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from pydantic import model_validator

from tradingagents_tw.contracts import StrictModel
from tradingagents_tw.truth.feed_capture import (
    AppendOnlyFeedArchive, capture_twse_feed,
)

# Daily 19:17 Asia/Taipei scheduling; >30 hours means a missed/delayed poll.
MAX_POLL_GAP_SECONDS = 30 * 3600
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


class PollRecord(StrictModel):
    version: Literal["pit-poll-v1"] = "pit-poll-v1"
    source: Literal["TWSE_OPENAPI"] = "TWSE_OPENAPI"
    started_at: datetime
    finished_at: datetime
    outcome: Literal["SUCCESS", "ERROR"]
    observation_hash: str | None
    failure_code: Literal["CAPTURE_FAILED"] | None
    previous_poll_hash: str | None
    previous_finished_at: datetime | None
    previous_outcome: Literal["SUCCESS", "ERROR"] | None
    cadence_state: Literal["NO_BASELINE", "OBSERVED", "GAP_OR_FAILURE"]
    poll_hash: str

    @model_validator(mode="after")
    def valid_record(self):
        if (self.started_at.utcoffset() is None
                or self.finished_at.utcoffset() is None
                or self.finished_at < self.started_at):
            raise ValueError("poll clock must be aware and ordered")
        if self.outcome == "SUCCESS":
            if (self.observation_hash is None
                    or not _HEX64.fullmatch(self.observation_hash)
                    or self.failure_code is not None):
                raise ValueError("invalid successful poll receipt")
        elif self.observation_hash is not None or self.failure_code != "CAPTURE_FAILED":
            raise ValueError("invalid failed poll receipt")
        prior_fields = (self.previous_poll_hash, self.previous_finished_at,
                        self.previous_outcome)
        if all(value is None for value in prior_fields):
            expected_cadence = "NO_BASELINE"
        elif all(value is not None for value in prior_fields):
            if not _HEX64.fullmatch(self.previous_poll_hash):
                raise ValueError("invalid previous poll hash")
            if (self.previous_finished_at.utcoffset() is None
                    or self.started_at < self.previous_finished_at):
                raise ValueError("invalid previous poll clock")
            gap = (self.previous_outcome != "SUCCESS"
                   or (self.started_at - self.previous_finished_at).total_seconds()
                   > MAX_POLL_GAP_SECONDS)
            expected_cadence = "GAP_OR_FAILURE" if gap else "OBSERVED"
        else:
            raise ValueError("incomplete previous poll identity")
        if self.cadence_state != expected_cadence:
            raise ValueError("poll cadence mismatch")
        if self.poll_hash != hashlib.sha256(
            _canonical(self.model_dump(mode="json", exclude={"poll_hash"}))
        ).hexdigest():
            raise ValueError("poll digest mismatch")
        return self


class AppendOnlyPollJournal:
    """Single-writer hash-linked journal; not an independently witnessed ledger."""

    def __init__(self, root: str | Path, *, create: bool = True):
        self.objects = Path(root) / "poll-records"
        if create:
            self.objects.mkdir(parents=True, exist_ok=True)

    def read(self, poll_hash: str) -> PollRecord:
        if not _HEX64.fullmatch(poll_hash):
            raise ValueError("invalid poll hash")
        record = PollRecord.model_validate(json.loads(
            (self.objects / (poll_hash + ".json")).read_text(encoding="utf-8")
        ))
        if record.poll_hash != poll_hash:
            raise ValueError("poll identity mismatch")
        return record

    def _verify_success_receipt(self, record: PollRecord) -> None:
        if record.outcome != "SUCCESS":
            return
        observation = AppendOnlyFeedArchive(self.objects.parent, create=False).read(
            record.observation_hash
        )
        if not (record.started_at <= observation.started_at
                <= observation.observed_at <= record.finished_at):
            raise ValueError("poll observation clock mismatch")

    def validated_records(self) -> list[PollRecord]:
        """Verify every stored poll, linked predecessor and referenced raw receipt."""
        records = [self.read(path.stem) for path in self.objects.glob("*.json")]
        for record in records:
            self._verify_success_receipt(record)
        records.sort(key=lambda r: (r.started_at, r.finished_at, r.poll_hash))
        for index, record in enumerate(records):
            prior = records[index - 1] if index else None
            if (record.previous_poll_hash != (prior.poll_hash if prior else None)
                    or record.previous_finished_at != (prior.finished_at if prior else None)
                    or record.previous_outcome != (prior.outcome if prior else None)):
                raise ValueError("poll chain mismatch or missing predecessor")
        return records

    def latest(self) -> PollRecord | None:
        records = self.validated_records()
        return records[-1] if records else None

    def append(self, record: PollRecord) -> str:
        PollRecord.model_validate(record.model_dump(mode="json"))
        self._verify_success_receipt(record)
        prior = self.latest()
        if (record.previous_poll_hash != (prior.poll_hash if prior else None)
                or record.previous_finished_at != (prior.finished_at if prior else None)
                or record.previous_outcome != (prior.outcome if prior else None)):
            raise ValueError("poll append must extend current chain")
        path = self.objects / (record.poll_hash + ".json")
        serialized = _canonical(record.model_dump(mode="json")).decode("utf-8")
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            if self.read(record.poll_hash) != record:
                raise ValueError("immutable poll receipt collision")
        return record.poll_hash


def audit_poll_health(root: str | Path, *, as_of: datetime) -> dict[str, object]:
    """Read-only operational audit, never a PIT publication-coverage attestation.

    Unlike per-poll cadence, this detects a stale *last* observation even when
    GitHub skipped the next scheduled workflow entirely. Historical gaps/errors
    remain visible after subsequent successful polls.
    """
    if as_of.utcoffset() is None:
        raise ValueError("audit clock must be timezone-aware")
    records = AppendOnlyPollJournal(root, create=False).validated_records()
    last = records[-1] if records else None
    if last is not None and as_of < last.finished_at:
        raise ValueError("audit clock precedes latest poll")
    gap_or_failure = any(
        record.outcome != "SUCCESS" or record.cadence_state == "GAP_OR_FAILURE"
        for record in records
    )
    stale = (last is None or
             (as_of - last.finished_at).total_seconds() > MAX_POLL_GAP_SECONDS)
    if last is None:
        status = "NO_BASELINE"
    elif gap_or_failure:
        status = "GAP_OR_FAILURE"
    elif stale:
        status = "STALE"
    else:
        status = "RECENT_UNATTESTED"
    return {
        "status": status,
        "stale": stale,
        "historical_gap_or_failure": gap_or_failure,
        "poll_count": len(records),
        "last_poll_hash": last.poll_hash if last else None,
        "coverage": "UNATTESTED",
    }


def capture_poll(
    root: str | Path, *,
    fetch_bytes: Callable[[], bytes] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> PollRecord:
    """Always journal a fetch failure if local storage and clock remain healthy.

    Failures contain no exception messages, secrets, or fabricated feed observations.
    Missing journal writes are surfaced by the workflow, never reported as success.
    """
    journal = AppendOnlyPollJournal(root)
    prior = journal.latest()
    now = clock or (lambda: datetime.now(timezone.utc))
    started_at = now()
    if (started_at.utcoffset() is None
            or (prior is not None and started_at < prior.finished_at)):
        raise ValueError("invalid poll start clock")
    try:
        observation = capture_twse_feed(
            AppendOnlyFeedArchive(root), fetch_bytes=fetch_bytes, clock=now
        )
        finished_at = now()
        if finished_at.utcoffset() is None or finished_at < observation.observed_at:
            raise ValueError("invalid poll finish clock")
        outcome, observation_hash, failure_code = (
            "SUCCESS", observation.receipt_hash, None
        )
    except Exception:
        finished_at = now()
        outcome, observation_hash, failure_code = (
            "ERROR", None, "CAPTURE_FAILED"
        )
    previous_finished_at = prior.finished_at if prior else None
    previous_outcome = prior.outcome if prior else None
    if prior is None:
        cadence = "NO_BASELINE"
    elif (prior.outcome != "SUCCESS"
          or (started_at - prior.finished_at).total_seconds() > MAX_POLL_GAP_SECONDS):
        cadence = "GAP_OR_FAILURE"
    else:
        cadence = "OBSERVED"
    fields = {
        "version": "pit-poll-v1", "source": "TWSE_OPENAPI",
        "started_at": started_at, "finished_at": finished_at,
        "outcome": outcome, "observation_hash": observation_hash,
        "failure_code": failure_code,
        "previous_poll_hash": prior.poll_hash if prior else None,
        "previous_finished_at": previous_finished_at,
        "previous_outcome": previous_outcome, "cadence_state": cadence,
    }
    payload = PollRecord.model_construct(**fields).model_dump(mode="json")
    record = PollRecord.model_validate({
        **payload, "poll_hash": hashlib.sha256(_canonical(payload)).hexdigest()
    })
    journal.append(record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Append-only TWSE prospective poll (not PIT coverage proof)"
    )
    parser.add_argument("--archive-root", required=True, type=Path)
    parser.add_argument("--audit-only", action="store_true",
                        help="Read-only freshness/chain audit; never PIT coverage proof")
    args = parser.parse_args()
    if args.audit_only:
        result = audit_poll_health(args.archive_root, as_of=datetime.now(timezone.utc))
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "RECENT_UNATTESTED" else 2
    record = capture_poll(args.archive_root)
    print(json.dumps({
        "poll_hash": record.poll_hash, "outcome": record.outcome,
        "cadence_state": record.cadence_state, "coverage": "UNATTESTED",
    }, sort_keys=True))
    return 0 if record.outcome == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
