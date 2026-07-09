"""Shared HTTP-level idempotency helpers for mutating API routes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from fastapi import HTTPException, status
from pydantic import BaseModel

from margin.core.hashing import stable_json_hash
from margin.platform_runtime.repository import IdempotencyKeyRecord

_DEFAULT_TTL = timedelta(hours=24)


class IdempotencyStore(Protocol):
    """Minimal store interface used by route-level replay."""

    def get_idempotency_key(self, idempotency_key: str) -> IdempotencyKeyRecord | None:
        """Return a prior record when present."""

    def record_idempotency_key(self, record: IdempotencyKeyRecord) -> None:
        """Persist a completed request/response pair."""


@dataclass(frozen=True)
class IdempotencyBegin:
    """Result of looking up an idempotency key before execution."""

    scoped_key: str
    request_hash: str
    replay_payload: Any | None = None


def begin_idempotent(
    store: IdempotencyStore,
    *,
    scope: str,
    idempotency_key: str,
    request_payload: Any,
) -> IdempotencyBegin:
    """Return a replay payload when present, otherwise proceed metadata.

    Raises:
        HTTPException: 409 when the same key was used with a different body.
    """
    request_hash = stable_json_hash(_normalize_payload(request_payload))
    scoped_key = f"{scope}:{idempotency_key}"
    existing = store.get_idempotency_key(scoped_key)
    if existing is None:
        return IdempotencyBegin(scoped_key=scoped_key, request_hash=request_hash)
    if existing.request_hash != request_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "idempotency_key_conflict",
                "message": "Idempotency-Key was reused with a different request body",
            },
        )
    if existing.status == "completed" and existing.response_ref:
        return IdempotencyBegin(
            scoped_key=scoped_key,
            request_hash=request_hash,
            replay_payload=json.loads(existing.response_ref),
        )
    return IdempotencyBegin(scoped_key=scoped_key, request_hash=request_hash)


def complete_idempotent(
    store: IdempotencyStore,
    *,
    scope: str,
    scoped_key: str,
    request_hash: str,
    response_payload: Any,
    ttl: timedelta = _DEFAULT_TTL,
    now: datetime | None = None,
) -> Any:
    """Persist a successful response for later replay and return it.

    On concurrent insert races, returns the first writer's payload when the
    request hash matches.
    """
    resolved_now = now or datetime.now(UTC)
    response_json = json.dumps(
        _normalize_payload(response_payload),
        ensure_ascii=False,
        sort_keys=True,
    )
    record = IdempotencyKeyRecord(
        idempotency_key=scoped_key,
        scope=scope,
        request_hash=request_hash,
        response_hash=stable_json_hash(json.loads(response_json)),
        response_ref=response_json,
        status="completed",
        created_at=resolved_now,
        expires_at=resolved_now + ttl,
    )
    try:
        store.record_idempotency_key(record)
        return response_payload
    except ValueError:
        raced = store.get_idempotency_key(scoped_key)
        if (
            raced is not None
            and raced.request_hash == request_hash
            and raced.status == "completed"
            and raced.response_ref
        ):
            return json.loads(raced.response_ref)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "idempotency_key_conflict",
                "message": "Idempotency-Key was reused with a different request body",
            },
        ) from None


def _normalize_payload(payload: Any) -> Any:
    """Convert pydantic models and nested payloads into JSON-compatible data."""
    if isinstance(payload, BaseModel):
        return payload.model_dump(mode="json")
    if isinstance(payload, dict):
        return {str(key): _normalize_payload(value) for key, value in payload.items()}
    if isinstance(payload, list | tuple):
        return [_normalize_payload(item) for item in payload]
    return payload
