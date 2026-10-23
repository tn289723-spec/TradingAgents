from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Mapping

from tradingagents_tw.contracts import Evidence, EvidenceAssessment


def _normalize(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("identity datetime must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "model_dump"):
        return _normalize(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def canonical_identity_json(value: Any) -> str:
    try:
        return json.dumps(
            _normalize(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("identity input must be canonical JSON data") from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_identity_json(value).encode("utf-8")).hexdigest()


def derive_config_hash(config: Mapping[str, Any]) -> str:
    """Hash deterministic Truth configuration with timezone-normalized values."""
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
        "trade_date": trade_date,
        "analysis_cutoff": analysis_cutoff,
        "evidence": ordered,
        "assessment": assessment,
        "config_hash": config_hash,
    }
    return _sha256(payload)
