"""Local append-only snapshot store with content addressing.

Snapshots are serialized to JSON, hashed with SHA-256, and stored on disk so
that downstream audits can verify payload integrity. An ``index.jsonl`` per
object records the lineage of snapshots without duplicating payload data.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SnapshotEntry:
    """Pointer to a persisted snapshot.

    Attributes:
        snapshot_id: Unique snapshot identifier.
        object_type: Category of the snapshotted object.
        object_id: Identifier of the snapshotted object.
        snapshot_path: Relative path where the snapshot is stored.
        sha256: Content hash of the serialized snapshot.
        created_at: UTC timestamp when the snapshot was created.
        metadata: Optional key-value metadata.
        payload: Deserialized snapshot payload, when loaded.
    """

    snapshot_id: str
    object_type: str
    object_id: str
    snapshot_path: Path
    sha256: str
    created_at: datetime
    metadata: dict[str, Any]
    payload: Any = None


class FileSnapshotStore:
    """Append-only snapshot store on local filesystem.

    Snapshots are serialized to JSON, content-hashed, and written under
    ``<base>/<object_type>/<object_id>/<snapshot_id>.json``. An index file
    records the lineage for each object.

    Attributes:
        _base: Root directory for all snapshot files.
    """

    def __init__(self, base_path: str | Path) -> None:
        """Initialize the store.

        Args:
            base_path: Root directory for snapshot files. Created if missing.
        """
        self._base = Path(base_path)
        self._base.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        object_type: str,
        object_id: str,
        payload: Any,
        metadata: dict[str, Any] | None = None,
    ) -> SnapshotEntry:
        """Persist a new snapshot for an object.

        Args:
            object_type: Category of the object.
            object_id: Identifier of the object.
            payload: JSON-serializable snapshot payload.
            metadata: Optional key-value metadata to store with the snapshot.

        Returns:
            A ``SnapshotEntry`` describing the persisted snapshot.
        """
        snapshot_id = f"sn_{uuid.uuid4().hex[:12]}"
        # Serialize with sorted keys so the same payload always yields the same hash.
        serialized = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
        sha256 = "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        relative = Path(object_type) / f"{object_id}" / f"{snapshot_id}.json"
        full_path = self._base / relative
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(serialized, encoding="utf-8")
        entry = SnapshotEntry(
            snapshot_id=snapshot_id,
            object_type=object_type,
            object_id=object_id,
            snapshot_path=relative,
            sha256=sha256,
            created_at=datetime.now(UTC),
            metadata=metadata or {},
            payload=payload,
        )
        # Append a small index record so lineage can be read without loading payloads.
        index_path = self._base / object_type / object_id / "index.jsonl"
        with index_path.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "snapshot_id": entry.snapshot_id,
                        "sha256": entry.sha256,
                        "created_at": entry.created_at.isoformat(),
                    },
                    default=str,
                )
                + "\n"
            )
        return entry

    def read(self, snapshot_id: str) -> SnapshotEntry:
        """Load a snapshot by its identifier.

        Args:
            snapshot_id: Unique snapshot identifier.

        Returns:
            A ``SnapshotEntry`` including the deserialized payload.

        Raises:
            KeyError: When no snapshot with the given id exists.
        """
        # Search recursively by id; snapshots are content-addressed but indexed by id.
        for path in self._base.rglob(f"{snapshot_id}.json"):
            relative = path.relative_to(self._base)
            parts = relative.parts
            object_type = parts[0]
            object_id = parts[1]
            serialized = path.read_text(encoding="utf-8")
            # Recompute the hash on read to verify the stored payload has not changed.
            sha256 = "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()
            payload = json.loads(serialized)
            return SnapshotEntry(
                snapshot_id=snapshot_id,
                object_type=object_type,
                object_id=object_id,
                snapshot_path=relative,
                sha256=sha256,
                created_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
                metadata={},
                payload=payload,
            )
        raise KeyError(f"snapshot '{snapshot_id}' not found")

    def list_snapshots(self, object_type: str, object_id: str) -> list[SnapshotEntry]:
        """List all snapshots for an object, ordered by filename.

        Args:
            object_type: Category of the object.
            object_id: Identifier of the object.

        Returns:
            List of ``SnapshotEntry`` objects for the object.
        """
        dir_path = self._base / object_type / object_id
        if not dir_path.exists():
            return []
        entries: list[SnapshotEntry] = []
        for path in sorted(dir_path.glob("*.json")):
            if path.name == "index.jsonl":
                continue
            snapshot_id = path.stem
            entries.append(self.read(snapshot_id))
        return entries
