# 10-deployment_audit — 部署、审计和可观测性

这个模块负责让系统能跑、能查、能降级、能复盘。

## 它做什么

- 提供 Docker / Compose / migration / bootstrap / smoke 脚本。
- `scripts/docker_dev.py` 支持 zero-env 启动：自动生成 `.margin/docker/runtime.env`、选择空闲端口并显示启动进度。
- 暴露健康检查、Prometheus 指标和结构化日志。
- 保存审计记录、快照、任务状态和降级原因。
- 在 Provider 不可用、配置缺失或任务失败时给出明确状态。
- 保留当前正在使用的运行态表：orchestration、outbox、audit、Agent 会话、配置拉链表、数据同步状态、Dashboard 状态，以及正式的 `platform.*` / `ops.*` 运行表。
- 已通过 `20260709_0058` 清理未接入的 v1 草稿 control-plane 表。
- 已通过 `20260709_0059` 补齐 PIT 数据仓库分层，并把旧表数据非破坏式迁移到新层。
- 已通过 `20260709_0063` 重新引入正式 platform/ops 表：idempotency、runtime environment、config snapshot、outbox、dead-letter、backfill、health、freshness。

## 它怎么跑

```text
部署启动
  -> migration
  -> bootstrap 配置
  -> api / worker / web 启动
  -> health / metrics / audit 持续记录
```

这个模块不产生股票推荐，但它决定系统出问题时能不能定位原因。

## 主要入口

- `Dockerfile`、`web/Dockerfile`、`docker-compose.yml`。
- `scripts/`：Docker 启动、本地开发、迁移、回填、smoke；普通 Docker 用户不需要手动创建 `.env`，`.env` 仅作为高级覆盖。
- `src/margin/core/`：audit、metrics、degradation、run states。
- `src/margin/platform_runtime/`：platform/ops 运行表 ORM 和 repository。
- `src/margin/api/routes/health.py` 和 `/metrics`。
- `alembic/versions/20260708_0053` 到 `20260709_0063`：v1 schema、warehouse、mart、app serving、草稿表清理和正式 platform/ops 表。
- `src/margin/api/routes/backfill.py`、`freshness.py`、`tool_audit.py`：回填、新鲜度和工具审计 safe API。

## 输出给谁

- 开发者用它启动和排错。
- CI / 部署环境用它验证服务状态。
- Agent 和 Dashboard 用它展示 degraded / unhealthy 状态。
