from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Protocol, runtime_checkable

from tradingagents_tw.contracts import TruthSnapshot
from .identity import derive_truth_content_hash


class SnapshotStoreError(RuntimeError):
    pass


class SnapshotNotFound(SnapshotStoreError):
    pass


class SnapshotImmutableError(SnapshotStoreError):
    pass


class SnapshotIntegrityError(SnapshotStoreError):
    pass


@runtime_checkable
class TruthSnapshotStore(Protocol):
    def put(self, snapshot: TruthSnapshot) -> None:
        ...

    def replay(self, snapshot_id: str) -> TruthSnapshot:
        ...


def verify_snapshot_integrity(snapshot: TruthSnapshot) -> None:
    expected = derive_truth_content_hash(
        symbol=snapshot.symbol,
        trade_date=snapshot.trade_date,
        analysis_cutoff=snapshot.analysis_cutoff,
        evidence=snapshot.evidence,
        assessment=snapshot.assessment,
        config_hash=snapshot.config_hash,
        schema_version=snapshot.schema_version,
    )
    if expected != snapshot.content_hash:
        raise SnapshotIntegrityError(
            f"snapshot content hash mismatch: expected {expected}, got {snapshot.content_hash}"
        )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class FileTruthSnapshotStore:
    """Immutable filesystem reference store.

    Objects are keyed by TruthSnapshot.content_hash. Snapshot IDs are immutable
    refs that point to those content-addressed objects. Replay never contacts a
    provider.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.refs = self.root / "refs"
        self.objects.mkdir(parents=True, exist_ok=True)
        self.refs.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _ref_key(snapshot_id: str) -> str:
        if not snapshot_id:
            raise SnapshotStoreError("snapshot_id cannot be empty")
        return hashlib.sha256(snapshot_id.encode("utf-8")).hexdigest()

    def _ref_path(self, snapshot_id: str) -> Path:
        return self.refs / f"{self._ref_key(snapshot_id)}.json"

    def _object_path(self, content_hash: str) -> Path:
        return self.objects / f"{content_hash}.json"

    @staticmethod
    def _write_atomic(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def put(self, snapshot: TruthSnapshot) -> None:
        verify_snapshot_integrity(snapshot)

        ref_path = self._ref_path(snapshot.snapshot_id)
        if ref_path.exists():
            ref = json.loads(ref_path.read_text(encoding="utf-8"))
            if ref.get("snapshot_id") != snapshot.snapshot_id:
                raise SnapshotIntegrityError("snapshot ref key collision")
            if ref.get("content_hash") != snapshot.content_hash:
                raise SnapshotImmutableError(
                    f"snapshot_id {snapshot.snapshot_id!r} already points to different content"
                )
            existing = self.replay(snapshot.snapshot_id)
            if existing.content_hash != snapshot.content_hash:
                raise SnapshotIntegrityError("existing snapshot ref failed integrity check")
            return

        object_path = self._object_path(snapshot.content_hash)
        object_payload = snapshot.model_dump(mode="json", exclude={"snapshot_id"})
        if object_path.exists():
            stored = json.loads(object_path.read_text(encoding="utf-8"))
            candidate = TruthSnapshot.model_validate(
                {"snapshot_id": snapshot.snapshot_id, **stored}
            )
            verify_snapshot_integrity(candidate)
            if candidate.content_hash != snapshot.content_hash:
                raise SnapshotIntegrityError("content-addressed object mismatch")
        else:
            self._write_atomic(object_path, _canonical_json(object_payload))

        ref_payload = {
            "snapshot_id": snapshot.snapshot_id,
            "content_hash": snapshot.content_hash,
        }
        self._write_atomic(ref_path, _canonical_json(ref_payload))

    def replay(self, snapshot_id: str) -> TruthSnapshot:
        ref_path = self._ref_path(snapshot_id)
        if not ref_path.exists():
            raise SnapshotNotFound(snapshot_id)

        ref = json.loads(ref_path.read_text(encoding="utf-8"))
        if ref.get("snapshot_id") != snapshot_id:
            raise SnapshotIntegrityError("snapshot ref identity mismatch")
        content_hash = str(ref.get("content_hash", ""))
        object_path = self._object_path(content_hash)
        if not object_path.exists():
            raise SnapshotIntegrityError("snapshot object is missing")

        payload = json.loads(object_path.read_text(encoding="utf-8"))
        snapshot = TruthSnapshot.model_validate(
            {"snapshot_id": snapshot_id, **payload}
        )
        if snapshot.content_hash != content_hash:
            raise SnapshotIntegrityError("snapshot ref/object hash mismatch")
        verify_snapshot_integrity(snapshot)
        return snapshot
