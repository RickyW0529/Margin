# 模块 10：部署与审计实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 Margin 模块 10（部署与审计），提供容器化 Docker Compose 部署、集中式配置、不可变审计记录、结构化日志与 Prometheus 指标、健康/降级端点、故障降级包装器以及 GitHub Actions CI。

**Architecture:** 新增 `src/margin/settings.py` 作为唯一配置源；新增 `src/margin/core/db_audit.py` + `audit_repository.py` 提供 PostgreSQL 不可变审计；新增 `src/margin/core/degradation.py` 统一包装 Provider 调用实现 fallback；新增 `src/margin/core/logging_config.py`、`src/margin/api/middleware.py`、`src/margin/api/metrics.py`、`src/margin/api/routes/health.py` 实现可观测性；新增 Dockerfiles 与 `docker-compose.yml`；新增 `.github/workflows/ci.yml`。所有业务模块通过 `MarginSettings` 读取配置，通过 `AuditRepository` 记录关键对象快照哈希。

**Tech Stack:** Python 3.12, Pydantic Settings, FastAPI, SQLAlchemy, Alembic, structlog, prometheus-client, Docker, Docker Compose, GitHub Actions。

---

## 文件结构映射

**配置与核心基础设施：**

| 文件 | 职责 |
|------|------|
| `src/margin/settings.py` | 集中式 Pydantic BaseSettings |
| `src/margin/core/db_audit.py` | 审计记录 SQLAlchemy 模型 |
| `src/margin/core/audit_repository.py` | 审计仓库 Protocol + 内存/SQLAlchemy 实现 |
| `src/margin/core/degradation.py` | 故障降级包装器与策略 |
| `src/margin/core/logging_config.py` | structlog JSON/Console 配置 |
| `src/margin/api/middleware.py` | trace_id + HTTP 指标 middleware |
| `src/margin/api/metrics.py` | Prometheus registry 与 `/metrics` |
| `src/margin/api/routes/health.py` | `/health`、`/health/ready`、`/health/degraded` |

**部署与脚本：**

| 文件 | 职责 |
|------|------|
| `Dockerfile` | Python API/Worker 镜像 |
| `web/Dockerfile` | Next.js 前端镜像 |
| `docker-compose.yml` | 全栈 Compose |
| `docker/prometheus.yml` | Prometheus scrape 配置 |
| `docker/grafana/provisioning/datasources/datasource.yml` | Grafana 数据源 |
| `docker/grafana/provisioning/dashboards/dashboard.yml` | Grafana dashboard 配置 |
| `scripts/snapshot_store.py` | 本地快照存储脚本 |
| `scripts/migrate.py` | 容器迁移入口 |
| `scripts/health_check.py` | 容器探针 |

**CI：**

| 文件 | 职责 |
|------|------|
| `.github/workflows/ci.yml` | lint / test / docker build |

**测试：**

| 文件 | 职责 |
|------|------|
| `tests/core/test_settings.py` | 配置解析 |
| `tests/core/test_audit_repository.py` | 审计仓库 |
| `tests/core/test_degradation.py` | 降级包装器 |
| `tests/api/test_health.py` | 健康端点 |
| `tests/api/test_metrics.py` | Prometheus 指标 |

---

### Task 1: 集中式配置 `MarginSettings`

**Files:**
- Create: `src/margin/settings.py`
- Modify: `pyproject.toml`（增加 `pydantic-settings` 依赖）
- Test: `tests/core/test_settings.py`

- [ ] **Step 1: 写失败测试**

```python
from margin.settings import MarginSettings


def test_settings_reads_database_url():
    settings = MarginSettings(_env_file=None)
    assert "postgresql" in str(settings.database_url)
    assert settings.log_level in {"DEBUG", "INFO", "WARNING", "ERROR"}
```

Run: `pytest tests/core/test_settings.py::test_settings_reads_database_url -v`
Expected: FAIL "ModuleNotFoundError: No module named 'margin.settings'"

- [ ] **Step 2: 实现 settings**

`src/margin/settings.py`:

```python
"""Centralized application settings for Margin."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class MarginSettings(BaseSettings):
    """Single source of truth for all Margin environment configuration."""

    model_config = SettingsConfigDict(
        env_prefix="MARGIN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: PostgresDsn = "postgresql+psycopg://margin:margin@localhost:5432/margin"
    database_echo: bool = False
    database_pool_pre_ping: bool = True

    # LLM
    llm_api_key: SecretStr | None = None
    llm_base_url: HttpUrl | None = None
    llm_model: str = "deepseek-v4-pro"

    # Embedding
    embedding_base_url: HttpUrl | None = None
    embedding_api_key: SecretStr | None = None
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = 1536

    # Rerank
    rerank_base_url: HttpUrl | None = None
    rerank_api_key: SecretStr | None = None
    rerank_model: str = ""

    # WebSearch
    websearch_api_key: SecretStr | None = None

    # Logging / Observability
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    metrics_enabled: bool = True
    trace_id_header: str = "x-margin-trace-id"

    # Audit
    audit_log_path: Path = Path(".margin") / "audit" / "provider_calls.jsonl"

    # Deployment
    environment: Literal["development", "test", "production"] = "development"
    service_name: str = "margin-api"
    service_version: str = "0.1.0"


@lru_cache
def get_settings() -> MarginSettings:
    """Return cached settings instance."""
    return MarginSettings()
```

在 `pyproject.toml` 的 `dependencies` 中追加：

```toml
"pydantic-settings>=2.0",
"prometheus-client>=0.20",
```

Run:
```bash
pip install -e ".[dev]"
pytest tests/core/test_settings.py::test_settings_reads_database_url -v
```
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add src/margin/settings.py tests/core/test_settings.py pyproject.toml
git commit -m "feat(deployment): add centralized MarginSettings"
```

---

### Task 2: 不可变审计记录表与仓库

**Files:**
- Create: `src/margin/core/db_audit.py`
- Create: `src/margin/core/audit_repository.py`
- Create: `alembic/versions/20260619_0009_audit_records.py`
- Modify: `alembic/env.py`
- Test: `tests/core/test_audit_repository.py`

- [ ] **Step 1: 写失败测试**

```python
from datetime import datetime, UTC

from margin.core.audit_repository import MemoryAuditRepository
from margin.core.models import AuditLogRecord


def test_audit_repository_appends_record():
    repo = MemoryAuditRepository()
    record = AuditLogRecord(
        record_type="research_signal",
        object_id="sig_1",
        trace_id="t1",
        input_hash="sha256:abc",
        output_hash="sha256:def",
    )
    repo.record(record)
    assert len(repo.list_records("research_signal")) == 1
```

Run: `pytest tests/core/test_audit_repository.py::test_audit_repository_appends_record -v`
Expected: FAIL "ModuleNotFoundError: No module named 'margin.core.audit_repository'"

- [ ] **Step 2: 实现模型与仓库**

`src/margin/core/models.py`（若不存在则创建，否则追加）：

```python
"""Shared core domain models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from margin.news.models import ensure_utc, utc_now


class AuditLogRecord(BaseModel):
    """Immutable audit record for critical business objects."""

    record_id: str = Field(default_factory=lambda: f"ar_{uuid.uuid4().hex[:12]}")
    record_type: str
    object_id: str | None = None
    trace_id: str = ""
    input_hash: str | None = None
    output_hash: str | None = None
    payload_json: dict[str, Any] | None = None
    recorded_at: datetime = Field(default_factory=utc_now)
    service_version: str = "0.1.0"

    model_config = {"frozen": True}

    @field_validator("recorded_at")
    @classmethod
    def normalize_recorded_at(cls, value: datetime) -> datetime:
        return ensure_utc(value)
```

`src/margin/core/db_audit.py`:

```python
"""SQLAlchemy ORM model for immutable audit records."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from margin.storage.base import Base


class AuditLogRecordRow(Base):
    """Append-only audit record persisted in PostgreSQL."""

    __tablename__ = "audit_records"
    __table_args__ = (
        Index("ix_audit_records_record_type", "record_type"),
        Index("ix_audit_records_object_id", "object_id"),
        Index("ix_audit_records_trace_id", "trace_id"),
        Index("ix_audit_records_recorded_at", "recorded_at"),
    )

    record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    record_type: Mapped[str] = mapped_column(String(48), nullable=False)
    object_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    input_hash: Mapped[str | None] = mapped_column(String(96), nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(96), nullable=True)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    service_version: Mapped[str] = mapped_column(String(32), nullable=False, default="0.1.0")
```

`src/margin/core/audit_repository.py`:

```python
"""Audit repository for immutable business records."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from margin.core.db_audit import AuditLogRecordRow
from margin.core.models import AuditLogRecord


class AuditRepository(Protocol):
    """Persistence contract for immutable audit records."""

    def record(self, record: AuditLogRecord) -> None:
        """Append an audit record."""
        ...

    def list_records(
        self,
        record_type: str | None = None,
        object_id: str | None = None,
        trace_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditLogRecord]:
        """Return audit records ordered by recorded_at desc."""
        ...


class MemoryAuditRepository:
    """In-memory audit repository for tests."""

    def __init__(self) -> None:
        self._records: dict[str, AuditLogRecord] = {}

    def record(self, record: AuditLogRecord) -> None:
        self._records[record.record_id] = record

    def list_records(
        self,
        record_type: str | None = None,
        object_id: str | None = None,
        trace_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditLogRecord]:
        records = list(self._records.values())
        if record_type is not None:
            records = [r for r in records if r.record_type == record_type]
        if object_id is not None:
            records = [r for r in records if r.object_id == object_id]
        if trace_id is not None:
            records = [r for r in records if r.trace_id == trace_id]
        records = sorted(records, key=lambda r: r.recorded_at, reverse=True)
        return records[:limit]


class SQLAlchemyAuditRepository:
    """PostgreSQL audit repository."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def record(self, record: AuditLogRecord) -> None:
        with self._session_factory.begin() as session:
            session.add(_record_to_row(record))

    def list_records(
        self,
        record_type: str | None = None,
        object_id: str | None = None,
        trace_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditLogRecord]:
        statement = select(AuditLogRecordRow).order_by(AuditLogRecordRow.recorded_at.desc())
        if record_type is not None:
            statement = statement.where(AuditLogRecordRow.record_type == record_type)
        if object_id is not None:
            statement = statement.where(AuditLogRecordRow.object_id == object_id)
        if trace_id is not None:
            statement = statement.where(AuditLogRecordRow.trace_id == trace_id)
        statement = statement.limit(limit)
        with self._session_factory() as session:
            return [_record_from_row(row) for row in session.scalars(statement).all()]


def _record_to_row(record: AuditLogRecord) -> AuditLogRecordRow:
    return AuditLogRecordRow(
        record_id=record.record_id,
        record_type=record.record_type,
        object_id=record.object_id,
        trace_id=record.trace_id,
        input_hash=record.input_hash,
        output_hash=record.output_hash,
        payload_json=record.payload_json,
        recorded_at=record.recorded_at,
        service_version=record.service_version,
    )


def _record_from_row(row: AuditLogRecordRow) -> AuditLogRecord:
    return AuditLogRecord(
        record_id=row.record_id,
        record_type=row.record_type,
        object_id=row.object_id,
        trace_id=row.trace_id,
        input_hash=row.input_hash,
        output_hash=row.output_hash,
        payload_json=dict(row.payload_json) if row.payload_json is not None else None,
        recorded_at=row.recorded_at,
        service_version=row.service_version,
    )
```

`alembic/versions/20260619_0009_audit_records.py`:

```python
"""Create audit_records table."""

from alembic import op
from sqlalchemy import Column, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260619_0009_audit"
down_revision = "20260619_0008_monitoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_records",
        Column("record_id", String(64), primary_key=True),
        Column("record_type", String(48), nullable=False),
        Column("object_id", String(96), nullable=True),
        Column("trace_id", String(64), nullable=False, default=""),
        Column("input_hash", String(96), nullable=True),
        Column("output_hash", String(96), nullable=True),
        Column("payload_json", JSONB, nullable=True),
        Column("recorded_at", DateTime(timezone=True), nullable=False),
        Column("service_version", String(32), nullable=False, default="0.1.0"),
        Index("ix_audit_records_record_type", "record_type"),
        Index("ix_audit_records_object_id", "object_id"),
        Index("ix_audit_records_trace_id", "trace_id"),
        Index("ix_audit_records_recorded_at", "recorded_at"),
    )


def downgrade() -> None:
    op.drop_table("audit_records")
```

在 `alembic/env.py` 追加导入：

```python
from margin.core import db_audit as core_db_audit  # noqa: F401
```

Run: `pytest tests/core/test_audit_repository.py -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add src/margin/core/models.py src/margin/core/db_audit.py src/margin/core/audit_repository.py \
  alembic/versions/20260619_0009_audit_records.py alembic/env.py tests/core/test_audit_repository.py
git commit -m "feat(audit): add immutable audit record repository and migration"
```

---

### Task 3: 本地快照存储脚本

**Files:**
- Create: `scripts/snapshot_store.py`
- Create: `src/margin/core/snapshot_store.py`（供其他模块调用）
- Test: `tests/core/test_snapshot_store.py`

- [ ] **Step 1: 写失败测试**

```python
from margin.core.snapshot_store import FileSnapshotStore


def test_snapshot_store_writes_and_reads():
    store = FileSnapshotStore(base_path=".margin/snapshots")
    entry = store.write(
        object_type="research_report",
        object_id="rep_1",
        payload={"summary": "buy"},
    )
    assert entry.sha256.startswith("sha256:")
    loaded = store.read(entry.snapshot_id)
    assert loaded.payload["summary"] == "buy"
```

Run: `pytest tests/core/test_snapshot_store.py::test_snapshot_store_writes_and_reads -v`
Expected: FAIL "ModuleNotFoundError: No module named 'margin.core.snapshot_store'"

- [ ] **Step 2: 实现快照存储**

`src/margin/core/snapshot_store.py`:

```python
"""Local append-only snapshot store with content addressing."""

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
    """Pointer to a persisted snapshot."""

    snapshot_id: str
    object_type: str
    object_id: str
    snapshot_path: Path
    sha256: str
    created_at: datetime
    metadata: dict[str, Any]


class FileSnapshotStore:
    """Append-only snapshot store on local filesystem."""

    def __init__(self, base_path: str | Path) -> None:
        self._base = Path(base_path)
        self._base.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        object_type: str,
        object_id: str,
        payload: Any,
        metadata: dict[str, Any] | None = None,
    ) -> SnapshotEntry:
        snapshot_id = f"sn_{uuid.uuid4().hex[:12]}"
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
        )
        index_path = self._base / object_type / object_id / "index.jsonl"
        with index_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "snapshot_id": entry.snapshot_id,
                "sha256": entry.sha256,
                "created_at": entry.created_at.isoformat(),
            }, default=str) + "\n")
        return entry

    def read(self, snapshot_id: str) -> SnapshotEntry:
        for path in self._base.rglob(f"{snapshot_id}.json"):
            relative = path.relative_to(self._base)
            parts = relative.parts
            object_type = parts[0]
            object_id = parts[1]
            serialized = path.read_text(encoding="utf-8")
            sha256 = "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()
            return SnapshotEntry(
                snapshot_id=snapshot_id,
                object_type=object_type,
                object_id=object_id,
                snapshot_path=relative,
                sha256=sha256,
                created_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
                metadata={},
            )
        raise KeyError(f"snapshot '{snapshot_id}' not found")

    def list_snapshots(self, object_type: str, object_id: str) -> list[SnapshotEntry]:
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
```

`scripts/snapshot_store.py`:

```python
#!/usr/bin/env python3
"""CLI to write/read snapshots for storage audit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from margin.core.snapshot_store import FileSnapshotStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Margin snapshot store CLI")
    parser.add_argument("--base-path", default=str(Path(".margin") / "snapshots"))
    sub = parser.add_subparsers(dest="command")

    write_parser = sub.add_parser("write")
    write_parser.add_argument("--type", required=True)
    write_parser.add_argument("--object-id", required=True)
    write_parser.add_argument("--payload", required=True, help="JSON string")

    read_parser = sub.add_parser("read")
    read_parser.add_argument("snapshot_id", nargs="?")

    list_parser = sub.add_parser("list")
    list_parser.add_argument("--type", required=True)
    list_parser.add_argument("--object-id", required=True)

    args = parser.parse_args(argv)
    store = FileSnapshotStore(args.base_path)

    if args.command == "write":
        entry = store.write(
            object_type=args.type,
            object_id=args.object_id,
            payload=json.loads(args.payload),
        )
        print(json.dumps({
            "snapshot_id": entry.snapshot_id,
            "sha256": entry.sha256,
            "path": str(entry.snapshot_path),
        }))
        return 0
    if args.command == "read":
        entry = store.read(args.snapshot_id)
        print(json.dumps({
            "snapshot_id": entry.snapshot_id,
            "sha256": entry.sha256,
            "path": str(entry.snapshot_path),
        }))
        return 0
    if args.command == "list":
        entries = store.list_snapshots(args.type, args.object_id)
        print(json.dumps([
            {"snapshot_id": e.snapshot_id, "sha256": e.sha256}
            for e in entries
        ]))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

Run: `pytest tests/core/test_snapshot_store.py -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add src/margin/core/snapshot_store.py scripts/snapshot_store.py tests/core/test_snapshot_store.py
git commit -m "feat(audit): add local append-only snapshot store"
```

---

### Task 4: 结构化日志与 Trace ID

**Files:**
- Create: `src/margin/core/logging_config.py`
- Create: `src/margin/api/middleware.py`
- Modify: `src/margin/api/main.py`
- Test: `tests/api/test_middleware.py`

- [ ] **Step 1: 写失败测试**

```python
from fastapi.testclient import TestClient
from margin.api.main import create_app


def test_trace_id_header_propagates():
    app = create_app()
    @app.get("/echo-trace")
    def echo_trace(request: Request):
        from margin.api.middleware import _get_trace_id
        return {"trace_id": _get_trace_id(request)}

    client = TestClient(app)
    response = client.get("/echo-trace", headers={"x-margin-trace-id": "t-123"})
    assert response.json()["trace_id"] == "t-123"
```

Run: `pytest tests/api/test_middleware.py::test_trace_id_header_propagates -v`
Expected: FAIL "ImportError: cannot import name '...'"

- [ ] **Step 2: 实现日志与 middleware**

`src/margin/core/logging_config.py`:

```python
"""Structured logging configuration using structlog."""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(*, log_level: str = "INFO", log_format: str = "json") -> None:
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.ExtraAdder(),
    ]

    if log_format == "json":
        formatter = structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.processors.dict_tracebacks,
                structlog.processors.JSONRenderer(),
            ],
        )
    else:
        formatter = structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[structlog.dev.ConsoleRenderer()],
        )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level.upper())

    structlog.configure(
        processors=shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
```

`src/margin/api/middleware.py`:

```python
"""FastAPI middleware for trace ID propagation and HTTP metrics."""

from __future__ import annotations

import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from margin.settings import get_settings

_TRACE_KEY = "margin_trace_id"


def _get_trace_id(request: Request) -> str:
    return request.scope.get(_TRACE_KEY, "")


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Populate trace_id from header or generate a new one."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        settings = get_settings()
        trace_id = request.headers.get(settings.trace_id_header) or f"t-{uuid.uuid4().hex[:12]}"
        request.scope[_TRACE_KEY] = trace_id
        response = await call_next(request)
        response.headers[settings.trace_id_header] = trace_id
        return response
```

在 `src/margin/api/main.py` 的 `create_app` 中注册 middleware：

```python
from margin.api.middleware import TraceIdMiddleware
from margin.core.logging_config import configure_logging
from margin.settings import get_settings


def create_app(...) -> FastAPI:
    settings = get_settings()
    configure_logging(log_level=settings.log_level, log_format=settings.log_format)
    application = FastAPI(title="Margin API", version=settings.service_version)
    application.add_middleware(TraceIdMiddleware)
    ...
```

Run: `pytest tests/api/test_middleware.py -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add src/margin/core/logging_config.py src/margin/api/middleware.py src/margin/api/main.py tests/api/test_middleware.py
git commit -m "feat(observability): add structured logging and trace-id middleware"
```

---

### Task 5: Prometheus 指标与 `/metrics`

**Files:**
- Create: `src/margin/api/metrics.py`
- Modify: `src/margin/api/main.py`
- Modify: `src/margin/api/middleware.py`
- Test: `tests/api/test_metrics.py`

- [ ] **Step 1: 写失败测试**

```python
from fastapi.testclient import TestClient
from margin.api.main import create_app


def test_metrics_endpoint_exposes_http_requests():
    app = create_app()
    client = TestClient(app)
    client.get("/health")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "margin_http_requests_total" in response.text
```

Run: `pytest tests/api/test_metrics.py::test_metrics_endpoint_exposes_http_requests -v`
Expected: FAIL（指标不存在）

- [ ] **Step 2: 实现指标**

`src/margin/api/metrics.py`:

```python
"""Prometheus metrics registry and endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest

router = APIRouter(tags=["metrics"])

REGISTRY = CollectorRegistry(auto_describe=True)

HTTP_REQUESTS = Counter(
    "margin_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
    registry=REGISTRY,
)

HTTP_REQUEST_DURATION = Histogram(
    "margin_http_request_duration_seconds",
    "HTTP request duration",
    ["method", "path"],
    registry=REGISTRY,
)

PROVIDER_CALLS = Counter(
    "margin_provider_calls_total",
    "Total provider calls",
    ["provider", "method", "status"],
    registry=REGISTRY,
)

PROVIDER_DEGRADED = Counter(
    "margin_provider_degraded_total",
    "Total degraded provider calls",
    ["provider", "method"],
    registry=REGISTRY,
)


@router.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
```

在 `src/margin/api/middleware.py` 追加 `MetricsMiddleware`：

```python
from margin.api.metrics import HTTP_REQUESTS, HTTP_REQUEST_DURATION


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record HTTP request counts and durations."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path) if route else request.url.path
        HTTP_REQUEST_DURATION.labels(method=request.method, path=path).observe(duration)
        HTTP_REQUESTS.labels(
            method=request.method,
            path=path,
            status_code=response.status_code,
        ).inc()
        return response
```

在 `src/margin/api/main.py` 注册 metrics router 与 middleware：

```python
from margin.api.metrics import router as metrics_router
from margin.api.middleware import MetricsMiddleware, TraceIdMiddleware


def create_app(...) -> FastAPI:
    application.add_middleware(TraceIdMiddleware)
    application.add_middleware(MetricsMiddleware)
    application.include_router(metrics_router)
    ...
```

Run: `pytest tests/api/test_metrics.py -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add src/margin/api/metrics.py src/margin/api/middleware.py src/margin/api/main.py tests/api/test_metrics.py
git commit -m "feat(observability): add Prometheus metrics endpoint"
```

---

### Task 6: 健康/就绪/降级端点

**Files:**
- Create: `src/margin/api/routes/health.py`
- Modify: `src/margin/api/main.py`
- Test: `tests/api/test_health.py`

- [ ] **Step 1: 写失败测试**

```python
from fastapi.testclient import TestClient
from margin.api.main import create_app


def test_health_returns_ok():
    app = create_app()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
```

Run: `pytest tests/api/test_health.py::test_health_returns_ok -v`
Expected: PASS（已有 `/health`，但 `/health/ready` 不存在）

```python
def test_ready_endpoint_checks_database():
    app = create_app()
    client = TestClient(app)
    response = client.get("/health/ready")
    assert response.status_code in {200, 503}
```

Run: `pytest tests/api/test_health.py::test_ready_endpoint_checks_database -v`
Expected: FAIL 404

- [ ] **Step 2: 实现健康路由**

`src/margin/api/routes/health.py`:

```python
"""Health, readiness and degradation endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Response, status

from margin.core.provider import HealthCheckResult, ProviderStatus
from margin.settings import get_settings
from margin.storage.database import DatabaseSettings, create_database_engine

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Simple liveness probe."""
    return {"status": "ok"}


@router.get("/health/ready")
def ready() -> Response:
    """Readiness probe: database must be reachable."""
    settings = get_settings()
    try:
        engine = create_database_engine(
            DatabaseSettings(url=str(settings.database_url))
        )
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return Response(
            content='{"status":"ready"}',
            media_type="application/json",
            status_code=status.HTTP_200_OK,
        )
    except Exception as exc:  # noqa: BLE001
        return Response(
            content=f'{{"status":"not_ready","detail":"{exc}"}}',
            media_type="application/json",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@router.get("/health/degraded")
def degraded() -> dict[str, object]:
    """Return true if database is not ready or any provider is degraded."""
    settings = get_settings()
    degraded_providers: list[HealthCheckResult] = []
    try:
        engine = create_database_engine(
            DatabaseSettings(url=str(settings.database_url))
        )
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        degraded_providers.append(
            HealthCheckResult(
                provider_name="database",
                status=ProviderStatus.UNHEALTHY,
                checked_at=datetime.now(UTC),
                message=str(exc),
            )
        )
    return {
        "degraded": len(degraded_providers) > 0,
        "degraded_count": len(degraded_providers),
        "providers": [r.model_dump() for r in degraded_providers],
        "service": settings.service_name,
        "version": settings.service_version,
    }
```

在 `src/margin/api/main.py` 注册 health router 并移除旧的 `/health`：

```python
from margin.api.routes.health import router as health_router


def create_app(...) -> FastAPI:
    application.include_router(health_router)
    application.include_router(portfolio_router)
    ...
    # remove the inline @application.get("/health") handler
```

Run: `pytest tests/api/test_health.py -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add src/margin/api/routes/health.py src/margin/api/main.py tests/api/test_health.py
git commit -m "feat(health): add ready and degraded endpoints"
```

---

### Task 7: 故障降级包装器

**Files:**
- Create: `src/margin/core/degradation.py`
- Test: `tests/core/test_degradation.py`

- [ ] **Step 1: 写失败测试**

```python
from datetime import datetime

from margin.core.degradation import call_with_fallback
from margin.core.provider import CallResult


def test_degradation_returns_fallback_on_failure():
    def failing(**_):
        raise RuntimeError("provider down")

    def fallback(**_):
        return CallResult(provider_name="x", provider_version="1", success=True, data="fallback")

    result = call_with_fallback(failing, fallback, trace_id="t1", metrics_label="x")
    assert result.from_fallback is True
    assert result.data == "fallback"
```

Run: `pytest tests/core/test_degradation.py::test_degradation_returns_fallback_on_failure -v`
Expected: FAIL "ModuleNotFoundError"

- [ ] **Step 2: 实现降级包装器**

`src/margin/core/degradation.py`:

```python
"""Failure degradation wrapper for Provider calls."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from margin.core.provider import CallResult

logger = logging.getLogger(__name__)


def call_with_fallback(
    fn: Callable[..., CallResult],
    fallback: Callable[..., CallResult] | None,
    *,
    trace_id: str,
    metrics_label: str,
    **kwargs: Any,
) -> CallResult:
    """Call ``fn``; on failure execute ``fallback`` and mark result as degraded.

    Args:
        fn: Primary function to call.
        fallback: Optional fallback function.
        trace_id: Trace identifier for observability.
        metrics_label: Label used for metrics.
        **kwargs: Arguments passed to both functions.

    Returns:
        CallResult with ``from_fallback=True`` if fallback was used.
    """
    try:
        return fn(**kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Primary call failed, attempting fallback",
            extra={
                "trace_id": trace_id,
                "metrics_label": metrics_label,
                "error": str(exc),
            },
        )
        if fallback is None:
            return CallResult(
                provider_name=metrics_label,
                provider_version="",
                success=False,
                error=f"primary failed and no fallback: {exc}",
                from_fallback=False,
            )
        try:
            result = fallback(**kwargs)
            result.from_fallback = True
            return result
        except Exception as fb_exc:  # noqa: BLE001
            return CallResult(
                provider_name=metrics_label,
                provider_version="",
                success=False,
                error=f"primary: {exc}; fallback: {fb_exc}",
                from_fallback=True,
            )
```

Run: `pytest tests/core/test_degradation.py -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add src/margin/core/degradation.py tests/core/test_degradation.py
git commit -m "feat(degradation): add provider call degradation wrapper"
```

---

### Task 8: Docker 镜像与 Docker Compose

**Files:**
- Create: `Dockerfile`
- Create: `web/Dockerfile`
- Create: `docker-compose.yml`
- Create: `docker/prometheus.yml`
- Create: `docker/grafana/provisioning/datasources/datasource.yml`
- Create: `docker/grafana/provisioning/dashboards/dashboard.yml`
- Create: `scripts/migrate.py`
- Create: `scripts/health_check.py`

- [ ] **Step 1: 创建 Dockerfile**

`Dockerfile`:

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install -e ".[dev]"

COPY scripts ./scripts
COPY alembic ./alembic
COPY alembic.ini ./

EXPOSE 8000

CMD ["uvicorn", "margin.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`web/Dockerfile`:

```dockerfile
FROM node:20-slim

ENV NODE_ENV=production

WORKDIR /app

COPY web/package.json web/package-lock.json* ./
RUN npm ci

COPY web ./
RUN npm run build

EXPOSE 3000

CMD ["npm", "start"]
```

- [ ] **Step 2: 创建 Docker Compose**

`docker-compose.yml`:

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: margin
      POSTGRES_USER: margin
      POSTGRES_PASSWORD: margin
    volumes:
      - margin-postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U margin -d margin"]
      interval: 2s
      timeout: 5s
      retries: 20

  api:
    build:
      context: .
      dockerfile: Dockerfile
    environment:
      MARGIN_DATABASE_URL: postgresql+psycopg://margin:margin@postgres:5432/margin
      MARGIN_LOG_LEVEL: INFO
      MARGIN_LOG_FORMAT: json
      MARGIN_METRICS_ENABLED: "true"
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - margin-audit:/app/.margin/audit
      - margin-snapshots:/app/.margin/snapshots
    command: ["uvicorn", "margin.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

  worker:
    build:
      context: .
      dockerfile: Dockerfile
    environment:
      MARGIN_DATABASE_URL: postgresql+psycopg://margin:margin@postgres:5432/margin
      MARGIN_LOG_LEVEL: INFO
      MARGIN_LOG_FORMAT: json
    depends_on:
      postgres:
        condition: service_healthy
    command: ["python", "-m", "scripts.seed_demo"]

  web:
    build:
      context: ./web
      dockerfile: Dockerfile
    environment:
      NEXT_PUBLIC_API_URL: http://api:8000
    ports:
      - "3000:3000"
    depends_on:
      - api

  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./docker/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    ports:
      - "9090:9090"
    depends_on:
      - api

  grafana:
    image: grafana/grafana:latest
    environment:
      GF_SECURITY_ADMIN_PASSWORD: margin
    volumes:
      - ./docker/grafana/provisioning:/etc/grafana/provisioning:ro
      - margin-grafana:/var/lib/grafana
    ports:
      - "3001:3000"
    depends_on:
      - prometheus

volumes:
  margin-postgres:
  margin-audit:
  margin-snapshots:
  margin-grafana:
```

`docker/prometheus.yml`:

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: "margin-api"
    static_configs:
      - targets: ["api:8000"]
    metrics_path: /metrics
```

`docker/grafana/provisioning/datasources/datasource.yml`:

```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
```

`docker/grafana/provisioning/dashboards/dashboard.yml`:

```yaml
apiVersion: 1
providers:
  - name: "default"
    folder: "Margin"
    type: file
    options:
      path: /etc/grafana/provisioning/dashboards
```

`scripts/migrate.py`:

```python
#!/usr/bin/env python3
"""Run Alembic migrations inside container."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    return subprocess.call(["alembic", "upgrade", "head"])


if __name__ == "__main__":
    sys.exit(main())
```

`scripts/health_check.py`:

```python
#!/usr/bin/env python3
"""Container readiness probe."""

from __future__ import annotations

import sys
import urllib.request


def main() -> int:
    try:
        with urllib.request.urlopen("http://localhost:8000/health/ready", timeout=5) as resp:
            return 0 if resp.status == 200 else 1
    except Exception:  # noqa: BLE001
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: 验证构建**

Run:
```bash
docker compose build
```
Expected: 成功构建 api 与 web 镜像（不保证运行时外部 API Key）。

- [ ] **Step 4: 提交**

```bash
git add Dockerfile web/Dockerfile docker-compose.yml docker/ scripts/migrate.py scripts/health_check.py
git commit -m "feat(deployment): add Docker Compose stack for api/web/worker/postgres/prometheus/grafana"
```

---

### Task 9: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: 创建 CI 工作流**

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_DB: margin
          POSTGRES_USER: margin
          POSTGRES_PASSWORD: margin
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 2s
          --health-timeout 5s
          --health-retries 20
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: pip install -e ".[dev]"
      - name: Lint
        run: ruff check src tests
      - name: Run migrations
        env:
          MARGIN_DATABASE_URL: postgresql+psycopg://margin:margin@localhost:5432/margin
        run: alembic upgrade head
      - name: Test
        env:
          MARGIN_DATABASE_URL: postgresql+psycopg://margin:margin@localhost:5432/margin
        run: pytest

  docker:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build API image
        run: docker build -t margin-api .
      - name: Build Web image
        run: docker build -t margin-web ./web
```

- [ ] **Step 2: 提交**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add GitHub Actions workflow for lint/test/docker build"
```

---

### Task 10: 最终验证

**Files:** 全部新增/修改文件

- [ ] **Step 1: 安装依赖**

Run: `pip install -e ".[dev]"`
Expected: 成功安装

- [ ] **Step 2: 运行 lint**

Run: `ruff check src tests`
Expected: PASS

- [ ] **Step 3: 运行测试**

Run: `pytest`
Expected: PASS

- [ ] **Step 4: 本地 Docker Compose 启动**

Run:
```bash
docker compose up -d postgres
sleep 5
docker compose run --rm api alembic upgrade head
docker compose up -d api web prometheus grafana
```
Expected: `curl http://localhost:8000/health` 返回 `{"status":"ok"}`，`curl http://localhost:8000/metrics` 返回 Prometheus 指标。

- [ ] **Step 5: 提交**

```bash
git add .
git commit -m "feat(deployment_audit): complete module 10 MVP"
```

---

## 计划自查

### Spec 覆盖检查

| 设计文档章节 | 实现任务 |
|-------------|---------|
| 5.1 MarginSettings | Task 1 |
| 5.2 AuditRepository / 4.1 AuditLogRecord | Task 2 |
| 5.3 DegradationWrapper | Task 7 |
| 5.4 HealthChecker / 6. API 健康端点 | Task 6 |
| 4.2 SnapshotEntry / 5. 快照 | Task 3 |
| 7. Docker Compose | Task 8 |
| 8. 安全与降级 | Task 7 + Task 8 |
| 9. 测试策略 | 各 Task 均含测试 |
| 10. CI 验收 | Task 9 |

### Placeholder 扫描

- 无 TBD / TODO / "implement later" / "add appropriate error handling" 等占位符。
- 每个代码步骤均包含具体代码或具体修改位置。

### 类型一致性检查

- `AuditLogRecord.recorded_at` 使用 UTC datetime，与 SQLAlchemy `DateTime(timezone=True)` 一致。
- `MarginSettings.database_url` 为 `PostgresDsn`，构造 engine 时转换为 `str`。
- `DegradationWrapper` 返回 `CallResult`，复用现有 `margin.core.provider.CallResult`。
- Prometheus 指标在 middleware 中按 `method/path/status_code` 打标签，与 `/metrics` endpoint 一致。

## 执行交接

计划已保存到 `docs/superpowers/plans/2026-06-19-module-10-deployment-audit.md`。

**两种执行方式：**

1. **Subagent-Driven（推荐）**：按任务逐个派发子代理，每个任务完成后做 spec compliance + code quality 两轮审查。
2. **Inline Execution**：在当前会话按任务批次直接执行，关键节点 checkpoint 后给你确认。

你选哪种？
