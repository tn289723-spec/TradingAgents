"""Immutable prospective capture of the official TWSE rolling action feed.

A successful HTTP observation is NOT a COMPLETE PIT coverage attestation.
No publication time is inferred from the event date or current HTTP response.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Literal
from urllib.request import Request, urlopen

from pydantic import model_validator

from tradingagents_tw.contracts import StrictModel
from tradingagents_tw.providers.corporate_actions import TWSE_EXRIGHT_PREVIEW_URL

MAX_RESPONSE_BYTES = 2_000_000
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _check_body(body: bytes) -> None:
    if not body or len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("invalid or oversized official feed body")
    try:
        rows = json.loads(body.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("official feed is not valid UTF-8 JSON") from exc
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("official feed must be a JSON array of objects")
    # An upstream JSON error envelope must not become a SUCCESS receipt.
    # Empty [] remains an unattested observation, not no-action proof.
    for row in rows:
        # The official preview includes an identity, event date, name and action
        # type. A partial/error-shaped array must not become a SUCCESS receipt.
        for field in ("Code", "Date", "Name", "Exdividend"):
            value = row.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"official feed row missing valid {field}")
        raw_date = row["Date"].strip()
        if re.fullmatch(r"(?:[0-9]{7}|[0-9]{8})", raw_date) is None:
            raise ValueError("official feed row has invalid Date")
        try:
            if len(raw_date) == 7:
                date(int(raw_date[:3]) + 1911, int(raw_date[3:5]), int(raw_date[5:7]))
            else:
                date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8]))
        except ValueError as exc:
            raise ValueError("official feed row has invalid Date") from exc


class FeedObservation(StrictModel):
    version: Literal["pit-feed-observation-v1"] = "pit-feed-observation-v1"
    source: Literal["TWSE_OPENAPI"] = "TWSE_OPENAPI"
    endpoint: Literal[TWSE_EXRIGHT_PREVIEW_URL] = TWSE_EXRIGHT_PREVIEW_URL
    started_at: datetime
    observed_at: datetime
    response_b64: str
    body_sha256: str
    receipt_hash: str

    @model_validator(mode="after")
    def valid_observation(self):
        if (self.started_at.utcoffset() is None or self.observed_at.utcoffset() is None
                or self.observed_at < self.started_at):
            raise ValueError("feed observation clock must be aware and ordered")
        try:
            body = base64.b64decode(self.response_b64, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("invalid feed body encoding") from exc
        _check_body(body)
        if self.body_sha256 != hashlib.sha256(body).hexdigest():
            raise ValueError("feed body digest mismatch")
        if self.receipt_hash != hashlib.sha256(
            _canonical(self.model_dump(mode="json", exclude={"receipt_hash"}))
        ).hexdigest():
            raise ValueError("feed receipt digest mismatch")
        return self

    def raw_bytes(self) -> bytes:
        FeedObservation.model_validate(self.model_dump(mode="json"))
        return base64.b64decode(self.response_b64, validate=True)


class AppendOnlyFeedArchive:
    """Exclusive-create receipts. No overwrites, no implied coverage continuity."""

    def __init__(self, root: str | Path, *, create: bool = True):
        self.objects = Path(root) / "feed-observations"
        if create:
            self.objects.mkdir(parents=True, exist_ok=True)

    def append(self, observation: FeedObservation) -> str:
        FeedObservation.model_validate(observation.model_dump(mode="json"))
        path = self.objects / (observation.receipt_hash + ".json")
        serialized = _canonical(observation.model_dump(mode="json")).decode("utf-8")
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            if self.read(observation.receipt_hash) != observation:
                raise ValueError("immutable feed observation collision")
        return observation.receipt_hash

    def read(self, receipt_hash: str) -> FeedObservation:
        if not _HEX64.fullmatch(receipt_hash):
            raise ValueError("invalid feed receipt hash")
        record = FeedObservation.model_validate(json.loads(
            (self.objects / (receipt_hash + ".json")).read_text(encoding="utf-8")
        ))
        if record.receipt_hash != receipt_hash:
            raise ValueError("feed receipt identity mismatch")
        return record


def _fetch_official_bytes() -> bytes:
    request = Request(TWSE_EXRIGHT_PREVIEW_URL,
                      headers={"User-Agent": "TradingAgents-TW/0.1 PIT prospective capture"})
    with urlopen(request, timeout=10) as response:
        return response.read(MAX_RESPONSE_BYTES + 1)


def capture_twse_feed(
    archive: AppendOnlyFeedArchive, *,
    fetch_bytes: Callable[[], bytes] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FeedObservation:
    """Capture exact HTTP body; observation timestamp is taken AFTER retrieval.

    A valid empty response is only an empty observed feed, never no-action proof.
    Failures leave no success receipt. Callers must monitor capture gaps separately.
    """
    now = clock or (lambda: datetime.now(timezone.utc))
    started_at = now()
    body = (fetch_bytes or _fetch_official_bytes)()
    observed_at = now()
    if not isinstance(body, bytes):
        raise ValueError("official feed fetcher must return bytes")
    _check_body(body)
    fields = {
        "version": "pit-feed-observation-v1", "source": "TWSE_OPENAPI",
        "endpoint": TWSE_EXRIGHT_PREVIEW_URL, "started_at": started_at,
        "observed_at": observed_at, "response_b64": base64.b64encode(body).decode("ascii"),
        "body_sha256": hashlib.sha256(body).hexdigest(),
    }
    normalized = FeedObservation.model_construct(**fields).model_dump(mode="json")
    observation = FeedObservation.model_validate({
        **fields, "receipt_hash": hashlib.sha256(_canonical(normalized)).hexdigest()
    })
    archive.append(observation)
    return observation


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture TWSE rolling action feed (unattested)")
    parser.add_argument("--archive-root", required=True, type=Path)
    args = parser.parse_args()
    record = capture_twse_feed(AppendOnlyFeedArchive(args.archive_root))
    print(json.dumps({"receipt_hash": record.receipt_hash,
                      "observed_at": record.observed_at.isoformat(),
                      "coverage": "UNATTESTED"}, sort_keys=True))


if __name__ == "__main__":
    main()
