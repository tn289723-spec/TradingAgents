"""Prospective point-in-time corporate-action capture and coverage verification.

This is a fail-closed evidence boundary, NOT an exchange historical archive.
A COMPLETE claim is unusable without an independent trusted attestation callback.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Callable, Literal
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator
from tradingagents_tw.contracts import StrictModel


def _digest(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> bool:
    return value.utcoffset() is not None


class CapturedAction(StrictModel):
    version: Literal["pit-action-capture-v1"] = "pit-action-capture-v1"
    market: Literal["TWSE", "TPEX"]
    symbol: str = Field(min_length=1)
    source: Literal["TWSE_OPENAPI", "TPEX_OPENAPI", "TWSE_ARCHIVE", "TPEX_ARCHIVE"]
    event_key: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    supersedes_revision_id: str | None = None
    published_at: datetime
    observed_at: datetime
    raw_payload: dict[str, Any]
    raw_sha256: str
    record_hash: str

    @model_validator(mode="after")
    def validate_capture(self):
        if self.source.split("_", 1)[0] != self.market:
            raise ValueError("capture board/source mismatch")
        if not _aware(self.published_at) or not _aware(self.observed_at):
            raise ValueError("capture timestamps must be timezone-aware")
        if self.published_at > self.observed_at:
            raise ValueError("publication cannot follow observation")
        if self.supersedes_revision_id == self.revision_id:
            raise ValueError("self-superseding revision")
        if self.raw_sha256 != _digest(self.raw_payload):
            raise ValueError("captured raw payload hash mismatch")
        if self.record_hash != _digest(self.model_dump(mode="json", exclude={"record_hash"})):
            raise ValueError("captured record hash mismatch")
        return self


def capture_action(*, market: str, symbol: str, source: str, event_key: str,
                   revision_id: str, raw_payload: dict[str, Any],
                   published_at: datetime | None = None, supersedes_revision_id: str | None = None,
                   clock: Callable[[], datetime] | None = None) -> CapturedAction:
    """Stamp acquisition at capture time; never infer observation from event date."""
    observed = (clock or (lambda: datetime.now(timezone.utc)))()
    if not _aware(observed):
        raise ValueError("capture clock must be timezone-aware")
    payload = {
        "version": "pit-action-capture-v1", "market": market, "symbol": symbol,
        "source": source, "event_key": event_key, "revision_id": revision_id,
        "supersedes_revision_id": supersedes_revision_id,
        "published_at": published_at or observed, "observed_at": observed,
        "raw_payload": raw_payload, "raw_sha256": _digest(raw_payload),
    }
    normalized = CapturedAction.model_construct(**payload).model_dump(mode="json")
    return CapturedAction.model_validate({**payload, "record_hash": _digest(normalized)})


class AppendOnlyActionArchive:
    """Content-addressed, exclusive-create capture; no mutation or timestamp rewrite."""

    def __init__(self, root: str | Path):
        self.objects = Path(root) / "action-objects"
        self.objects.mkdir(parents=True, exist_ok=True)

    def append(self, record: CapturedAction) -> str:
        CapturedAction.model_validate(record.model_dump(mode="json"))
        path = self.objects / (record.record_hash + ".json")
        payload = json.dumps(record.model_dump(mode="json"), ensure_ascii=False,
                             sort_keys=True, separators=(",", ":"), allow_nan=False)
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            if self.read(record.record_hash) != record:
                raise ValueError("immutable capture collision")
        return record.record_hash

    def read(self, record_hash: str) -> CapturedAction:
        if len(record_hash) != 64 or any(c not in "0123456789abcdef" for c in record_hash):
            raise ValueError("invalid capture hash")
        record = CapturedAction.model_validate(
            json.loads((self.objects / (record_hash + ".json")).read_text(encoding="utf-8"))
        )
        if record.record_hash != record_hash:
            raise ValueError("capture object identity mismatch")
        return record


class CoverageAttestation(StrictModel):
    version: Literal["pit-action-coverage-v1"] = "pit-action-coverage-v1"
    market: Literal["TWSE", "TPEX"]
    symbol: str = Field(min_length=1)
    start_date: date
    end_date: date
    analysis_cutoff: datetime
    capture_started_at: datetime
    capture_ended_at: datetime
    observed_at: datetime
    coverage: Literal["COMPLETE", "PARTIAL", "UNKNOWN"]
    record_hashes: tuple[str, ...]
    attestation_id: str = Field(min_length=1)
    attestation_hash: str

    @model_validator(mode="after")
    def valid_manifest(self):
        if self.start_date > self.end_date:
            raise ValueError("invalid coverage window")
        if not all(_aware(t) for t in (self.analysis_cutoff, self.capture_started_at,
                                      self.capture_ended_at, self.observed_at)):
            raise ValueError("coverage timestamps must be timezone-aware")
        if self.capture_started_at > self.capture_ended_at or self.capture_ended_at > self.observed_at:
            raise ValueError("invalid capture chronology")
        if tuple(sorted(set(self.record_hashes))) != self.record_hashes:
            raise ValueError("record hashes must be unique and sorted")
        if self.attestation_hash != _digest(self.model_dump(mode="json", exclude={"attestation_hash"})):
            raise ValueError("coverage attestation hash mismatch")
        return self


def build_attestation(**fields: Any) -> CoverageAttestation:
    values = {"version": "pit-action-coverage-v1", **fields}
    normalized = CoverageAttestation.model_construct(**values).model_dump(
        mode="json", exclude={"attestation_hash"}
    )
    return CoverageAttestation.model_validate({**values, "attestation_hash": _digest(normalized)})


def verify_archive_coverage(
    manifest: CoverageAttestation, records: tuple[CapturedAction, ...], *,
    market: str, symbol: str, start: date, end: date, cutoff: datetime,
    trusted_attestation: Callable[[CoverageAttestation], bool] | None = None,
) -> tuple[CapturedAction, ...]:
    """Return effective revisions only if independent coverage proof is trusted.

    Without an externally verified attestor, even an empty COMPLETE manifest BLOCKS.
    An empty latest-only feed is never evidence of no corporate actions.
    """
    if not _aware(cutoff) or manifest.market != market or manifest.symbol != symbol:
        raise ValueError("coverage board/symbol/cutoff mismatch")
    if (manifest.start_date != start or manifest.end_date != end
            or manifest.analysis_cutoff != cutoff or manifest.observed_at > cutoff):
        raise ValueError("coverage time window mismatch or late attestation")
    if manifest.coverage != "COMPLETE":
        raise ValueError("incomplete corporate-action archive coverage")
    window_start = datetime.combine(start, time.min, tzinfo=ZoneInfo("Asia/Taipei"))
    if manifest.capture_started_at > window_start or manifest.capture_ended_at < cutoff:
        raise ValueError("continuous capture window is not demonstrated")
    if trusted_attestation is None or trusted_attestation(manifest) is not True:
        raise ValueError("unverified archive coverage attestation")
    if tuple(sorted(r.record_hash for r in records)) != manifest.record_hashes:
        raise ValueError("captured records do not match attestation")
    grouped: dict[str, list[CapturedAction]] = defaultdict(list)
    for record in records:
        CapturedAction.model_validate(record.model_dump(mode="json"))
        if (record.market != market or record.symbol != symbol
                or record.observed_at > cutoff or record.published_at > cutoff):
            raise ValueError("cross-board, cross-symbol or late action evidence")
        event_date = date.fromisoformat(str(record.raw_payload["event_date"]))
        if not start < event_date <= end:
            raise ValueError("action event outside attested window")
        grouped[record.event_key].append(record)
    active: list[CapturedAction] = []
    for key in sorted(grouped):
        chain = sorted(grouped[key], key=lambda r: (r.observed_at, r.revision_id))
        if len({r.revision_id for r in chain}) != len(chain):
            raise ValueError("conflicting duplicate revision")
        if len({(r.source, r.raw_payload["event_date"]) for r in chain}) != 1:
            raise ValueError("ambiguous action identity or event date")
        if chain[0].supersedes_revision_id is not None:
            raise ValueError("missing initial revision")
        for old, new in zip(chain, chain[1:]):
            if (new.supersedes_revision_id != old.revision_id
                    or new.observed_at <= old.observed_at
                    or new.published_at < old.published_at):
                raise ValueError("forked, out-of-order or missing revision")
        active.append(chain[-1])
    return tuple(active)
