"""Persisted user-facing Agent chat sessions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from margin.agent_runtime.db_models import AgentChatMessageRow, AgentChatSessionRow


class AgentChatSession(BaseModel):
    """One user-facing chat session.."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    title: str
    scope_version_id: str
    universe: str
    language: str
    created_at: datetime
    updated_at: datetime


class AgentChatMessage(BaseModel):
    """One persisted chat message.."""

    model_config = ConfigDict(extra="forbid")

    message_id: str
    session_id: str
    role: str
    content: str
    run_id: str | None = None
    payload: dict
    created_at: datetime


class AgentChatSessionDetail(BaseModel):
    """A session plus ordered messages.."""

    model_config = ConfigDict(extra="forbid")

    session: AgentChatSession
    messages: list[AgentChatMessage]


class AgentChatRepository(Protocol):
    """Persistence contract for user-facing Agent chat history.."""

    def get_session(self, session_id: str) -> AgentChatSession | None:
        """Return one session by ID.

        Args:
            session_id: str: .

        Returns:
            AgentChatSession | None: .
        """

    def list_sessions(self, *, limit: int = 20) -> list[AgentChatSession]:
        """List recent sessions newest first.

        Args:
            limit: int: .

        Returns:
            list[AgentChatSession]: .
        """

    def upsert_session(self, session: AgentChatSession) -> AgentChatSession:
        """Create or update a session.

        Args:
            session: AgentChatSession: .

        Returns:
            AgentChatSession: .
        """

    def add_message(self, message: AgentChatMessage) -> AgentChatMessage:
        """Persist a chat message idempotently.

        Args:
            message: AgentChatMessage: .

        Returns:
            AgentChatMessage: .
        """

    def list_messages(
        self,
        session_id: str,
        *,
        limit: int | None = None,
    ) -> list[AgentChatMessage]:
        """List messages oldest first.

        Args:
            session_id: str: .
            limit: int | None: .

        Returns:
            list[AgentChatMessage]: .
        """

    def get_session_detail(self, session_id: str) -> AgentChatSessionDetail | None:
        """Return a session with ordered messages.

        Args:
            session_id: str: .

        Returns:
            AgentChatSessionDetail | None: .
        """


class MemoryAgentChatRepository:
    """In-memory chat repository for deterministic tests.."""

    def __init__(self) -> None:
        """Process __init__.

        Returns:
            None: .
        """
        self._sessions: dict[str, AgentChatSession] = {}
        self._messages: dict[str, AgentChatMessage] = {}
        self._message_order: list[str] = []

    def get_session(self, session_id: str) -> AgentChatSession | None:
        """Process get_session.

        Args:
            session_id: str: .

        Returns:
            AgentChatSession | None: .
        """
        return self._sessions.get(session_id)

    def list_sessions(self, *, limit: int = 20) -> list[AgentChatSession]:
        """Process list_sessions.

        Args:
            limit: int: .

        Returns:
            list[AgentChatSession]: .
        """
        return sorted(
            self._sessions.values(),
            key=lambda session: session.updated_at,
            reverse=True,
        )[:limit]

    def upsert_session(self, session: AgentChatSession) -> AgentChatSession:
        """Process upsert_session.

        Args:
            session: AgentChatSession: .

        Returns:
            AgentChatSession: .
        """
        self._sessions[session.session_id] = session
        return session

    def add_message(self, message: AgentChatMessage) -> AgentChatMessage:
        """Process add_message.

        Args:
            message: AgentChatMessage: .

        Returns:
            AgentChatMessage: .
        """
        current = self._messages.get(message.message_id)
        if current is not None and current != message:
            raise ValueError(f"chat message '{message.message_id}' is immutable")
        if current is None:
            self._message_order.append(message.message_id)
        self._messages[message.message_id] = message
        session = self._sessions.get(message.session_id)
        if session is not None and message.created_at > session.updated_at:
            self._sessions[session.session_id] = session.model_copy(
                update={"updated_at": message.created_at}
            )
        return message

    def list_messages(
        self,
        session_id: str,
        *,
        limit: int | None = None,
    ) -> list[AgentChatMessage]:
        """Process list_messages.

        Args:
            session_id: str: .
            limit: int | None: .

        Returns:
            list[AgentChatMessage]: .
        """
        messages = [
            self._messages[message_id]
            for message_id in self._message_order
            if self._messages[message_id].session_id == session_id
        ]
        if limit is None:
            return messages
        return messages[-limit:]

    def get_session_detail(self, session_id: str) -> AgentChatSessionDetail | None:
        """Process get_session_detail.

        Args:
            session_id: str: .

        Returns:
            AgentChatSessionDetail | None: .
        """
        session = self.get_session(session_id)
        if session is None:
            return None
        return AgentChatSessionDetail(
            session=session,
            messages=self.list_messages(session_id),
        )


class SQLAlchemyAgentChatRepository:
    """SQLAlchemy-backed chat repository.."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Process __init__.

        Args:
            session_factory: Callable[[], Session]: .

        Returns:
            None: .
        """
        self._session_factory = session_factory

    def get_session(self, session_id: str) -> AgentChatSession | None:
        """Process get_session.

        Args:
            session_id: str: .

        Returns:
            AgentChatSession | None: .
        """
        with self._session_factory() as session:
            row = session.get(AgentChatSessionRow, session_id)
            return _session_from_row(row) if row else None

    def list_sessions(self, *, limit: int = 20) -> list[AgentChatSession]:
        """Process list_sessions.

        Args:
            limit: int: .

        Returns:
            list[AgentChatSession]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(
                select(AgentChatSessionRow)
                .order_by(AgentChatSessionRow.updated_at.desc())
                .limit(limit)
            ).all()
            return [_session_from_row(row) for row in rows]

    def upsert_session(self, chat_session: AgentChatSession) -> AgentChatSession:
        """Process upsert_session.

        Args:
            chat_session: AgentChatSession: .

        Returns:
            AgentChatSession: .
        """
        with self._session_factory.begin() as session:
            current = session.get(AgentChatSessionRow, chat_session.session_id)
            if current is None:
                session.add(_session_to_row(chat_session))
                return chat_session
            current.title = chat_session.title
            current.scope_version_id = chat_session.scope_version_id
            current.universe = chat_session.universe
            current.language = chat_session.language
            current.updated_at = chat_session.updated_at
            return chat_session

    def add_message(self, message: AgentChatMessage) -> AgentChatMessage:
        """Process add_message.

        Args:
            message: AgentChatMessage: .

        Returns:
            AgentChatMessage: .
        """
        with self._session_factory.begin() as session:
            current = session.get(AgentChatMessageRow, message.message_id)
            if current is None:
                session.add(_message_to_row(message))
            elif _message_from_row(current) != message:
                raise ValueError(f"chat message '{message.message_id}' is immutable")
            session_row = session.get(AgentChatSessionRow, message.session_id)
            if session_row is not None and message.created_at > session_row.updated_at:
                session_row.updated_at = message.created_at
            return message

    def list_messages(
        self,
        session_id: str,
        *,
        limit: int | None = None,
    ) -> list[AgentChatMessage]:
        """Process list_messages.

        Args:
            session_id: str: .
            limit: int | None: .

        Returns:
            list[AgentChatMessage]: .
        """
        statement = (
            select(AgentChatMessageRow)
            .where(AgentChatMessageRow.session_id == session_id)
            .order_by(AgentChatMessageRow.created_at.asc())
        )
        with self._session_factory() as session:
            rows = session.scalars(statement).all()
            messages = [_message_from_row(row) for row in rows]
        if limit is None:
            return messages
        return messages[-limit:]

    def get_session_detail(self, session_id: str) -> AgentChatSessionDetail | None:
        """Process get_session_detail.

        Args:
            session_id: str: .

        Returns:
            AgentChatSessionDetail | None: .
        """
        session = self.get_session(session_id)
        if session is None:
            return None
        return AgentChatSessionDetail(
            session=session,
            messages=self.list_messages(session_id),
        )


def new_chat_session(
    *,
    session_id: str,
    title: str,
    scope_version_id: str,
    universe: str,
    language: str,
    now: datetime | None = None,
) -> AgentChatSession:
    """Build a new chat session model.

    Args:
        session_id: str: .
        title: str: .
        scope_version_id: str: .
        universe: str: .
        language: str: .
        now: datetime | None: .

    Returns:
        AgentChatSession: .
    """
    timestamp = now or datetime.now(UTC)
    return AgentChatSession(
        session_id=session_id,
        title=title[:200],
        scope_version_id=scope_version_id,
        universe=universe,
        language=language,
        created_at=timestamp,
        updated_at=timestamp,
    )


def new_chat_message(
    *,
    message_id: str,
    session_id: str,
    role: str,
    content: str,
    run_id: str | None = None,
    payload: dict | None = None,
    now: datetime | None = None,
) -> AgentChatMessage:
    """Build a new chat message model.

    Args:
        message_id: str: .
        session_id: str: .
        role: str: .
        content: str: .
        run_id: str | None: .
        payload: dict | None: .
        now: datetime | None: .

    Returns:
        AgentChatMessage: .
    """
    return AgentChatMessage(
        message_id=message_id,
        session_id=session_id,
        role=role,
        content=content,
        run_id=run_id,
        payload=payload or {},
        created_at=now or datetime.now(UTC),
    )


def summarize_messages_for_prompt(messages: list[AgentChatMessage]) -> list[dict[str, str]]:
    """Return compact context rows safe for prompt rendering.

    Args:
        messages: list[AgentChatMessage]: .

    Returns:
        list[dict[str, str]]: .
    """
    return [
        {
            "role": message.role,
            "content": message.content[:2000],
            "created_at": message.created_at.isoformat(),
        }
        for message in messages
    ]


def _session_to_row(session: AgentChatSession) -> AgentChatSessionRow:
    """Process _session_to_row.

    Args:
        session: AgentChatSession: .

    Returns:
        AgentChatSessionRow: .
    """
    return AgentChatSessionRow(
        session_id=session.session_id,
        title=session.title,
        scope_version_id=session.scope_version_id,
        universe=session.universe,
        language=session.language,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _session_from_row(row: AgentChatSessionRow) -> AgentChatSession:
    """Process _session_from_row.

    Args:
        row: AgentChatSessionRow: .

    Returns:
        AgentChatSession: .
    """
    return AgentChatSession(
        session_id=row.session_id,
        title=row.title,
        scope_version_id=row.scope_version_id,
        universe=row.universe,
        language=row.language,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _message_to_row(message: AgentChatMessage) -> AgentChatMessageRow:
    """Process _message_to_row.

    Args:
        message: AgentChatMessage: .

    Returns:
        AgentChatMessageRow: .
    """
    return AgentChatMessageRow(
        message_id=message.message_id,
        session_id=message.session_id,
        role=message.role,
        content=message.content,
        run_id=message.run_id,
        payload=message.payload,
        created_at=message.created_at,
    )


def _message_from_row(row: AgentChatMessageRow) -> AgentChatMessage:
    """Process _message_from_row.

    Args:
        row: AgentChatMessageRow: .

    Returns:
        AgentChatMessage: .
    """
    return AgentChatMessage(
        message_id=row.message_id,
        session_id=row.session_id,
        role=row.role,
        content=row.content,
        run_id=row.run_id,
        payload=row.payload,
        created_at=row.created_at,
    )
