# 10-deployment_audit 模块文档

本文档覆盖 Margin 当前实现 部署与审计模块（deployment & audit）全部公共接口与核心实现，文件位于 `src/margin/core/`、`src/margin/api/`、`scripts/` 以及项目根目录部署配置。

---

## 目录

1. [模块概述与职责](#1-模块概述与职责)
2. [文件级摘要](#2-文件级摘要)
3. [审计（Audit）](#3-审计audit)
4. [快照存储（Snapshot Store）](#4-快照存储snapshot-store)
5. [故障降级（Degradation）](#5-故障降级degradation)
6. [结构化日志（Logging）](#6-结构化日志logging)
7. [指标（Metrics）](#7-指标metrics)
8. [中间件（Middleware）](#8-中间件middleware)
9. [健康检查端点](#9-健康检查端点)
10. [部署产物](#10-部署产物)
11. [跨模块使用说明](#11-跨模块使用说明)

---

## 1. 模块概述与职责

`10-deployment_audit` 是 Margin 系统的基础设施与横切能力层，负责：

- **一键本地部署**：通过 `docker-compose.yml` 编排 PostgreSQL + pgvector、后端 API、Next.js 前端、后台 Worker、Prometheus、Grafana、一次性 migrate/bootstrap 服务。
- **不可变审计**：记录每一次 Provider 调用、关键业务对象变更，以及研究信号的输入/输出哈希，保证审计日志 append-only、不可修改。
- **本地快照存储**：以内容寻址（SHA-256）方式保存研究信号、文档、报告等对象的不可变 JSON 快照，支持按对象类型/ID 查询历史版本。
- **故障降级**：当主 Provider 调用失败时，自动切换到 fallback，并标记结果为降级，避免虚假高置信输出。
- **可观测性**：结构化 JSON/Console 日志、`trace_id` 全链路传播、HTTP 与 Provider 指标采集、`/metrics` Prometheus 暴露端点。
- **健康探针**：提供 Kubernetes 风格的 `/health`（存活）、`/health/ready`（就绪，检测数据库）、`/health/degraded`（聚合降级状态）端点。

该模块的产品与架构边界见对应大版本的 `docs/design/`，本文只描述当前已实现状态。

---

## 2. 文件级摘要

| 文件路径 | 作用 |
|---|---|
| `src/margin/core/audit.py` | Provider 调用审计：不可变 `AuditRecord`、SHA-256 哈希、JSON Lines 本地日志写入与读取。 |
| `src/margin/core/audit_repository.py` | 业务审计记录持久化契约 `AuditRepository`，含内存实现与 SQLAlchemy/PostgreSQL 实现。 |
| `src/margin/core/run_states.py` | v0.2 durable orchestration 的 Run/Step 状态、append-only attempt/event 模型、输入哈希与状态转换语义。 |
| `src/margin/core/db_orchestration.py` | v0.2 orchestration、capacity、transactional outbox、idempotency、smoke audit 的 SQLAlchemy ORM 表。 |
| `src/margin/core/orchestration_repository.py` | 内存/PostgreSQL orchestration repository，支持 latest-step 查询、lease claim、retry append 与 `FOR UPDATE SKIP LOCKED`。 |
| `src/margin/core/orchestration.py` | `DBStepWorker` 与 `StepClaim`，负责从数据库安全领取可执行 step。 |
| `src/margin/core/capacity.py` | 版本化容量治理：provider RPM、LLM token/cost、并发窗口与 typed waiting 结果。 |
| `src/margin/core/outbox.py` | Transactional Outbox：同事务 enqueue、幂等去重、lease claim、ack/retry/deliver。 |
| `src/margin/core/db_audit.py` | 审计记录的 SQLAlchemy ORM 模型 `AuditLogRecordRow` 与索引定义。 |
| `src/margin/core/models.py` | 共享领域模型，包括业务审计记录 `AuditLogRecord`。 |
| `src/margin/core/snapshot_store.py` | 本地 append-only 快照存储 `FileSnapshotStore` 与 `SnapshotEntry`。 |
| `src/margin/core/degradation.py` | Provider 故障降级包装器 `call_with_fallback`。 |
| `src/margin/core/logging_config.py` | 基于 structlog 的结构化日志配置 `configure_logging`。 |
| `src/margin/core/metrics.py` | Prometheus 指标注册表 `REGISTRY` 与 HTTP/Provider 计数器/直方图。 |
| `src/margin/api/metrics.py` | FastAPI `/metrics` 端点，暴露 Prometheus 文本格式指标。 |
| `src/margin/api/middleware.py` | `TraceIdMiddleware`（trace_id 传播）与 `MetricsMiddleware`（HTTP 指标采集）。 |
| `src/margin/api/routes/health.py` | `/health`、`/health/ready`、`/health/degraded` 端点实现。 |
| `Dockerfile` | 后端 API 容器镜像构建定义。 |
| `web/Dockerfile` | Next.js 前端容器镜像构建定义。 |
| `docker-compose.yml` | 本地全栈服务编排。 |
| `.github/workflows/ci.yml` | GitHub Actions 持续集成工作流。 |
| `docker/prometheus.yml` | Prometheus 抓取配置。 |
| `docker/grafana/dashboards/margin-v02.json` | v0.2 orchestration/capacity/outbox/provider/data/LLM/Grafana dashboard。 |
| `docker/grafana/provisioning/dashboards/margin.yml` | Grafana dashboard provisioning 配置。 |
| `scripts/migrate.py` | 容器内执行 Alembic 迁移的一次性脚本。 |
| `scripts/verify_migrations.py` | 从 clean database 验证 Alembic 全链路升级、head、表、索引和 pgvector 扩展。 |
| `scripts/worker_health_check.py` | Worker 容器健康检查，验证数据库 migration head 后再允许 worker 进入 healthy。 |
| `scripts/smoke_full_v02.py` | v0.2 全链路 smoke harness，支持真实 Provider 强制模式、结构化 blocker 和脱敏输出。 |
| `scripts/bootstrap_config.py` | 一次性版本化配置 bootstrap：写入默认 Provider/Scope/策略配置，并把环境变量密钥导入 Secret Store。 |
| `scripts/dev.py` | 本地开发 supervisor：清理旧 API/worker/web 进程，以 `127.0.0.1` 启动单实例服务，写入 `.margin/dev` PID/log，并用 `lsof` 做监听就绪检查。 |
| `scripts/health_check.py` | 容器就绪探针脚本。 |
| `scripts/snapshot_store.py` | 快照存储 CLI 工具。 |

---

## 2.1 v0.2 生产级 orchestration / deployment audit 增量

### Run / Step 状态

`src/margin/core/run_states.py` 定义 v0.2 运行状态：

- `pending`
- `running`
- `waiting_rate_limit`
- `waiting_budget`
- `succeeded`
- `succeeded_with_degradation`
- `failed_retryable`
- `failed_final`
- `skipped`
- `cancelled`

`StepAttempt` 是 append-only 事件模型：

| 字段 | 说明 |
|---|---|
| `event_id` | 单条 step 状态事件 ID。 |
| `run_id` / `step_id` | 所属 run 与 step。 |
| `attempt_no` | 真实重试次数；只有重新执行时递增。 |
| `state_seq` | 同一次 attempt 内的状态事件序号。 |
| `previous_event_id` | 前一状态事件，用于审计链。 |
| `input_hash` / `input_ref` | 输入 payload 的 SHA-256 与可选外部引用；不把大 payload 写入日志。 |
| `output_ref` | 输出对象引用，通常指向 snapshot、warehouse row 或报告对象。 |
| `lease_owner` / `lease_expires_at` | worker claim lease，支持崩溃恢复。 |
| `retry_after` | rate limit、budget 或 retryable failure 的下次可执行时间。 |

PostgreSQL 表 `orchestration_step_attempts` 保留所有状态事件，不 destructive update 历史行；latest state 由 repository 查询派生。

### Worker claim / lease / retry

`DBStepWorker` 只从 repository 领取已到期、可执行的 step：

- 可 claim 的状态包括 `pending`、到期的 `failed_retryable`、lease 过期的 `running`；
- PostgreSQL 路径使用 `FOR UPDATE SKIP LOCKED` 避免多 worker 重复领取；
- retry 会追加新的 `attempt_no`，旧 attempt 保留；
- lease 过期后可被其他 worker 重新领取；
- 核心 worker 不执行未知 step handler，具体业务 step 由后续模块注册。

### Capacity Governor

`src/margin/core/capacity.py` 提供版本化容量治理：

| 能力 | 说明 |
|---|---|
| `CapacityLimit` | 定义 `limit_key`、窗口、`max_count`、版本和 outcome。 |
| `CapacityGovernor.try_acquire` | 消费 provider RPM、并发窗口、任务队列等计数型额度。 |
| `CapacityGovernor.try_acquire_budget` | 检查 LLM 日预算、token/cost 预算等金额型额度。 |
| `CapacityOutcome.WAITING_RATE_LIMIT` | 映射到 step 状态 `waiting_rate_limit`。 |
| `CapacityOutcome.WAITING_BUDGET` | 映射到 step 状态 `waiting_budget`。 |

PostgreSQL counter 按 `(limit_key, window_start, version)` 隔离，避免新旧容量版本互相污染。

### Transactional Outbox

`src/margin/core/outbox.py` 实现同事务 outbox：

| 状态 | 说明 |
|---|---|
| `pending` | 业务事务已提交，等待发布。 |
| `claimed` | outbox worker 已领取并持有 lease。 |
| `delivered` | 下游确认成功后才标记完成。 |
| `failed_retryable` | 可重试失败，等待 `retry_after`。 |
| `failed_final` | 达到最大重试或不可恢复失败。 |

`enqueue_once` / `enqueue_once_in_session` 使用 `(topic, idempotency_key)` 去重。`enqueue_once_in_session` 可复用调用方 SQLAlchemy session，使业务状态与 outbox row 在同一事务提交或回滚。

### Secret redaction

当前 redaction 覆盖：

- Provider 调用审计参数；
- `AuditRepository.payload_json` 入库前；
- structlog event dictionary；
- traceback / exception string；
- HTTP header/body/cookie 形态字段；
- smoke harness stage detail 与 stdout summary。

敏感键包含 `token`、`api_key`、`authorization`、`password`、`secret`、`cookie`。已知 secret value 会被替换为 `[REDACTED]` 或 `***REDACTED***`，不允许出现在日志、测试输出、smoke summary、正式文档或 Git 产物。

### v0.2 Metrics / Grafana

`src/margin/core/metrics.py` 新增 bounded-label 指标族：

- run / step duration；
- queue age；
- retry / failure counts；
- provider request total / latency；
- data freshness / schema drift / quality；
- LLM token / cost；
- graph path / reflection / revision；
- checkpoint recovery / outbox lag；
- DB pool / statement timeout。

指标避免以全市场 `symbol` 作为 label，防止 Prometheus 高基数。Grafana dashboard 位于 `docker/grafana/dashboards/margin-v02.json`，通过 `docker/grafana/provisioning/dashboards/margin.yml` 自动加载。

### Health / migration / smoke

| 脚本或端点 | 当前语义 |
|---|---|
| `/health` | 进程存活检查。 |
| `/health/ready` | 检查 database、migration head、outbox、provider config、worker readiness；失败返回 503，不暴露原始 secret 或 DB 连接串。 |
| `/health/degraded` | 聚合 provider degraded、waiting budget/rate-limit、retry queue/outbox pending 等可恢复状态。 |
| `scripts/verify_migrations.py` | 在隔离 clean DB 中执行 Alembic 到 head，验证当前 head、目标表、索引和 pgvector。 |
| `scripts/worker_health_check.py` | Worker 容器启动前验证数据库可连接且 migration head 正确。 |
| `scripts/smoke_full_v02.py` | 运行 Compose/migration/health/DB/provider/downstream 注册 stage；stdout 只打印 stage/status/blocker summary，完整脱敏 detail 可写入 `--output-json`。 |
| `scripts/smoke_dashboard_e2e.py` | 通过 HTTP 验证 Next.js 关键页面、只读数据流和 secret-safe HTML；本地 URL 显式 bypass system proxy。 |
| `scripts/smoke_valuation_discovery_p1.py` | 通过本地 API 触发 valuation-discovery refresh；本地 URL 显式 bypass system proxy，Provider 未 active 时返回结构化 `service_not_configured`。 |

`scripts/smoke_full_v02.py --require-real-providers` 的失败分类：

| blocker | 含义 |
|---|---|
| `missing_secret` | 缺少所需 API key/base URL/model 等配置。 |
| `network` | DNS、proxy、timeout、connection reset 等外部网络问题。 |
| `auth` | 401/403 或明确认证失败。 |
| `rate_limit` | 429 或 provider 限流。 |
| `provider` | Provider 返回业务错误或不健康，但无法归入以上外部类别。 |

非 `--require-real-providers` 模式下 Provider stage 会标记为 `skipped: real_provider_not_required`，不会冒充真实通过。尚未由后续模块注册的 P0/P1/P2 业务 smoke stage 标记为 `skipped: stage_registered_by_downstream_module`。

### Compose 顺序

`docker-compose.yml` 的启动顺序：

1. `postgres` health；
2. `migrate` 一次性升级；
3. `bootstrap` 一次性版本化配置与 Secret Store 导入；
4. `api` readiness；
5. `worker` migration-head healthcheck；
6. `web`；
7. `prometheus`；
8. `grafana`。

API 与 Worker 都不会在 migration 成功前进入 healthy。Compose 验证时应使用 `docker compose config --quiet` 或 `--no-interpolate`，避免展开本地真实 Provider secret。

### 本地开发 supervisor

宿主机本地开发优先使用：

```bash
python scripts/dev.py restart
```

该脚本会：

- 停止当前仓库已有的 API、worker、web dev 进程；
- 保证只保留一个 `margin.worker`；
- 用 `127.0.0.1:8000` 启动 FastAPI，用 `127.0.0.1:3000` 启动 Next.js；
- 为子进程设置 `NO_PROXY/no_proxy=localhost,127.0.0.1,::1`，减少 VPN/proxy 对本地服务的干扰；
- 把 PID 写入 `.margin/dev/pids/`，日志写入 `.margin/dev/logs/`；
- 用 `lsof` 判断端口是否监听，不依赖当前 shell 能否成功 `curl localhost`。

常用命令：

| 命令 | 说明 |
|---|---|
| `python scripts/dev.py restart` | 清理旧进程并启动本地 API/worker/web。 |
| `python scripts/dev.py status` | 查看 8000、3000 和 worker 是否为单实例运行。 |
| `python scripts/dev.py stop` | 停止本地开发进程。 |

## 3. 审计（Audit）

### 3.1 `AuditRecord`

源码文件：`src/margin/core/audit.py`

描述一次 Provider 调用的不可变审计记录，使用 Pydantic `BaseModel` 并设置 `frozen=True`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `provider_name` | `str` | Provider 名称。 |
| `provider_version` | `str` | Provider 版本。 |
| `method` | `str` | 被调用的方法名。 |
| `params_summary` | `dict[str, Any]` | 经脱敏/截断后的调用参数摘要。 |
| `success` | `bool` | 调用是否成功。 |
| `error` | `str \| None` | 错误信息。 |
| `fetched_at` | `datetime` | 数据获取时间。 |
| `available_at` | `datetime \| None` | 数据可用时间。 |
| `response_hash` | `str \| None` | 响应内容哈希（如 `sha256:<hex>`）。 |
| `cost` | `float` | 调用成本，默认 `0.0`。 |
| `latency_ms` | `float \| None` | 调用延迟（毫秒）。 |
| `attempt_count` | `int` | 尝试次数，默认 `1`。 |
| `from_fallback` | `bool` | 是否来自 fallback，默认 `False`。 |
| `trace_id` | `str` | 链路追踪 ID。 |

### 3.2 `compute_hash`

| 项目 | 说明 |
|---|---|
| 签名 | `def compute_hash(data: Any) -> str` |
| 功能 | 对任意可 JSON 序列化的数据计算确定性 SHA-256 哈希。 |
| 参数 | `data`：任意可 JSON 序列化的值；`None` 会被特殊处理。 |
| 返回值 | `sha256:<hex_digest>` 或 `sha256:none`。 |
| 实现要点 | 使用 `json.dumps(data, sort_keys=True, default=str, ensure_ascii=False)` 保证相同输入产生相同哈希。 |

### 3.3 `AuditLogger`

| 项目 | 说明 |
|---|---|
| 签名 | `class AuditLogger` |
| 功能 | append-only 的 Provider 调用审计日志写入器，当前以 JSON Lines 写入本地文件。 |
| 初始化 | `def __init__(self, log_path: Path \| None = None) -> None` |
| 默认路径 | `.margin/audit/provider_calls.jsonl` |

| 方法 | 签名 | 说明 |
|---|---|---|
| `log_call` | `def log_call(self, provider_name: str, provider_version: str, method: str, params: dict[str, Any], result: CallResult, trace_id: str = "") -> AuditRecord` | 记录一次 Provider 调用，先对 `params` 脱敏摘要，构造 `AuditRecord` 并追加到日志文件。 |
| `_append` | `def _append(self, record: AuditRecord) -> None` | 将单条记录序列化为 JSON 并追加写入日志文件。 |
| `read_all` | `def read_all(self) -> list[AuditRecord]` | 读取日志文件中全部记录；文件不存在时返回空列表。 |

### 3.4 `_summarize_params`

| 项目 | 说明 |
|---|---|
| 签名 | `def _summarize_params(params: dict[str, Any]) -> dict[str, Any]` |
| 功能 | 对调用参数进行审计安全摘要。 |
| 脱敏规则 | `token`、`api_key`、`password`、`secret` 等敏感键替换为 `***REDACTED***`。 |
| 截断规则 | 长度超过 10 的列表/元组替换为 `类型名[len=长度]`；长度超过 200 的字符串截断并追加 `...`。 |
| 返回值 | 适合持久化审计日志的净化参数字典。 |

### 3.5 `AuditRepository`（Protocol）

源码文件：`src/margin/core/audit_repository.py`

业务审计记录的持久化契约，支持按 `record_type`、`object_id`、`trace_id` 过滤。

| 方法 | 签名 | 说明 |
|---|---|---|
| `record` | `def record(self, record: AuditLogRecord) -> None` | 追加一条审计记录。 |
| `list_records` | `def list_records(self, record_type: str \| None = None, object_id: str \| None = None, trace_id: str \| None = None, limit: int = 100) -> list[AuditLogRecord]` | 按条件查询审计记录，默认按 `recorded_at` 降序、最多 100 条。 |

### 3.6 `MemoryAuditRepository`

| 项目 | 说明 |
|---|---|
| 签名 | `class MemoryAuditRepository` |
| 用途 | 测试用内存实现。 |
| 实现要点 | 以 `dict[str, AuditLogRecord]` 存储；若 `record_id` 已存在则抛出 `ValueError`，保证 append-only/不可变语义。 |

| 方法 | 签名 | 说明 |
|---|---|---|
| `record` | `def record(self, record: AuditLogRecord) -> None` | 写入内存，拒绝重复 `record_id`。 |
| `list_records` | `def list_records(self, record_type=None, object_id=None, trace_id=None, limit=100) -> list[AuditLogRecord]` | 按条件过滤并按 `recorded_at` 降序返回前 `limit` 条。 |

### 3.7 `SQLAlchemyAuditRepository`

| 项目 | 说明 |
|---|---|
| 签名 | `class SQLAlchemyAuditRepository` |
| 用途 | PostgreSQL 生产实现。 |
| 初始化 | `def __init__(self, session_factory: Callable[[], Session]) -> None` |

| 方法 | 签名 | 说明 |
|---|---|---|
| `record` | `def record(self, record: AuditLogRecord) -> None` | 通过 `session.begin()` 开启事务，将记录映射为 `AuditLogRecordRow` 后插入；成功自动提交，异常自动回滚。 |
| `list_records` | `def list_records(self, record_type=None, object_id=None, trace_id=None, limit=100) -> list[AuditLogRecord]` | 构建 `select(AuditLogRecordRow)` 并按 `recorded_at.desc()` 排序，附加可选过滤条件后返回。 |

### 3.8 `AuditLogRecord`（领域模型）

源码文件：`src/margin/core/models.py`

| 字段 | 类型 | 说明 |
|---|---|---|
| `record_id` | `str` | 唯一标识，默认 `ar_<uuid前12位>`。 |
| `record_type` | `str` | 记录类型（如 `research_signal`、`portfolio_change`）。 |
| `object_id` | `str \| None` | 关联业务对象 ID。 |
| `trace_id` | `str` | 链路追踪 ID。 |
| `input_hash` | `str \| None` | 输入内容哈希。 |
| `output_hash` | `str \| None` | 输出内容哈希。 |
| `payload_json` | `dict[str, Any] \| None` | 附加 JSON 载荷。 |
| `recorded_at` | `datetime` | 记录时间，默认 UTC 当前时间。 |
| `service_version` | `str` | 服务版本，默认 `0.1.0`。 |

| 校验器 | 签名 | 说明 |
|---|---|---|
| `normalize_recorded_at` | `@field_validator("recorded_at") @classmethod def normalize_recorded_at(cls, value: datetime) -> datetime` | 将时间戳强制转换为 UTC，保证审计排序确定性。 |

### 3.9 `AuditLogRecordRow`（ORM 模型）

源码文件：`src/margin/core/db_audit.py`

| 项目 | 说明 |
|---|---|
| 表名 | `audit_records` |
| 基类 | `margin.storage.base.Base` |

| 字段 | 类型 | 说明 |
|---|---|---|
| `record_id` | `String(64)` | 主键。 |
| `record_type` | `String(48)` | 非空。 |
| `object_id` | `String(96)` | 可为空。 |
| `trace_id` | `String(64)` | 非空，默认空字符串。 |
| `input_hash` | `String(96)` | 可为空。 |
| `output_hash` | `String(96)` | 可为空。 |
| `payload_json` | `JSONB` | 可为空。 |
| `recorded_at` | `DateTime(timezone=True)` | 非空。 |
| `service_version` | `String(32)` | 非空，默认 `0.1.0`。 |

| 索引名 | 字段 | 用途 |
|---|---|---|
| `ix_audit_records_record_type` | `record_type` | 按类型查询。 |
| `ix_audit_records_object_id` | `object_id` | 按对象 ID 查询。 |
| `ix_audit_records_trace_id` | `trace_id` | 按 trace_id 查询。 |
| `ix_audit_records_recorded_at` | `recorded_at` | 按时间排序。 |

---

## 4. 快照存储（Snapshot Store）

### 4.1 `SnapshotEntry`

源码文件：`src/margin/core/snapshot_store.py`

指向一个已持久化快照的不可变数据类（`frozen=True`）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `snapshot_id` | `str` | 快照唯一标识。 |
| `object_type` | `str` | 对象类型（如 `research_signal`、`report`）。 |
| `object_id` | `str` | 对象 ID。 |
| `snapshot_path` | `Path` | 相对于快照根目录的文件路径。 |
| `sha256` | `str` | 内容 SHA-256 哈希。 |
| `created_at` | `datetime` | 创建时间。 |
| `metadata` | `dict[str, Any]` | 附加元数据。 |
| `payload` | `Any` | 载荷内容；写入时持有原始对象，读取时从 JSON 反序列化。 |

### 4.2 `FileSnapshotStore`

| 项目 | 说明 |
|---|---|
| 签名 | `class FileSnapshotStore` |
| 功能 | 基于本地文件系统的 append-only 快照存储，内容寻址，支持按对象类型/ID 列历史版本。 |
| 初始化 | `def __init__(self, base_path: str \| Path) -> None` |
| 存储结构 | `<base_path>/<object_type>/<object_id>/<snapshot_id>.json`；同目录下维护 `index.jsonl` 索引。 |

| 方法 | 签名 | 说明 |
|---|---|---|
| `write` | `def write(self, object_type: str, object_id: str, payload: Any, metadata: dict[str, Any] \| None = None) -> SnapshotEntry` | 序列化载荷（排序键、默认 `str`），计算 SHA-256，写入 JSON 文件，并在 `index.jsonl` 追加索引记录；返回 `SnapshotEntry`。 |
| `read` | `def read(self, snapshot_id: str) -> SnapshotEntry` | 递归查找 `<snapshot_id>.json`；读取时重新计算哈希校验完整性；返回包含反序列化载荷的 `SnapshotEntry`。 |
| `list_snapshots` | `def list_snapshots(self, object_type: str, object_id: str) -> list[SnapshotEntry]` | 列出指定对象类型与 ID 下的全部快照（按文件名排序）。 |

---

## 5. 故障降级（Degradation）

### 5.1 `CallResult`

`CallResult` 定义于 `src/margin/core/provider.py`，是 Provider 调用的统一结果模型。

| 字段 | 类型 | 说明 |
|---|---|---|
| `provider_name` | `str` | Provider 名称。 |
| `provider_version` | `str` | Provider 版本。 |
| `success` | `bool` | 是否成功。 |
| `data` | `Any` | 返回数据。 |
| `error` | `str \| None` | 错误信息。 |
| `fetched_at` | `datetime` | 获取时间。 |
| `available_at` | `datetime \| None` | 数据可用时间。 |
| `response_hash` | `str \| None` | 响应哈希。 |
| `cost` | `float` | 成本。 |
| `latency_ms` | `float \| None` | 延迟。 |
| `attempt_count` | `int` | 尝试次数。 |
| `from_fallback` | `bool` | 是否来自 fallback；降级包装器会将其置为 `True`。 |

### 5.2 `call_with_fallback`

源码文件：`src/margin/core/degradation.py`

| 项目 | 说明 |
|---|---|
| 签名 | `def call_with_fallback(fn: Callable[..., CallResult], fallback: Callable[..., CallResult] \| None, *, trace_id: str, metrics_label: str, **kwargs: Any) -> CallResult` |
| 功能 | 先调用主函数；失败时调用 fallback，并将结果标记为降级；同时更新 Prometheus 指标。 |
| 参数 | `fn`：主函数；`fallback`：可选 fallback 函数；`trace_id`：链路 ID；`metrics_label`：指标标签；`**kwargs`：传给主/备函数的参数。 |
| 返回值 | `CallResult`；若使用 fallback，则 `from_fallback=True`。 |

| 执行路径 | 指标行为 | 返回值 |
|---|---|---|
| 主调用成功 | `PROVIDER_CALLS`（primary, success）+1 | 主结果 |
| 主调用失败、无 fallback | `PROVIDER_CALLS`（primary, error）+1、`PROVIDER_DEGRADED`（primary）+1 | 合成失败 `CallResult` |
| 主调用失败、fallback 成功 | primary error +1、fallback success +1、`PROVIDER_DEGRADED`（fallback）+1 | fallback 结果，`from_fallback=True` |
| 主调用失败、fallback 也失败 | primary error +1、fallback error +1、`PROVIDER_DEGRADED`（fallback）+1 | 合成失败 `CallResult`，错误信息合并 |

---

## 6. 结构化日志（Logging）

### 6.1 `configure_logging`

源码文件：`src/margin/core/logging_config.py`

| 项目 | 说明 |
|---|---|
| 签名 | `def configure_logging(*, log_level: str = "INFO", log_format: str = "json") -> None` |
| 功能 | 配置 stdlib `logging` 与 structlog 使用同一套处理器，输出 JSON（生产）或彩色控制台（开发）。 |
| 参数 | `log_level`：日志级别；`log_format`：`"json"` 或 `"console"`。 |

### 6.2 共享处理器（Shared Processors）

| 处理器 | 说明 |
|---|---|
| `structlog.contextvars.merge_contextvars` | 合并上下文变量（如 trace_id）。 |
| `structlog.processors.add_log_level` | 添加日志级别字段。 |
| `structlog.processors.TimeStamper(fmt="iso")` | 添加 ISO 格式时间戳。 |
| `structlog.stdlib.ExtraAdder()` | 将 stdlib `extra` 字典合并到事件。 |

### 6.3 格式化器差异

| `log_format` | 处理器 | 输出格式 |
|---|---|---|
| `json` | `dict_tracebacks` + `JSONRenderer()` | 单行 JSON。 |
| `console` | `ConsoleRenderer()` | 彩色可读的终端格式。 |

### 6.4 structlog 配置

- `wrapper_class`：过滤型 bound logger，级别与 stdlib 一致。
- `logger_factory`：`structlog.stdlib.LoggerFactory()`，使 structlog 复用 stdlib logger。
- `cache_logger_on_first_use=True`：缓存首次使用的 logger。
- 配置前会清空 root logger 的已有 handler，避免重复输出。

---

## 7. 指标（Metrics）

### 7.1 `REGISTRY` 与指标定义

源码文件：`src/margin/core/metrics.py`

| 名称 | 类型 | 标签 | 说明 |
|---|---|---|---|
| `REGISTRY` | `CollectorRegistry` | - | 专用注册表，隔离 Margin 指标与全局默认注册表，避免第三方库冲突。 |
| `HTTP_REQUESTS` | `Counter` | `method`, `path`, `status_code` | HTTP 请求总数。 |
| `HTTP_REQUEST_DURATION` | `Histogram` | `method`, `path` | HTTP 请求耗时（秒）。 |
| `PROVIDER_CALLS` | `Counter` | `provider`, `method`, `status` | Provider 调用总数（含 primary/fallback 与 success/error）。 |
| `PROVIDER_DEGRADED` | `Counter` | `provider`, `method` | Provider 降级调用总数。 |

### 7.2 `/metrics` 端点

源码文件：`src/margin/api/metrics.py`

| 项目 | 说明 |
|---|---|
| 路由 | `GET /metrics` |
| 函数 | `def metrics() -> Response` |
| 功能 | 调用 `generate_latest(REGISTRY)` 生成 Prometheus 文本格式指标。 |
| 响应类型 | `CONTENT_TYPE_LATEST`（`text/plain; version=0.0.4`）。 |

### 7.3 `MetricsMiddleware`

源码文件：`src/margin/api/middleware.py`

| 项目 | 说明 |
|---|---|
| 签名 | `class MetricsMiddleware(BaseHTTPMiddleware)` |
| 功能 | 记录每个 HTTP 请求的耗时与计数。 |
| 路径处理 | 优先使用 FastAPI 路由模板（`request.scope["route"].path`），避免原始 URL 高基数标签；无路由时回退到 `request.url.path`。 |
| 异常处理 | 若下游抛出未处理异常，默认状态码为 `500`。 |

---

## 8. 中间件（Middleware）

### 8.1 `TraceIdMiddleware`

源码文件：`src/margin/api/middleware.py`

| 项目 | 说明 |
|---|---|
| 签名 | `class TraceIdMiddleware(BaseHTTPMiddleware)` |
| 功能 | 为每个请求生成或复用 trace_id，并写入响应头，供日志与下游服务关联。 |
| trace_id 来源 | 优先读取请求头 `settings.trace_id_header`（默认 `x-margin-trace-id`）；不存在则生成 `t-<uuid前12位>`。 |
| 存储位置 | `request.scope["margin_trace_id"]`。 |
| 响应头 | 将 trace_id 通过 `settings.trace_id_header` 返回给客户端。 |

### 8.2 辅助函数 `_get_trace_id`

| 项目 | 说明 |
|---|---|
| 签名 | `def _get_trace_id(request: Request) -> str` |
| 功能 | 从 `request.scope` 读取由 `TraceIdMiddleware` 注入的 trace_id。 |

---

## 9. 健康检查端点

源码文件：`src/margin/api/routes/health.py`

### 9.1 `GET /health`

| 项目 | 说明 |
|---|---|
| 函数 | `def health() -> dict[str, str]` |
| 功能 | 轻量级存活探针。 |
| 响应 | `{"status": "ok"}`，HTTP 200。 |

### 9.2 `GET /health/ready`

| 项目 | 说明 |
|---|---|
| 函数 | `def ready() -> JSONResponse` |
| 功能 | 就绪探针，验证数据库可连接。 |
| 数据库检查 | 创建临时引擎，执行 `SELECT 1`，无论成功或失败都调用 `engine.dispose()` 释放连接池。 |
| 就绪响应 | `{"status": "ready"}`，HTTP 200。 |
| 未就绪响应 | `{"status": "not_ready"}`，HTTP 503。 |

### 9.3 `GET /health/degraded`

| 项目 | 说明 |
|---|---|
| 函数 | `def degraded() -> dict[str, object]` |
| 功能 | 聚合降级状态；当前主要检测数据库是否不可达。 |
| 响应字段 | `degraded`（是否存在降级）、`degraded_count`（降级数量）、`providers`（降级详情列表）、`service`、`version`。 |
| 返回值示例 | 若数据库不可达，`providers` 包含 `HealthCheckResult(provider_name="database", status=ProviderStatus.UNHEALTHY, ...)`。 |

---

## 10. 部署产物

### 10.1 后端 Dockerfile

文件路径：`Dockerfile`

| 阶段/指令 | 说明 |
|---|---|
| `FROM python:3.12-slim` | 基础镜像。 |
| `ENV PYTHONDONTWRITEBYTECODE=1` | 禁止生成 `.pyc`。 |
| `ENV PYTHONUNBUFFERED=1` | 标准输出无缓冲，适合容器环境。 |
| `ENV PIP_NO_CACHE_DIR=1` | pip 不缓存，减小镜像体积。 |
| `ENV PIP_DEFAULT_TIMEOUT=300` | 拉取数据依赖时提高 pip 默认超时，降低慢网络下的构建误失败。 |
| `ENV PIP_RETRIES=10` | 拉取数据依赖时增加 pip 重试次数。 |
| `WORKDIR /app` | 工作目录。 |
| `COPY pyproject.toml README.md ./` | 先复制依赖元数据。 |
| `COPY src/margin/__init__.py ./src/margin/__init__.py` | 使 `pip install -e ".[data]"` 可识别包。 |
| `RUN pip install -e ".[data]"` | 安装依赖与本地包。 |
| `COPY src ./src` | 复制全部源码。 |
| `COPY scripts ./scripts` | 复制脚本。 |
| `COPY alembic ./alembic` | 复制迁移目录。 |
| `COPY alembic.ini ./` | 复制 Alembic 配置。 |
| `RUN useradd --create-home --uid 10001 margin` | 创建非 root 用户。 |
| `RUN mkdir -p .margin/audit .margin/snapshots` | 在 `WORKDIR /app` 下预创建项目相对的审计日志与快照持久化目录。 |
| `RUN chown -R margin:margin /app` | 目录归属非 root 用户。 |
| `USER margin` | 切换到非 root 用户运行。 |
| `EXPOSE 8000` | 暴露 API 端口。 |
| `CMD ["uvicorn", "margin.api.main:app", "--host", "0.0.0.0", "--port", "8000"]` | 默认启动命令。 |

### 10.2 前端 Dockerfile

文件路径：`web/Dockerfile`

| 阶段/指令 | 说明 |
|---|---|
| `FROM node:20-slim` | 基础镜像。 |
| `WORKDIR /app` | 工作目录。 |
| `COPY package.json package-lock.json* ./` | 先复制依赖文件。 |
| `RUN npm ci` | 安装依赖。 |
| `COPY ./ ./` | 复制全部前端源码。 |
| `RUN npm run build` | 构建 Next.js 生产包。 |
| `RUN npm prune --omit=dev` | 移除开发依赖。 |
| `RUN chown -R node:node /app` | 目录归属 `node` 用户。 |
| `ENV NODE_ENV=production` | 生产模式。 |
| `USER node` | 非 root 运行。 |
| `EXPOSE 3000` | 暴露前端端口。 |
| `CMD ["npm", "start"]` | 启动 Next.js 生产服务。 |

### 10.3 docker-compose 服务

文件路径：`docker-compose.yml`

| 服务 | 镜像/构建 | 端口 | 依赖 | 说明 |
|---|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | `5432:5432` | 无 | 主数据库，带 pgvector 扩展；通过 `pg_isready` 做健康检查。 |
| `migrate` | 后端 Dockerfile | - | postgres healthy | 一次性 Alembic 迁移服务。 |
| `bootstrap` | 后端 Dockerfile | - | migrate completed | 一次性版本化配置 bootstrap；导入默认 Provider/Scope/策略配置与环境变量密钥。 |
| `api` | 后端 Dockerfile | `8000:8000` | bootstrap completed | 主 API 服务；挂载审计与快照卷；使用 `scripts/health_check.py` 做健康检查。 |
| `worker` | 后端 Dockerfile | - | bootstrap completed | 后台任务 Worker。 |
| `web` | 前端 Dockerfile | `3000:3000` | api healthy | Next.js 前端；`MARGIN_API_BASE_URL=http://api:8000`。 |
| `prometheus` | `prom/prometheus:v3.12.0` | `9090:9090` | api healthy | 抓取 API `/metrics`。 |
| `grafana` | `grafana/grafana:13.0.2` | `${GRAFANA_PORT:-3002}:3000` | prometheus started | 可视化监控；默认管理员密码 `margin`。 |

| 数据卷 | 用途 |
|---|---|
| `margin-postgres` | PostgreSQL 数据持久化。 |
| `margin-audit` | 审计日志文件持久化（挂载到容器工作目录 `/app/.margin/audit`，对应应用相对路径 `.margin/audit`）。 |
| `margin-snapshots` | 快照文件持久化（挂载到容器工作目录 `/app/.margin/snapshots`，对应应用相对路径 `.margin/snapshots`）。 |
| `margin-grafana` | Grafana 配置与数据持久化。 |

### 10.4 CI 工作流

文件路径：`.github/workflows/ci.yml`

| Job | 运行环境 | 步骤 | 说明 |
|---|---|---|---|
| `backend` | `ubuntu-latest` | 检出代码、设置 Python 3.12、安装 `pip install -e ".[dev]"`、运行 `ruff check src tests`、执行 `alembic upgrade head`、运行 `pytest` | 后端代码检查、迁移、测试。 |
| `frontend` | `ubuntu-latest` | 检出代码、设置 Node 20、缓存 npm、安装依赖、运行 `npm run lint`、`npm test`、`npm run build` | 前端检查、测试、构建。 |
| `docker` | `ubuntu-latest` | 构建 `margin-api` 镜像、构建 `margin-web` 镜像、运行 `docker compose config --quiet` | 验证镜像构建与 Compose 配置语法。 |

### 10.5 Prometheus 配置

文件路径：`docker/prometheus.yml`

| 配置项 | 说明 |
|---|---|
| `global.scrape_interval` | `15s` |
| `scrape_configs.job_name` | `margin-api` |
| `static_configs.targets` | `["api:8000"]` |
| `metrics_path` | `/metrics` |

### 10.6 辅助脚本

| 脚本 | 路径 | 功能 |
|---|---|---|
| `migrate.py` | `scripts/migrate.py` | 容器内执行 `alembic upgrade head`，作为 `migrate` 服务入口。 |
| `bootstrap_config.py` | `scripts/bootstrap_config.py` | 初始化默认 Provider/Scope/策略配置，将 env 中的 Provider 密钥写入 Secret Store；幂等跳过已存在版本。 |
| `health_check.py` | `scripts/health_check.py` | 访问 `http://localhost:8000/health/ready`，HTTP 200 退出码 0，否则退出码 1。 |
| `worker_health_check.py` | `scripts/worker_health_check.py` | Worker 容器健康探针，验证数据库可连通且 Alembic head 正确。 |
| `verify_migrations.py` | `scripts/verify_migrations.py` | 从隔离 clean DB 验证 Alembic 全链路升级、pgvector、表与索引。 |
| `smoke_full_v02.py` | `scripts/smoke_full_v02.py` | v0.2 smoke harness；支持 `--require-real-providers`、`--skip-compose`、`--base-url`、`--web-url`、`--database-url`、`--output-json`。 |
| `smoke_dashboard_e2e.py` | `scripts/smoke_dashboard_e2e.py` | 验证 Web 关键页面、Provider 设置、research dashboard 与 secret-safe 输出；本地 URL 不走系统代理。 |
| `smoke_valuation_discovery_p1.py` | `scripts/smoke_valuation_discovery_p1.py` | 验证本地 API refresh trigger、admin/csrf/idempotency 与结构化 external blocker；本地 URL 不走系统代理。 |
| `snapshot_store.py` | `scripts/snapshot_store.py` | 快照 CLI，支持 `write`、`read`、`list` 子命令，操作与核心库兼容的 `FileSnapshotStore`。 |

---

## 11. 跨模块使用说明

### 11.1 应用启动流程

`src/margin/api/main.py` 中的 `create_app()` 按以下顺序装配可观测性能力：

1. 调用 `configure_logging(log_level=settings.log_level, log_format=settings.log_format)` 初始化结构化日志。
2. 注册 `TraceIdMiddleware`（最先执行，保证后续中间件和路由能读取 trace_id）。
3. 注册 `MetricsMiddleware`（记录 HTTP 请求指标）。
4. 挂载 `metrics_router`（`/metrics`）与 `health_router`（`/health*`）。

### 11.2 Provider 调用链路

业务模块通过 `margin.core.registry`（本模块未直接列出，但依赖本模块能力）调用 Provider 时：

- 调用结果封装为 `CallResult`。
- `call_with_fallback` 在主调用失败时触发 fallback，并更新 `PROVIDER_CALLS` / `PROVIDER_DEGRADED`。
- `AuditLogger.log_call()` 将调用记录为不可变 `AuditRecord`，写入 `.margin/audit/provider_calls.jsonl`。
- `trace_id` 由 `TraceIdMiddleware` 注入并贯穿整个请求链路。

### 11.3 业务审计记录链路

- 领域模型 `AuditLogRecord`（`margin.core.models`）携带 `record_id`、`record_type`、`object_id`、`input_hash`、`output_hash`、`payload_json` 等字段。
- `AuditRepository` 协议定义持久化契约；生产环境使用 `SQLAlchemyAuditRepository`，测试使用 `MemoryAuditRepository`。
- ORM 模型 `AuditLogRecordRow`（`margin.core.db_audit`）映射到 PostgreSQL 表 `audit_records`，并建立 `record_type`、`object_id`、`trace_id`、`recorded_at` 索引以支持取证查询。

### 11.4 快照与研究信号

- 研究模块生成信号/报告后，可调用 `FileSnapshotStore.write(...)` 将对象以 JSON 形式快照落地。
- 快照路径为 `<base>/<object_type>/<object_id>/<snapshot_id>.json`，并附加 `index.jsonl` 记录历史。
- 通过 `compute_hash` 计算的输入/输出哈希可存入 `AuditLogRecord.input_hash` / `output_hash`，实现研究信号的不可变追溯。

### 11.5 配置项

`src/margin/settings.py` 中与本模块相关的环境变量：

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `MARGIN_LOG_LEVEL` | `INFO` | 日志级别。 |
| `MARGIN_LOG_FORMAT` | `json` | 日志格式：`json` 或 `console`。 |
| `MARGIN_METRICS_ENABLED` | `true` | 是否启用指标。 |
| `MARGIN_TRACE_ID_HEADER` | `x-margin-trace-id` | trace_id 请求/响应头名称。 |
| `MARGIN_AUDIT_LOG_PATH` | `.margin/audit/provider_calls.jsonl` | Provider 调用审计日志路径。 |
| `MARGIN_ENVIRONMENT` | `development` | 运行环境。 |
| `MARGIN_SERVICE_NAME` | `margin-api` | 服务名。 |
| `MARGIN_SERVICE_VERSION` | `0.1.0` | 服务版本。 |

### 11.6 安全要点

- 容器以非 root 用户运行（后端 `margin` uid 10001，前端 `node`）。
- `AuditLogger` 对 `token`、`api_key`、`password`、`secret` 等敏感键自动脱敏。
- 审计记录与快照模型均为不可变（`frozen=True`），防止事后篡改。
- Provider 失败时遵循“宁可 ABSTAINED，也不输出虚假高置信结论”的原则，通过 `call_with_fallback` 明确标记降级结果。
