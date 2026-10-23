from __future__ import annotations

from datetime import date, datetime
from typing import Protocol, runtime_checkable

from pydantic import model_validator

from tradingagents_tw.contracts import Evidence, StrictModel


class ProviderMetadata(StrictModel):
    provider_id: str
    source: str
    schema_version: str
    evidence_types: tuple[str, ...]
    source_priority: int

    @model_validator(mode="after")
    def valid_capabilities(self) -> "ProviderMetadata":
        if not self.evidence_types:
            raise ValueError("provider must declare at least one evidence type")
        if len(set(self.evidence_types)) != len(self.evidence_types):
            raise ValueError("provider evidence types must be unique")
        return self


class ProviderRequest(StrictModel):
    symbol: str
    evidence_types: tuple[str, ...]
    start_date: date
    end_date: date
    analysis_cutoff: datetime

    @model_validator(mode="after")
    def valid_request(self) -> "ProviderRequest":
        if not self.evidence_types:
            raise ValueError("request must include at least one evidence type")
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot precede start_date")
        if self.analysis_cutoff.utcoffset() is None:
            raise ValueError("analysis_cutoff must be timezone-aware")
        return self


@runtime_checkable
class ProviderAdapter(Protocol):
    @property
    def metadata(self) -> ProviderMetadata:
        ...

    def fetch(self, request: ProviderRequest) -> tuple[Evidence, ...]:
        """Return Evidence only; Truth owns point-in-time and conflict validation."""
        ...
