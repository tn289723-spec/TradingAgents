"""Immutable prospective capture of the official TPEx ex-right/ex-dividend feed.

A successful observation is an exact raw HTTP receipt only. It never implies
historical completeness, no-action coverage, or independent attestation.
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
from tradingagents_tw.truth.feed_capture import MAX_RESPONSE_BYTES


TPEX_EXRIGHT_PREPOST_URL = (
    "https://www.tpex.org.tw/openapi/v1/tpex_exright_prepost"
)
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_REQUIRED_IDENTITY = (
    "ExRrightsExDividendDate",
    "SecuritiesCompanyCode",
    "CompanyName",
    "ExRrightsExDividend",
)
_REQUIRED_TERMS = (
    "StockDividendRatio",
    "SubscriptionRatioToNewSharesIssued",
    "SubscriptionPricePerShare",
    "CashDividend",
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _parse_event_date(raw: str) -> date:
    if re.fullmatch(r"(?:[0-9]{7}|[0-9]{8})", raw) is None:
        raise ValueError("official TPEx feed row has invalid event date")
    try:
        if len(raw) == 7:
            return date(int(raw[:3]) + 1911, int(raw[3:5]), int(raw[5:7]))
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    except ValueError as exc:
        raise ValueError("official TPEx feed row has invalid event date") from exc


def _check_body(body: bytes) -> None:
    if not body or len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("invalid or oversized official TPEx feed body")
    try:
        rows = json.loads(body.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("official TPEx feed is not valid UTF-8 JSON") from exc
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("official TPEx feed must be a JSON array of objects")

    # Empty [] is a valid observed response but remains UNATTESTED.
    # Non-empty rows must match the official preview schema enough that an
    # upstream error envelope cannot become a SUCCESS receipt.
    for row in rows:
        for field in _REQUIRED_IDENTITY:
            value = row.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"official TPEx feed row missing valid {field}")
        _parse_event_date(row["ExRrightsExDividendDate"].strip())
        for field in _REQUIRED_TERMS:
            if field not in row or not isinstance(row[field], str):
                raise ValueError(f"official TPEx feed row missing valid {field}")


class TPEXFeedObservation(StrictModel):
    version: Literal["pit-tpex-feed-observation-v1"] = "pit-tpex-feed-observation-v1"
    source: Literal["TPEX_OPENAPI"] = "TPEX_OPENAPI"
    endpoint: Literal[TPEX_EXRIGHT_PREPOST_URL] = TPEX_EXRIGHT_PREPOST_URL
    started_at: datetime
    observed_at: datetime
    response_b64: str
    body_sha256: str
    receipt_hash: str

    @model_validator(mode="after")
    def valid_observation(self):
        if (
            self.started_at.utcoffset() is None
            or self.observed_at.utcoffset() is None
            or self.observed_at < self.started_at
        ):
            raise ValueError("TPEx feed observation clock must be aware and ordered")
        try:
            body = base64.b64decode(self.response_b64, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("invalid TPEx feed body encoding") from exc
        _check_body(body)
        if self.body_sha256 != hashlib.sha256(body).hexdigest():
            raise ValueError("TPEx feed body digest mismatch")
        expected = hashlib.sha256(
            _canonical(self.model_dump(mode="json", exclude={"receipt_hash"}))
        ).hexdigest()
        if self.receipt_hash != expected:
            raise ValueError("TPEx feed receipt digest mismatch")
        return self

    def raw_bytes(self) -> bytes:
        TPEXFeedObservation.model_validate(self.model_dump(mode="json"))
        return base64.b64decode(self.response_b64, validate=True)


class AppendOnlyTPEXFeedArchive:
    """Exclusive-create TPEx receipts; no inferred coverage continuity."""

    def __init__(self, root: str | Path, *, create: bool = True):
        self.objects = Path(root) / "tpex-feed-observations"
        if create:
            self.objects.mkdir(parents=True, exist_ok=True)

    def append(self, observation: TPEXFeedObservation) -> str:
        TPEXFeedObservation.model_validate(observation.model_dump(mode="json"))
        path = self.objects / (observation.receipt_hash + ".json")
        serialized = _canonical(observation.model_dump(mode="json")).decode("utf-8")
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            if self.read(observation.receipt_hash) != observation:
                raise ValueError("immutable TPEx feed observation collision")
        return observation.receipt_hash

    def read(self, receipt_hash: str) -> TPEXFeedObservation:
        if not _HEX64.fullmatch(receipt_hash):
            raise ValueError("invalid TPEx feed receipt hash")
        record = TPEXFeedObservation.model_validate(json.loads(
            (self.objects / (receipt_hash + ".json")).read_text(encoding="utf-8")
        ))
        if record.receipt_hash != receipt_hash:
            raise ValueError("TPEx feed receipt identity mismatch")
        return record


def _fetch_official_bytes() -> bytes:
    request = Request(
        TPEX_EXRIGHT_PREPOST_URL,
        headers={"User-Agent": "TradingAgents-TW/0.1 PIT prospective capture"},
    )
    with urlopen(request, timeout=10) as response:
        return response.read(MAX_RESPONSE_BYTES + 1)


def capture_tpex_feed(
    archive: AppendOnlyTPEXFeedArchive,
    *,
    fetch_bytes: Callable[[], bytes] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> TPEXFeedObservation:
    now = clock or (lambda: datetime.now(timezone.utc))
    started_at = now()
    body = (fetch_bytes or _fetch_official_bytes)()
    observed_at = now()
    if not isinstance(body, bytes):
        raise ValueError("official TPEx feed fetcher must return bytes")
    _check_body(body)
    fields = {
        "version": "pit-tpex-feed-observation-v1",
        "source": "TPEX_OPENAPI",
        "endpoint": TPEX_EXRIGHT_PREPOST_URL,
        "started_at": started_at,
        "observed_at": observed_at,
        "response_b64": base64.b64encode(body).decode("ascii"),
        "body_sha256": hashlib.sha256(body).hexdigest(),
    }
    normalized = TPEXFeedObservation.model_construct(**fields).model_dump(mode="json")
    observation = TPEXFeedObservation.model_validate({
        **fields,
        "receipt_hash": hashlib.sha256(_canonical(normalized)).hexdigest(),
    })
    archive.append(observation)
    return observation


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture TPEx rolling ex-right/ex-dividend feed (unattested)"
    )
    parser.add_argument("--archive-root", required=True, type=Path)
    args = parser.parse_args()
    record = capture_tpex_feed(AppendOnlyTPEXFeedArchive(args.archive_root))
    print(json.dumps({
        "receipt_hash": record.receipt_hash,
        "observed_at": record.observed_at.isoformat(),
        "coverage": "UNATTESTED",
    }, sort_keys=True))


if __name__ == "__main__":
    main()
