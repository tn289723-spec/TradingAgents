"""Synthetic signatures exercise the independent trust boundary, not live PIT."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tradingagents_tw.truth.archive import build_attestation, capture_action
from tradingagents_tw.truth.attestation import (
    SignedCoverageProof, verify_signed_archive, verify_signed_coverage,
)

TZ = ZoneInfo("Asia/Taipei")
START, END = date(2026, 10, 22), date(2026, 10, 23)
CUTOFF = datetime(2026, 10, 23, 20, tzinfo=TZ)
DOMAIN = b"TradingAgents-TW/PIT-coverage/Ed25519/v1\x00"
KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
PUB = KEY.public_key().public_bytes(
    encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
).hex()


def manifest(records=()):
    return build_attestation(
        market="TWSE", symbol="2330", start_date=START, end_date=END,
        analysis_cutoff=CUTOFF,
        capture_started_at=datetime(2026, 10, 21, tzinfo=TZ),
        capture_ended_at=CUTOFF, observed_at=CUTOFF, coverage="COMPLETE",
        record_hashes=tuple(sorted(r.record_hash for r in records)),
        attestation_id="external-auditor-test-only",
    )


def proof(m):
    return SignedCoverageProof(
        attestation_id=m.attestation_id, attestation_hash=m.attestation_hash,
        signature_hex=KEY.sign(DOMAIN + bytes.fromhex(m.attestation_hash)).hex(),
    )


def check(m, records=(), p=None, keys=None):
    return verify_signed_archive(
        m, records, p or proof(m), trusted_public_keys=keys if keys is not None
        else {m.attestation_id: PUB}, market="TWSE", symbol="2330",
        start=START, end=END, cutoff=CUTOFF,
    )


def test_trusted_signed_no_action_is_explicit_not_inferred():
    m = manifest()
    assert check(m) == ()
    assert verify_signed_coverage(m, proof(m), trusted_public_keys={m.attestation_id: PUB})


def test_trusted_signed_revision_replay_is_deterministic():
    first = capture_action(
        market="TWSE", symbol="2330", source="TWSE_ARCHIVE",
        event_key="exdiv:2330", revision_id="r1",
        raw_payload={"event_date": "2026-10-23", "cash_dividend": 2},
        published_at=CUTOFF - timedelta(hours=3),
        clock=lambda: CUTOFF - timedelta(hours=2),
    )
    second = capture_action(
        market="TWSE", symbol="2330", source="TWSE_ARCHIVE",
        event_key="exdiv:2330", revision_id="r2", supersedes_revision_id="r1",
        raw_payload={"event_date": "2026-10-23", "cash_dividend": 3},
        published_at=CUTOFF - timedelta(hours=2),
        clock=lambda: CUTOFF - timedelta(hours=1),
    )
    records = (first, second)
    m = manifest(records)
    assert check(m, records) == (second,)
    assert check(m, tuple(reversed(records))) == (second,)


@pytest.mark.parametrize("fault", [
    "missing-key", "wrong-key", "wrong-domain", "changed-hash",
    "changed-id", "malformed-signature", "tampered-manifest", "missing-record",
    "partial-coverage", "wrong-board", "future-cutoff",
])
def test_untrusted_or_incomplete_proof_blocks(fault):
    action = capture_action(
        market="TWSE", symbol="2330", source="TWSE_ARCHIVE",
        event_key="exdiv:2330", revision_id="r1",
        raw_payload={"event_date": "2026-10-23", "cash_dividend": 2},
        clock=lambda: CUTOFF - timedelta(hours=1),
    )
    records = (action,)
    m = manifest(records)
    p = proof(m)
    keys = {m.attestation_id: PUB}
    if fault == "missing-key":
        keys = {}
    elif fault == "wrong-key":
        keys = {m.attestation_id: Ed25519PrivateKey.generate().public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
        ).hex()}
    elif fault == "wrong-domain":
        p = p.model_copy(update={"signature_hex": KEY.sign(bytes.fromhex(m.attestation_hash)).hex()})
    elif fault == "changed-hash":
        p = p.model_copy(update={"attestation_hash": "0" * 64})
    elif fault == "changed-id":
        p = p.model_copy(update={"attestation_id": "not-the-attestor"})
    elif fault == "malformed-signature":
        p = p.model_copy(update={"signature_hex": "bad"})
    elif fault == "tampered-manifest":
        m = m.model_copy(update={"symbol": "2317"})
    elif fault == "missing-record":
        records = ()
    elif fault == "partial-coverage":
        m = m.model_copy(update={"coverage": "PARTIAL"})
    elif fault == "wrong-board":
        m = m.model_copy(update={"market": "TPEX"})
    elif fault == "future-cutoff":
        m = m.model_copy(update={"observed_at": CUTOFF + timedelta(seconds=1)})
    with pytest.raises(ValueError):
        check(m, records, p, keys)


def test_signed_coverage_does_not_auto_trust_latest_only_feed():
    m = manifest()
    with pytest.raises(ValueError, match="not independently trusted"):
        verify_signed_coverage(m, proof(m), trusted_public_keys={})
