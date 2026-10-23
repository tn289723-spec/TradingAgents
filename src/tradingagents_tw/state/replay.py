from __future__ import annotations

import json
from tradingagents_tw.contracts import StateSnapshot


def canonical_state_json(state: StateSnapshot) -> str:
    """Stable serialization used by replay/invariant tests."""
    return json.dumps(
        state.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
