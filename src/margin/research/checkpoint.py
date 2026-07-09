"""PostgreSQL-backed LangGraph checkpoint persistence.

The v0.2 AI research graph uses LangGraph for orchestration, but keeps
checkpoint storage inside Margin-owned audit tables so graph state, node audit,
LLM audit, and final delta-review publication are recoverable from one
database boundary.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from typing import Any

from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    PendingWrite,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from langgraph.checkpoint.serde.base import SerializerProtocol
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.types import RunnableConfig
from sqlalchemy.orm import Session

from margin.research.db_models import AIGraphCheckpointRow, AIGraphRunRow
from margin.sql.research_queries import checkpoint_row, checkpoints_list

_CheckpointKey = tuple[str, str, str]


class PostgresGraphCheckpointer(BaseCheckpointSaver[int]):
    """LangGraph checkpoint saver backed by Margin-owned audit tables.."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        serde: SerializerProtocol | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize the checkpointer.

        Args:
            session_factory: Callable[[], Session]: .
            serde: SerializerProtocol | None: .
            clock: Callable[[], datetime] | None: .

        Returns:
            None: .
        """
        if serde is None:
            serde = JsonPlusSerializer()
        super().__init__(serde=serde)
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._pending_writes: dict[_CheckpointKey, list[dict[str, Any]]] = {}

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """Load one checkpoint tuple, validating the requested graph identity.

        Args:
            config: RunnableConfig: .

        Returns:
            CheckpointTuple | None: .
        """
        thread_id, checkpoint_ns = _thread_and_namespace(config)
        checkpoint_id = get_checkpoint_id(config)
        requested_identity_hash = config["configurable"].get("identity_hash")
        with self._session_factory() as session:
            row = self._load_checkpoint_row(
                session,
                thread_id=thread_id,
                checkpoint_ns=checkpoint_ns,
                checkpoint_id=checkpoint_id,
            )
            if row is None:
                return None
            if requested_identity_hash is not None and row.identity_hash != requested_identity_hash:
                raise ValueError("identity_hash mismatch for graph checkpoint")
            return self._row_to_checkpoint_tuple(row)

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        """List checkpoints ordered newest-first.

        Args:
            config: RunnableConfig | None: .
            filter: dict[str, Any] | None: .
            before: RunnableConfig | None: .
            limit: int | None: .

        Yields:
            Any: .
        """
        before_checkpoint_id = get_checkpoint_id(before) if before else None
        with self._session_factory() as session:
            thread_id = None
            checkpoint_ns = None
            checkpoint_id = None
            if config is not None:
                thread_id, checkpoint_ns = _thread_and_namespace(config)
                checkpoint_id = get_checkpoint_id(config)
            statement = checkpoints_list(
                thread_id=thread_id,
                checkpoint_ns=checkpoint_ns,
                checkpoint_id=checkpoint_id,
                before_checkpoint_id=before_checkpoint_id,
            )
            rows = session.scalars(statement).all()

        yielded = 0
        for row in rows:
            item = self._row_to_checkpoint_tuple(row)
            if filter and not all(item.metadata.get(key) == value for key, value in filter.items()):
                continue
            if limit is not None and yielded >= limit:
                break
            yielded += 1
            yield item

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Persist a checkpoint and return its updated runnable config.

        Args:
            config: RunnableConfig: .
            checkpoint: Checkpoint: .
            metadata: CheckpointMetadata: .
            new_versions: ChannelVersions: .

        Returns:
            RunnableConfig: .
        """
        del new_versions
        thread_id, checkpoint_ns = _thread_and_namespace(config)
        checkpoint_id = str(checkpoint["id"])
        identity_hash = _identity_hash_from_config(config)
        checkpoint_payload = _dump_typed(self.serde, checkpoint)
        checkpoint_metadata = _dump_typed(
            self.serde,
            get_checkpoint_metadata(config, metadata),
        )
        state_hash = _hash_json(checkpoint_payload)
        parent_checkpoint_id = config["configurable"].get("checkpoint_id")

        with self._session_factory.begin() as session:
            if session.get(AIGraphRunRow, thread_id) is None:
                raise ValueError(f"graph run does not exist: {thread_id}")
            row = self._load_checkpoint_row(
                session,
                thread_id=thread_id,
                checkpoint_ns=checkpoint_ns,
                checkpoint_id=checkpoint_id,
            )
            if row is not None:
                if (
                    row.identity_hash != identity_hash
                    or row.state_hash != state_hash
                    or row.parent_checkpoint_id != parent_checkpoint_id
                ):
                    raise ValueError("conflicting graph checkpoint replay")
            else:
                pending_writes = self._pending_writes.pop(
                    (thread_id, checkpoint_ns, checkpoint_id),
                    [],
                )
                session.add(
                    AIGraphCheckpointRow(
                        graph_run_id=thread_id,
                        checkpoint_ns=checkpoint_ns,
                        checkpoint_id=checkpoint_id,
                        parent_checkpoint_id=parent_checkpoint_id,
                        identity_hash=identity_hash,
                        state_hash=state_hash,
                        state_payload={"checkpoint": checkpoint_payload},
                        checkpoint_metadata={
                            "metadata": checkpoint_metadata,
                            "pending_writes": pending_writes,
                        },
                        created_at=self._clock(),
                    )
                )

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
                "identity_hash": identity_hash,
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Persist pending writes for a checkpoint, deduplicated by task/index.

        Args:
            config: RunnableConfig: .
            writes: Sequence[tuple[str, Any]]: .
            task_id: str: .
            task_path: str: .

        Returns:
            None: .
        """
        thread_id, checkpoint_ns = _thread_and_namespace(config)
        checkpoint_id = str(config["configurable"]["checkpoint_id"])
        with self._session_factory.begin() as session:
            row = self._load_checkpoint_row(
                session,
                thread_id=thread_id,
                checkpoint_ns=checkpoint_ns,
                checkpoint_id=checkpoint_id,
                for_update=True,
            )
            if row is None:
                self._buffer_pending_writes(
                    thread_id=thread_id,
                    checkpoint_ns=checkpoint_ns,
                    checkpoint_id=checkpoint_id,
                    writes=writes,
                    task_id=task_id,
                    task_path=task_path,
                )
                return
            metadata = dict(row.checkpoint_metadata)
            pending_writes = list(metadata.get("pending_writes", []))
            existing_keys = {(item["task_id"], int(item["write_index"])) for item in pending_writes}
            for index, (channel, value) in enumerate(writes):
                write_index = int(WRITES_IDX_MAP.get(channel, index))
                key = (task_id, write_index)
                if write_index >= 0 and key in existing_keys:
                    continue
                pending_writes.append(
                    {
                        "task_id": task_id,
                        "channel": channel,
                        "write_index": write_index,
                        "task_path": task_path,
                        "value": _dump_typed(self.serde, value),
                    }
                )
                existing_keys.add(key)
            metadata["pending_writes"] = pending_writes
            row.checkpoint_metadata = metadata

    def _buffer_pending_writes(
        self,
        *,
        thread_id: str,
        checkpoint_ns: str,
        checkpoint_id: str,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str,
    ) -> None:
        """Buffer pending writes in memory before a checkpoint row exists.

        Args:
            thread_id: str: .
            checkpoint_ns: str: .
            checkpoint_id: str: .
            writes: Sequence[tuple[str, Any]]: .
            task_id: str: .
            task_path: str: .

        Returns:
            None: .
        """
        key = (thread_id, checkpoint_ns, checkpoint_id)
        pending_writes = self._pending_writes.setdefault(key, [])
        existing_keys = {(item["task_id"], int(item["write_index"])) for item in pending_writes}
        for index, (channel, value) in enumerate(writes):
            write_index = int(WRITES_IDX_MAP.get(channel, index))
            item_key = (task_id, write_index)
            if write_index >= 0 and item_key in existing_keys:
                continue
            pending_writes.append(
                {
                    "task_id": task_id,
                    "channel": channel,
                    "write_index": write_index,
                    "task_path": task_path,
                    "value": _dump_typed(self.serde, value),
                }
            )
            existing_keys.add(item_key)

    def delete_thread(self, thread_id: str) -> None:
        """Preserve append-only graph checkpoints instead of deleting them.

        Args:
            thread_id: str: .

        Returns:
            None: .
        """
        del thread_id

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """Async wrapper around :meth:`get_tuple`.

        Args:
            config: RunnableConfig: .

        Returns:
            CheckpointTuple | None: .
        """
        return self.get_tuple(config)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ):
        """Async wrapper around :meth:`list`.

        Args:
            config: RunnableConfig | None: .
            filter: dict[str, Any] | None: .
            before: RunnableConfig | None: .
            limit: int | None: .

        Yields:
            Any: .
        """
        for item in self.list(config, filter=filter, before=before, limit=limit):
            yield item

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Async wrapper around :meth:`put_writes`.

        Args:
            config: RunnableConfig: .
            writes: Sequence[tuple[str, Any]]: .
            task_id: str: .
            task_path: str: .

        Returns:
            None: .
        """
        self.put_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        """Async wrapper around append-only delete behavior.

        Args:
            thread_id: str: .

        Returns:
            None: .
        """
        self.delete_thread(thread_id)

    def _load_checkpoint_row(
        self,
        session: Session,
        *,
        thread_id: str,
        checkpoint_ns: str,
        checkpoint_id: str | None,
        for_update: bool = False,
    ) -> AIGraphCheckpointRow | None:
        """Load one checkpoint row, optionally acquiring a row lock.

        Args:
            session: Session: .
            thread_id: str: .
            checkpoint_ns: str: .
            checkpoint_id: str | None: .
            for_update: bool: .

        Returns:
            AIGraphCheckpointRow | None: .
        """
        statement = checkpoint_row(thread_id, checkpoint_ns, checkpoint_id)
        if for_update:
            statement = statement.with_for_update()
        return session.scalars(statement).first()

    def _row_to_checkpoint_tuple(
        self,
        row: AIGraphCheckpointRow,
    ) -> CheckpointTuple:
        """Convert a persisted checkpoint row into a LangGraph tuple.

        Args:
            row: AIGraphCheckpointRow: .

        Returns:
            CheckpointTuple: .
        """
        checkpoint = _load_typed(self.serde, row.state_payload["checkpoint"])
        metadata_payload = row.checkpoint_metadata.get("metadata")
        metadata = _load_typed(self.serde, metadata_payload) if metadata_payload is not None else {}
        pending_writes = _load_pending_writes(
            self.serde,
            row.checkpoint_metadata.get("pending_writes", []),
        )
        config: RunnableConfig = {
            "configurable": {
                "thread_id": row.graph_run_id,
                "checkpoint_ns": row.checkpoint_ns,
                "checkpoint_id": row.checkpoint_id,
                "identity_hash": row.identity_hash,
            }
        }
        parent_config: RunnableConfig | None = (
            {
                "configurable": {
                    "thread_id": row.graph_run_id,
                    "checkpoint_ns": row.checkpoint_ns,
                    "checkpoint_id": row.parent_checkpoint_id,
                    "identity_hash": row.identity_hash,
                }
            }
            if row.parent_checkpoint_id
            else None
        )
        return CheckpointTuple(
            config=config,
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=pending_writes,
        )


def _thread_and_namespace(config: RunnableConfig) -> tuple[str, str]:
    """Extract thread ID and checkpoint namespace from a runnable config.

    Args:
        config: RunnableConfig: .

    Returns:
        tuple[str, str]: .
    """
    configurable = config["configurable"]
    return str(configurable["thread_id"]), str(configurable.get("checkpoint_ns", ""))


def _identity_hash_from_config(config: RunnableConfig) -> str:
    """Return the required identity hash from a runnable config.

    Args:
        config: RunnableConfig: .

    Returns:
        str: .
    """
    identity_hash = config["configurable"].get("identity_hash")
    if not identity_hash:
        raise ValueError("identity_hash is required for graph checkpoint persistence")
    return str(identity_hash)


def _dump_typed(
    serde: SerializerProtocol,
    value: Any,
) -> dict[str, str]:
    """Serialize a value to a base64-encoded typed dict.

    Args:
        serde: SerializerProtocol: .
        value: Any: .

    Returns:
        dict[str, str]: .
    """
    type_tag, data = serde.dumps_typed(value)
    if isinstance(data, str):
        data = data.encode("utf-8")
    return {
        "type": type_tag,
        "data": base64.b64encode(data).decode("ascii"),
    }


def _load_typed(
    serde: SerializerProtocol,
    payload: dict[str, str],
) -> Any:
    """Deserialize a base64-encoded typed dict back into a Python value.

    Args:
        serde: SerializerProtocol: .
        payload: dict[str, str]: .

    Returns:
        Any: .
    """
    return serde.loads_typed(
        (
            payload["type"],
            base64.b64decode(payload["data"].encode("ascii")),
        )
    )


def _load_pending_writes(
    serde: SerializerProtocol,
    rows: list[dict[str, Any]],
) -> list[PendingWrite]:
    """Deserialize buffered pending writes into LangGraph PendingWrite tuples.

    Args:
        serde: SerializerProtocol: .
        rows: list[dict[str, Any]]: .

    Returns:
        list[PendingWrite]: .
    """
    return [
        (
            str(item["task_id"]),
            str(item["channel"]),
            _load_typed(serde, item["value"]),
        )
        for item in rows
    ]


def _hash_json(payload: dict[str, Any]) -> str:
    """Return a deterministic SHA-256 hash for a JSON-serializable payload.

    Args:
        payload: dict[str, Any]: .

    Returns:
        str: .
    """
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
