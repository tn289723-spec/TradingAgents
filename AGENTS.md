# AGENTS.md — TradingAgents-TW v0.1

## Mission
Implement a Taiwan-stock post-market research and decision-error-prevention system. Do not build autonomous trading.

## Non-negotiable boundary
1. **Truth** — deterministic evidence integrity, provenance, point-in-time, corporate actions, conflict/revision handling.
2. **State** — deterministic/statistical trend, relative strength, flow, directional score.
3. **Judgment** — LLM interpretation only. LLM may not rewrite Truth or State.

## Construction order
Contracts → Truth → Point-in-Time → Corporate Actions → Trend → Directional Score → Reporting → Judgment.

## Fail-closed rules
- Future evidence relative to analysis cutoff: reject.
- Critical missing evidence: gate cannot be PASS.
- Unresolved critical source conflict: BLOCKED.
- Unknown schema/enum/timestamp coercion: reject.
- Raw and adjusted price bases may not be silently mixed.
- Directional Score is not probability.
- Same TruthSnapshot + config + engine version must yield the same State.

## Scope control
Do not add adaptive weighting, RL, automatic execution, model voting as evidence, or new capabilities without an ADR and explicit measurable gap.

## Testing
Every invariant implemented in code requires a regression test. Prefer pure functions and deterministic fixtures. Never weaken a test to make an implementation pass.
