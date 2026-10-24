"""Scheduled audit gate: operational health is not independent PIT completeness."""
from pathlib import Path

from tradingagents_tw.truth.capture_operator import MAX_POLL_GAP_SECONDS


def test_scheduled_health_gate_is_read_only_and_fail_closed():
    workflow = (Path(__file__).resolve().parents[1]
                / ".github" / "workflows" / "pit-health.yml").read_text(
                    encoding="utf-8"
                )
    assert 'cron: "0 1 * * *"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "contents: read" in workflow
    assert "contents: write" not in workflow
    assert "ref: pit-capture" in workflow
    assert "persist-credentials: false" in workflow
    assert "python -m pip install -e ." in workflow
    assert ("--archive-root pit-archive/data/pit --audit-only"
            in workflow)
    assert "continue-on-error:" not in workflow
    assert "|| true" not in workflow
    assert "git push" not in workflow
    # 09:00 local after a skipped 19:17 capture is >30h after
    # the preceding day's last 19:17 capture.
    assert (37 * 3600 + 43 * 60) > MAX_POLL_GAP_SECONDS
