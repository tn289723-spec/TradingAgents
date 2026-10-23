"""Independently signed PIT coverage: public-key trust root, never a self-claim.

The keyring must be supplied out of band by the operator. This verifies the
attestor's signature, not the truth of the attestor's coverage assertion.
An exchange latest-only response is never a trusted attestation.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field

from tradingagents_tw.contracts import StrictModel
from .archive import CapturedAction, CoverageAttestation, verify_archive_coverage

_DOMAIN = b"TradingAgents-TW/PIT-coverage/Ed25519/v1\x00"
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_HEX128 = re.compile(r"[0-9a-f]{128}\Z")


class SignedCoverageProof(StrictModel):
    version: Literal["pit-coverage-ed25519-v1"] = "pit-coverage-ed25519-v1"
    attestation_id: str = Field(min_length=1)
    attestation_hash: str
    signature_hex: str


def verify_signed_coverage(
    manifest: CoverageAttestation, proof: SignedCoverageProof,
    *, trusted_public_keys: Mapping[str, str],
) -> bool:
    """Accept only an independently pinned Ed25519 key; fail closed otherwise.

    Key values are lowercase hex-encoded 32-byte raw Ed25519 public keys.
    No TOFU, implicit keys, signature bypass, or key fetched from the manifest.
    """
    CoverageAttestation.model_validate(manifest.model_dump(mode="json"))
    SignedCoverageProof.model_validate(proof.model_dump(mode="json"))
    if (proof.attestation_id != manifest.attestation_id
            or proof.attestation_hash != manifest.attestation_hash
            or not _HEX64.fullmatch(proof.attestation_hash)
            or not _HEX128.fullmatch(proof.signature_hex)):
        raise ValueError("PIT coverage signature identity/hash/encoding mismatch")
    public_key_hex = trusted_public_keys.get(proof.attestation_id)
    if not isinstance(public_key_hex, str) or not _HEX64.fullmatch(public_key_hex):
        raise ValueError("PIT coverage attestor is not independently trusted")
    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        public_key.verify(
            bytes.fromhex(proof.signature_hex),
            _DOMAIN + bytes.fromhex(manifest.attestation_hash),
        )
    except (InvalidSignature, ValueError) as exc:
        raise ValueError("invalid PIT coverage attestor signature") from exc
    return True


def verify_signed_archive(
    manifest: CoverageAttestation, records: tuple[CapturedAction, ...],
    proof: SignedCoverageProof, *, trusted_public_keys: Mapping[str, str],
    market: str, symbol: str, start: date, end: date, cutoff: datetime,
) -> tuple[CapturedAction, ...]:
    """Verify signature AND complete PIT coverage before releasing active actions."""
    verify_signed_coverage(manifest, proof, trusted_public_keys=trusted_public_keys)
    return verify_archive_coverage(
        manifest, records, market=market, symbol=symbol, start=start, end=end,
        cutoff=cutoff, trusted_attestation=lambda candidate:
        candidate.attestation_hash == manifest.attestation_hash,
    )
