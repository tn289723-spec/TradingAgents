from __future__ import annotations

from tradingagents_tw.contracts import EvidenceAssessment, GateStatus


def assess_evidence(
    *,
    coverage: float,
    freshness: str,
    provenance: str,
    critical_missing: tuple[str, ...] = (),
    unresolved_conflicts: tuple[str, ...] = (),
) -> EvidenceAssessment:
    reasons: list[str] = []

    if provenance == "FAIL":
        reasons.append("PROVENANCE_FAIL")
        gate = GateStatus.BLOCKED
    elif unresolved_conflicts:
        reasons.append("UNRESOLVED_CRITICAL_CONFLICT")
        gate = GateStatus.BLOCKED
    elif critical_missing:
        reasons.append("CRITICAL_MISSING")
        gate = GateStatus.DEGRADED
    elif freshness == "FAIL":
        reasons.append("STALE_CRITICAL_EVIDENCE")
        gate = GateStatus.DEGRADED
    else:
        gate = GateStatus.PASS

    return EvidenceAssessment(
        coverage=coverage,
        freshness=freshness,  # type: ignore[arg-type]
        provenance=provenance,  # type: ignore[arg-type]
        critical_missing=critical_missing,
        unresolved_conflicts=unresolved_conflicts,
        decision_gate=gate,
        gate_reasons=tuple(reasons),
    )
