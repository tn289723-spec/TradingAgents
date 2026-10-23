# TradingAgents-TW v0.1 Bootstrap

Engineering bootstrap for the Taiwan post-market decision-error prevention system.

## Core boundary
- Truth: deterministic evidence integrity and point-in-time.
- State: deterministic/statistical market state.
- Judgment: LLM interpretation only; not implemented in V0.1 bootstrap.

## Run
```bash
pytest
```

## Current scope
- Strict schema contracts
- Point-in-time enforcement
- Critical-missing evidence gate
- Deterministic trend baseline
- Explainable directional score

This bootstrap intentionally does **not** implement autonomous trading, adaptive weighting, or LLM authority over Truth/State.
