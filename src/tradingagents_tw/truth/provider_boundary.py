from __future__ import annotations

from tradingagents_tw.contracts import Evidence, EvidenceStatus
from tradingagents_tw.providers import ProviderMetadata, ProviderRequest
from .point_in_time import LookaheadViolation, assert_point_in_time


class ProviderBoundaryViolation(ValueError):
    pass


def validate_provider_output(
    *,
    metadata: ProviderMetadata,
    request: ProviderRequest,
    evidence: tuple[Evidence, ...],
) -> tuple[Evidence, ...]:
    unsupported = sorted(set(request.evidence_types) - set(metadata.evidence_types))
    if unsupported:
        raise ProviderBoundaryViolation(
            f"provider does not support requested evidence types: {unsupported}"
        )

    seen_ids: set[str] = set()
    for item in evidence:
        if item.evidence_id in seen_ids:
            raise ProviderBoundaryViolation(f"duplicate evidence_id: {item.evidence_id}")
        seen_ids.add(item.evidence_id)

        if item.status is not EvidenceStatus.RAW:
            raise ProviderBoundaryViolation("provider output must enter Truth as RAW evidence")
        if item.source != metadata.source:
            raise ProviderBoundaryViolation(
                f"source mismatch: expected {metadata.source}, got {item.source}"
            )
        if item.symbol != request.symbol:
            raise ProviderBoundaryViolation(
                f"symbol mismatch: expected {request.symbol}, got {item.symbol}"
            )
        if item.evidence_type not in request.evidence_types:
            raise ProviderBoundaryViolation(
                f"unexpected evidence type: {item.evidence_type}"
            )
        if item.evidence_type not in metadata.evidence_types:
            raise ProviderBoundaryViolation(
                f"provider emitted undeclared evidence type: {item.evidence_type}"
            )
        try:
            assert_point_in_time(item, request.analysis_cutoff)
        except LookaheadViolation as exc:
            raise ProviderBoundaryViolation(str(exc)) from exc

    return evidence
