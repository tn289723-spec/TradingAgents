"""Signed PIT action archive boundary for historical ingestion and offline replay.

The legacy action coverage contract is synthetic-only. Production replay requires
a signed, independently pinned COMPLETE capture manifest, with every effective
announcement bound to the immutable captured record that the signer attested.
The signature proves attestor identity, not actual completeness of observation.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Mapping

from tradingagents_tw.contracts import Evidence, StrictModel
from tradingagents_tw.providers.registry import Market
from .archive import CapturedAction, CoverageAttestation
from .attestation import SignedCoverageProof, verify_signed_archive
from .factors import ActionCoverage, validate_action_coverage


class SignedHistoricalCoverage(StrictModel):
    version: Literal["historical-action-coverage-signed-v1"] = "historical-action-coverage-signed-v1"
    legacy_coverage: ActionCoverage
    manifest: CoverageAttestation
    records: tuple[CapturedAction, ...]
    proof: SignedCoverageProof


def verify_signed_historical_coverage(
    coverage: Evidence, announcements: tuple[Evidence, ...], *,
    market: Market, symbol: str, start: date, end: date, cutoff: datetime,
    trusted_public_keys: Mapping[str, str],
) -> None:
    """Fail closed before fetch and again on replay with out-of-band trust roots."""
    bundle = SignedHistoricalCoverage.model_validate(coverage.payload)
    if (bundle.legacy_coverage.market is not market
            or bundle.legacy_coverage.start_date != start
            or bundle.legacy_coverage.end_date != end):
        raise ValueError("signed and legacy coverage windows disagree")
    if (coverage.observed_at < bundle.manifest.observed_at
            or coverage.published_at < bundle.manifest.observed_at):
        raise ValueError("signed proof evidence predates attestation observation")
    # Preserve all legacy factor/announcement invariants, but never treat that
    # self-declared legacy manifest as independent proof of historical coverage.
    validate_action_coverage(
        coverage.model_copy(update={"payload": bundle.legacy_coverage.model_dump(mode="json")}),
        announcements, market=market, symbol=symbol, start=start, end=end, cutoff=cutoff,
    )
    active = verify_signed_archive(
        bundle.manifest, bundle.records, bundle.proof,
        trusted_public_keys=trusted_public_keys, market=market.value, symbol=symbol,
        start=start, end=end, cutoff=cutoff,
    )
    if len(active) != len(announcements):
        raise ValueError("signed archive active records do not match historical announcements")
    by_hash = {record.record_hash: record for record in active}
    if len(by_hash) != len(active):
        raise ValueError("duplicate active signed archive record")
    if {item.source_record_id for item in announcements} != set(by_hash):
        raise ValueError("historical announcement lacks captured signed record identity")
    for item in announcements:
        record = by_hash[item.source_record_id]
        if (item.evidence_id != record.event_key
                or item.source != record.source
                or item.revision_id != record.revision_id
                or item.supersedes_revision_id != record.supersedes_revision_id
                or item.published_at != record.published_at
                or item.observed_at != record.observed_at
                or item.payload != record.raw_payload):
            raise ValueError("historical announcement differs from effective signed capture")
