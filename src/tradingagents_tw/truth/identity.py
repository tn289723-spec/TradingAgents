from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any, Mapping

from tradingagents_tw.contracts import Evidence, EvidenceAssessment


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("identity input must be canonical JSON data") from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def derive_config_hash(config: Mapping[str, Any]) -> str:
    """Hash the deterministic Truth configuration, not runtime process state."""
    return _sha256(dict(config))


def canonical_evidence(evidence: tuple[Evidence, ...]) -> tuple[Evidence, ...]:
    return tuple(
        sorted(
            evidence,
            key=lambda item: (
                item.evidence_type,
                item.source,
                item.evidence_id,
                item.revision_id,
                item.content_hash,
            ),
        )
    )


def derive_truth_content_hash(
    *,
    symbol: str,
    trade_date: date,
    analysis_cutoff: datetime,
    evidence: tuple[Evidence, ...],
    assessment: EvidenceAssessment,
    config_hash: str,
    schema_version: str = "1.0",
) -> str:
    ordered = canonical_evidence(evidence)
    payload = {
        "schema_version": schema_version,
        "symbol": symbol,
        "trade_date": trade_date.isoformat(),
        "analysis_cutoff": analysis_cutoff.isoformat(),
        "evidence": [item.model_dump(mode="json") for item in ordered],
        "assessment": assessment.model_dump(mode="json"),
        "config_hash": config_hash,
    }
    return _sha256(payload)
