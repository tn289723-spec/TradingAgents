from __future__ import annotations

from datetime import datetime, date
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceStatus(str, Enum):
    RAW = "RAW"
    VERIFIED = "VERIFIED"
    CONFLICTED = "CONFLICTED"
    REVOKED = "REVOKED"


class GateStatus(str, Enum):
    PASS = "PASS"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"


class TrendState(str, Enum):
    STRONG_UPTREND = "STRONG_UPTREND"
    UPTREND = "UPTREND"
    PULLBACK_IN_UPTREND = "PULLBACK_IN_UPTREND"
    SIDEWAYS = "SIDEWAYS"
    REVERSAL_WATCH = "REVERSAL_WATCH"
    DISTRIBUTION = "DISTRIBUTION"
    DOWNTREND = "DOWNTREND"
    STRONG_DOWNTREND = "STRONG_DOWNTREND"


class Evidence(StrictModel):
    evidence_id: str
    schema_version: str = "1.0"
    symbol: str | None = None
    evidence_type: str
    source: str
    source_record_id: str | None = None
    event_time: datetime | None = None
    published_at: datetime
    observed_at: datetime
    effective_at: datetime | None = None
    content_hash: str
    revision_id: str
    supersedes_revision_id: str | None = None
    status: EvidenceStatus
    payload: Any

    @model_validator(mode="after")
    def chronology_is_possible(self) -> "Evidence":
        if self.observed_at < self.published_at:
            raise ValueError("observed_at cannot precede published_at")
        if self.effective_at and self.effective_at > self.observed_at:
            raise ValueError("effective_at cannot be after observed_at")
        return self


class EvidenceAssessment(StrictModel):
    coverage: float = Field(ge=0, le=100)
    freshness: Literal["PASS", "WARN", "FAIL"]
    provenance: Literal["PASS", "WARN", "FAIL"]
    critical_missing: tuple[str, ...] = ()
    unresolved_conflicts: tuple[str, ...] = ()
    decision_gate: GateStatus
    gate_reasons: tuple[str, ...] = ()


class TrendAssessment(StrictModel):
    state: TrendState
    candidate_state: TrendState | None = None
    confirmation_progress: float = Field(ge=0, le=1)
    state_since: date
    rule_version: str
    reasons: tuple[str, ...] = ()


class ScoreComponent(StrictModel):
    component: Literal[
        "TREND", "VOLUME_PRICE", "RELATIVE_STRENGTH", "FLOW", "FUNDAMENTAL", "EVENT"
    ]
    raw_value: float
    normalized_value: float = Field(ge=0, le=100)
    weight: float = Field(ge=0, le=1)
    contribution: float
    rule_version: str


class DirectionalScore(StrictModel):
    score: float = Field(ge=0, le=100)
    delta_1d: float | None = None
    slope_5d: float | None = None
    slope_20d: float | None = None
    components: tuple[ScoreComponent, ...]
    scoring_version: str


class ConfidenceBreakdown(StrictModel):
    evidence_confidence: float = Field(ge=0, le=100)
    statistical_confidence: float | None = Field(default=None, ge=0, le=100)
    agent_agreement: float | None = Field(default=None, ge=0, le=100)
    ood_risk: float | None = Field(default=None, ge=0, le=100)
    final_confidence: float = Field(ge=0, le=100)
    limitations: tuple[str, ...] = ()


class TruthSnapshot(StrictModel):
    snapshot_id: str
    symbol: str
    trade_date: date
    analysis_cutoff: datetime
    evidence: tuple[Evidence, ...]
    assessment: EvidenceAssessment
    schema_version: str = "1.0"


class CorporateActionType(str, Enum):
    DIVIDEND = "DIVIDEND"
    STOCK_DIVIDEND = "STOCK_DIVIDEND"
    CAPITAL_REDUCTION = "CAPITAL_REDUCTION"
    SPLIT = "SPLIT"
    REVERSE_SPLIT = "REVERSE_SPLIT"
    RIGHTS_ISSUE = "RIGHTS_ISSUE"
    OTHER = "OTHER"


class CorporateAction(StrictModel):
    action_id: str
    symbol: str
    action_type: CorporateActionType
    event_date: date
    adjustment_factor: float | None = None
    adjustment_method: str
    source: str
    published_at: datetime
    observed_at: datetime

    @model_validator(mode="after")
    def chronology_is_possible(self) -> "CorporateAction":
        if self.observed_at < self.published_at:
            raise ValueError("observed_at cannot precede published_at")
        return self


class PeerMembership(StrictModel):
    symbol: str
    peer_group_id: str
    valid_from: date
    valid_until: date | None = None
    source: str
    confidence: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def valid_window(self) -> "PeerMembership":
        if self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until cannot precede valid_from")
        return self


class DailyReport(StrictModel):
    schema_version: str = "1.0"
    analysis_run_id: str
    snapshot_id: str
    symbol: str
    trade_date: date
    directional_score: DirectionalScore
    trend: TrendAssessment
    confidence: ConfidenceBreakdown
    evidence: EvidenceAssessment
    state_engine_version: str
    config_hash: str
    generated_at: datetime


class StateSnapshot(StrictModel):
    snapshot_id: str
    symbol: str
    trade_date: date
    trend: TrendAssessment
    directional_score: DirectionalScore
    state_engine_version: str
    config_hash: str
