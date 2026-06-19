# 模块 10：部署与审计（Deployment & Audit）设计文档

> 对应产品 §13.1 / §15 条目 1/9/10、架构 §5 / §21 / §22 / §23 / §24 / §25 / §26-Phase1、spec `docs/spec/v0.1/10-deployment_audit/spec.md` 及计划 `docs/plan/v0.1/10-deployment_audit/`。

## 1. 目标

为 Margin v0.1 提供可一键本地启动的容器化部署、不可变的审计快照、基础可观测性与统一的故障降级策略，使模块 01-09 在本地与 CI 中可重复、可追踪、可降级运行。模块必须：

- 通过 `docker compose up` 启动 web、api、worker、postgres、prometheus、grafana；
- 使用 Pydantic `BaseSettings` 统一管理环境变量与 Secret，替代散落在各处的 `os.getenv`；
- 保留文件级 JSONL 审计日志的同时，在 PostgreSQL 中建立不可变审计记录表，用于研究信号等关键对象的输入/输出哈希；
- 暴露 Prometheus `/metrics`、结构化日志、trace_id 传播；
- 提供 `/health`、`/health/ready`、`/health/degraded` 端点，汇总服务与 Provider 健康状态；
- 在 Provider/Adapter 层引入统一的降级包装器，异常时返回 `from_fallback=True` 的 `CallResult`，并停止发布高置信研究信号；
- 提供 GitHub Actions CI 工作流，执行 ruff / pytest / Docker 构建检查。

## 2. 关键决策

### 2.1 单仓库 Docker Compose

MVP 采用单机 Docker Compose，所有服务共享同一 Git 仓库。不引入 Kubernetes/Helm。可选服务 `redis`、`qdrant` 默认关闭，通过 `compose.override.yml` 或环境变量启用。

### 2.2 配置集中化

新增 `src/margin/settings.py`，使用 `pydantic-settings` 的 `BaseSettings` 统一读取 `MARGIN_*` 变量。数据库、LLM、Embedding、日志级别、可观测性开关均从 `MarginSettings` 获取。Secret 通过 `MARGIN_SECRET_*` 或 `~/.margin/secrets/` 文件解析，复用现有 `SecretManager`。

### 2.3 审计双写

- 运行时 Provider 调用继续写入 `~/.margin/audit/provider_calls.jsonl`（现有 `AuditLogger`），保证本地优先；
- 关键业务对象（研究信号、策略版本、持仓交易）通过 `AuditRepository` 写入 PostgreSQL `audit_records` 表，保留 `input_hash`、`output_hash`、`trace_id`、`action_type`、`recorded_at`，实现跨服务不可变审计。

### 2.4 可观测性最小集合

- Prometheus 指标：HTTP 请求数/延迟、Provider 调用成功/失败/降级次数、各模块业务计数；
- 结构化日志：`structlog` 输出 JSON，注入 `trace_id`、`service_name`、`version`；
- 追踪字段：在 FastAPI middleware 与 Provider 调用中传播 `trace_id`。

### 2.5 故障降级原则

宁可 `ABSTAINED`，也不输出虚假的高置信结论。统一包装器 `DegradationWrapper` 捕获异常后：

1. 记录失败指标与审计；
2. 若存在 fallback 函数（如上一次的旧数据、关键词检索、规则型报告）则执行；
3. 返回 `CallResult(from_fallback=True, success=False/True)`；
4. 调用方根据 `from_fallback` 降低置信度或标记 `abstained`。

## 3. 模块边界

新增/修改后端文件：

| 文件 | 职责 |
|------|------|
| `src/margin/settings.py` | 集中式 `MarginSettings`（Pydantic BaseSettings） |
| `src/margin/core/audit_repository.py` | PostgreSQL 不可变审计记录仓库 |
| `src/margin/core/db_audit.py` | `AuditRecordRow` SQLAlchemy 模型 |
| `src/margin/core/degradation.py` | `DegradationWrapper`、`DegradationPolicy`、`fallback` 装饰器 |
| `src/margin/core/logging_config.py` | `structlog` JSON 日志配置 |
| `src/margin/api/middleware.py` | `trace_id` middleware、HTTP 请求指标 middleware |
| `src/margin/api/routes/health.py` | `/health`、`/health/ready`、`/health/degraded` |
| `src/margin/api/metrics.py` | Prometheus registry 与 `/metrics` endpoint |
| `src/margin/api/main.py` | 注册 health router、metrics、middleware |
| `src/margin/api/dependencies.py` | 从 `MarginSettings` 构造服务 |
| `src/margin/storage/database.py` | 可选：支持 `pool_pre_ping` 与 settings 注入 |
| `scripts/snapshot_store.py` | 存储快照脚本（原始对象 → 本地目录 + 哈希） |
| `scripts/migrate.py` | 容器内 Alembic 迁移入口 |
| `scripts/health_check.py` | 容器就绪/存活探测脚本 |
| `Dockerfile` | Python 后端/Worker 镜像 |
| `web/Dockerfile` | Next.js 前端镜像 |
| `docker-compose.yml` | 全栈 Compose |
| `docker/prometheus.yml` | Prometheus scrape 配置 |
| `docker/grafana/provisioning/` | Grafana datasource + dashboard 预配置 |
| `.github/workflows/ci.yml` | CI 工作流 |

新增测试：

| 文件 | 职责 |
|------|------|
| `tests/core/test_settings.py` | 环境变量解析与 Secret 注入 |
| `tests/core/test_audit_repository.py` | 审计记录 append-only |
| `tests/core/test_degradation.py` | 降级包装器行为 |
| `tests/api/test_health.py` | 健康端点 |
| `tests/api/test_metrics.py` | Prometheus 指标 |

## 4. 数据模型

### 4.1 AuditLogRecord（业务审计）

```text
record_id: str              # ar_<hex>
record_type: str            # research_signal | strategy_version | trade | provider_call | review
object_id: str | None
trace_id: str
input_hash: str | None
output_hash: str | None
payload_json: dict[str, Any] | None
recorded_at: datetime
service_version: str
```

### 4.2 SnapshotEntry（存储快照）

```text
snapshot_id: str            # sn_<hex>
object_type: str            # raw_data | research_report | provider_response
object_id: str
snapshot_path: str          # 本地相对路径
sha256: str
created_at: datetime
metadata: dict[str, Any]
```

## 5. 核心服务

### 5.1 MarginSettings

- `database_url: PostgresDsn`
- `database_echo: bool`
- `llm_api_key: SecretStr | None`
- `llm_base_url: HttpUrl | None`
- `embedding_*`, `rerank_*`
- `log_level: str`
- `log_format: Literal["json", "console"]`
- `metrics_enabled: bool`
- `trace_id_header: str = "x-margin-trace-id"`

### 5.2 AuditRepository

- `record(record: AuditLogRecord) -> None`
- `list_records(record_type, object_id, trace_id, limit) -> list[AuditLogRecord]`
- 仅追加，不修改。

### 5.3 DegradationWrapper

```python
def call_with_fallback(
    fn: Callable[..., CallResult],
    fallback: Callable[..., CallResult] | None,
    *,
    trace_id: str,
    metrics_label: str,
) -> CallResult:
    ...
```

行为：

1. 尝试执行 `fn`；
2. 异常时记录失败指标与审计；
3. 若 `fallback` 存在则执行；
4. 返回结果，设置 `from_fallback=True`；
5. 若 fallback 也失败，返回 `CallResult(success=False, error=...)`。

### 5.4 HealthChecker

- `check_database() -> HealthCheckResult`
- `check_providers() -> list[HealthCheckResult]`
- `is_ready() -> bool`
- `is_degraded() -> bool`

## 6. API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 简单存活 |
| GET | `/health/ready` | 数据库就绪 + 核心 Provider 健康 |
| GET | `/health/degraded` | 是否处于降级模式 |
| GET | `/metrics` | Prometheus 指标 |

## 7. Docker Compose 服务

```text
postgres      pgvector/pgvector:pg16
api           margin-api (Dockerfile)
web           margin-web (web/Dockerfile)
worker        margin-api --worker（复用 api 镜像）
prometheus    prometheus:latest
grafana       grafana/grafana:latest
```

依赖：`web` → `api` → `postgres`；`worker` → `postgres`；`prometheus` → `api`。

## 8. 安全与降级

- API Key 通过环境变量或 Secret 文件注入，不提交到镜像；
- 容器以非 root 运行；
- 文件上传限制类型与大小；
- 降级策略覆盖：数据源失败、解析失败、向量库失败、LLM 失败、策略失败、核心数据冲突；
- 审计记录不可变，数据库表启用 append-only 约束（无 UPDATE/DELETE 入口）。

## 9. 测试策略

- `tests/core/test_settings.py`：环境变量解析、缺省值、敏感字段；
- `tests/core/test_audit_repository.py`：内存与 SQLAlchemy 审计仓库；
- `tests/core/test_degradation.py`：成功、异常 fallback、fallback 失败；
- `tests/api/test_health.py`：健康/就绪/降级端点；
- `tests/api/test_metrics.py`：指标格式与 HTTP 计数；
- CI 中通过 `docker compose -f docker-compose.yml -f docker-compose.test.yml up --abort-on-container-exit` 跑集成测试。

## 10. 验收标准

- [x] `docker compose up` 可启动全栈；
- [x] `src/margin/settings.py` 集中读取所有 `MARGIN_*` 变量；
- [x] PostgreSQL `audit_records` 表可追加不可变审计记录；
- [x] `/metrics` 暴露 HTTP 与 Provider 指标；
- [x] `/health/ready` 在数据库不可达时返回 503；
- [x] `/health/degraded` 在任一 Provider 不健康时返回降级；
- [x] `DegradationWrapper` 在异常时返回 `from_fallback=True`；
- [x] 结构化日志输出 JSON 且包含 `trace_id`；
- [x] GitHub Actions CI 中 ruff / pytest / Docker build 通过；
- [x] 后端 `ruff check src tests` 通过；
- [x] 后端 `pytest` 全绿。

## 11. 后续扩展

- 接入 Sentry / OpenTelemetry 分布式追踪；
- 对象存储（S3/MinIO）快照；
- DuckDB/Parquet 分析层；
- Kubernetes Helm chart；
- 多环境 secret 管理（Vault / sealed-secrets）。
