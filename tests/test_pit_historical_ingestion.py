"""Synthetic end-to-end signed PIT ingestion; not proof of real archive coverage."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import hashlib
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from test_historical_replay import setup_case
from tradingagents_tw.providers.registry import Market
from tradingagents_tw.truth.archive import build_attestation, capture_action
from tradingagents_tw.truth.attestation import SignedCoverageProof
from tradingagents_tw.truth.historical_replay import ingest_historical, replay_historical

DOMAIN = b"TradingAgents-TW/PIT-coverage/Ed25519/v1\x00"
KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
PUB = KEY.public_key().public_bytes(
    encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
).hex()
TRUST = {"independent-fixture-attestor": PUB}
TZ = ZoneInfo("Asia/Taipei")


def signed_case(tmp_path, market=Market.TWSE):
    args, _, calls = setup_case(tmp_path, market)
    args["config"] = args["config"].model_copy(update={"archive_mode": "SIGNED_PIT_V1"})
    action = args["announcements"][0]
    record = capture_action(
        market=market.value, symbol=args["request"].symbol, source=action.source,
        event_key=action.evidence_id, revision_id=action.revision_id,
        raw_payload=action.payload, published_at=action.published_at,
        clock=lambda: action.observed_at,
    )
    args["announcements"] = (action.model_copy(update={"source_record_id": record.record_hash}),)
    request = args["request"]
    manifest = build_attestation(
        market=market.value, symbol=request.symbol,
        start_date=request.start_date, end_date=request.end_date,
        analysis_cutoff=request.analysis_cutoff,
        capture_started_at=datetime.combine(
            request.start_date - timedelta(days=1), time.min, tzinfo=TZ,
        ),
        capture_ended_at=request.analysis_cutoff,
        observed_at=request.analysis_cutoff, coverage="COMPLETE",
        record_hashes=(record.record_hash,),
        attestation_id="independent-fixture-attestor",
    )
    proof = SignedCoverageProof(
        attestation_id=manifest.attestation_id,
        attestation_hash=manifest.attestation_hash,
        signature_hex=KEY.sign(DOMAIN + bytes.fromhex(manifest.attestation_hash)).hex(),
    )
    bundle = {
        "version": "historical-action-coverage-signed-v1",
        "legacy_coverage": args["coverage"].payload,
        "manifest": manifest.model_dump(mode="json"),
        "records": [record.model_dump(mode="json")],
        "proof": proof.model_dump(mode="json"),
    }
    args["coverage"] = args["coverage"].model_copy(update={
        "payload": bundle,
        "published_at": request.analysis_cutoff,
        "observed_at": request.analysis_cutoff,
        "content_hash": hashlib.sha256(json.dumps(bundle, sort_keys=True).encode()).hexdigest(),
    })
    return args, calls


@pytest.mark.parametrize("market", list(Market))
def test_signed_capture_bound_to_ingest_and_offline_replay(tmp_path, market):
    args, calls = signed_case(tmp_path, market)
    args["trusted_public_keys"] = TRUST
    snapshot = ingest_historical(**args)
    assert len(calls) == 4
    assert snapshot.assessment.decision_gate.value == "PASS"
    with pytest.raises(ValueError, match="not independently trusted"):
        replay_historical(store=args["store"], snapshot_id=args["snapshot_id"])
    args["provider"]._fetch_json = lambda _: pytest.fail("replay must be offline")
    replayed = replay_historical(
        store=args["store"], snapshot_id=args["snapshot_id"],
        trusted_public_keys=TRUST, require_live_pit=True,
    )
    assert len(replayed.adjusted.bars) >= 60
    assert replayed.truth_hash == snapshot.content_hash
    with pytest.raises(ValueError, match="not independently trusted"):
        replay_historical(
            store=args["store"], snapshot_id=args["snapshot_id"],
            trusted_public_keys={"independent-fixture-attestor": "0" * 64},
        )


@pytest.mark.parametrize("fault", [
    "missing-key", "wrong-key", "bad-signature", "partial", "missing-record",
    "changed-action", "unbound-action", "changed-revision", "wrong-market",
    "future-coverage", "legacy-window",
])
def test_signed_gate_blocks_before_provider_and_persistence(tmp_path, fault):
    args, calls = signed_case(tmp_path)
    args["trusted_public_keys"] = TRUST
    coverage = args["coverage"]
    bundle = dict(coverage.payload)
    if fault == "missing-key":
        args["trusted_public_keys"] = {}
    elif fault == "wrong-key":
        args["trusted_public_keys"] = {next(iter(TRUST)): "0" * 64}
    elif fault == "bad-signature":
        bundle["proof"] = {**bundle["proof"], "signature_hex": "0" * 128}
    elif fault == "partial":
        bundle["manifest"] = {**bundle["manifest"], "coverage": "PARTIAL"}
    elif fault == "missing-record":
        bundle["records"] = []
    elif fault == "changed-action":
        action = args["announcements"][0]
        args["announcements"] = (action.model_copy(update={
            "payload": {**action.payload, "cash_dividend": 123},
        }),)
    elif fault == "unbound-action":
        action = args["announcements"][0]
        args["announcements"] = (action.model_copy(update={"source_record_id": "not-a-record"}),)
    elif fault == "changed-revision":
        action = args["announcements"][0]
        args["announcements"] = (action.model_copy(update={"revision_id": "forged"}),)
    elif fault == "wrong-market":
        bundle["manifest"] = {**bundle["manifest"], "market": "TPEX"}
    elif fault == "future-coverage":
        coverage = coverage.model_copy(update={
            "observed_at": args["request"].analysis_cutoff + timedelta(seconds=1),
        })
    elif fault == "legacy-window":
        bundle["legacy_coverage"] = {**bundle["legacy_coverage"], "start_date": "2026-01-03"}
    args["coverage"] = coverage.model_copy(update={"payload": bundle})
    with pytest.raises(ValueError):
        ingest_historical(**args)
    assert calls == []
    assert not tuple(args["store"].refs.iterdir())


def test_legacy_golden_explicitly_cannot_certify_live_pit(tmp_path):
    args, _ = signed_case(tmp_path)
    args["config"] = args["config"].model_copy(update={"archive_mode": "SYNTHETIC_FIXTURE_ONLY"})
    # Legacy fixture mode never accepts a signed wrapper as legacy self-attestation.
    with pytest.raises(ValueError):
        ingest_historical(**args)
