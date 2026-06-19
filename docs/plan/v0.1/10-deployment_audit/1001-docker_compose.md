---
task_id: 1001
parent_module: 10-deployment_audit
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §26-Phase1: PostgreSQL/Parquet 与快照; §21, 产品设计 §13.1]
status: active
estimate_days: 10
depends_on: [0101]
---

# 1001 Docker Compose 与部署架构 — 实施计划

## 1. 任务目标

实现一键本地部署：Docker Compose 服务（migrate/seed/web/api/worker/postgres/prometheus/grafana）。部署架构为 Next.js（web）→ FastAPI（api）→ PostgreSQL+pgvector；Worker/Scheduler → PostgreSQL / 本地快照 / LLM API / 外部数据源。Redis/Qdrant 不进入 v0.1 默认栈。

## 2. 工作项拆解

- 1001.1 docker-compose.yml — 全部服务编排与依赖顺序。
- 1001.2 PostgreSQL + pgvector 初始化 — 数据库、扩展、初始 Schema。
- 1001.3 FastAPI api 与 Next.js web 容器化 — 服务启动与配置注入。
- 1001.4 Worker/Scheduler 容器化 — APScheduler 本地任务、外部连接配置。

## 3. 依赖关系

- 前置：0101（Provider Registry，对应 Gantt a3 after a1）。
- 被依赖：1002（存储分层）、1003（可观测性）、0402（pgvector）。
- 外部依赖：无。

## 4. 工时估算

- 1001.1：3 天
- 1001.2：3 天
- 1001.3：2 天
- 1001.4：2 天
- 合计：10 天（对齐 Gantt a3）。

## 5. 里程碑与交付物

- M1：docker-compose.yml 全服务编排（第 3 天）。
- M2：PostgreSQL + pgvector 初始化（第 6 天）。
- M3：api 与 web 容器化（第 8 天）。
- M4：worker 容器化，一键启动可用（第 10 天）。

## 6. 验收动作

- 用户可在本地完成一键部署（对应产品 §15 条目 1）；
- docker compose up 启动全部服务；
- MVP 在 4C8G 主机运行，不依赖 GPU（对应架构 §1）。

## 7. 审计追溯

- `source_refs`：架构 §26-Phase1 a3、§21、产品 §13.1；
- 关联 spec：`spec/v0.1/10-deployment_audit/spec.md` §3 / §6；
- 不可变产物：docker-compose.yml 版本、初始化 Schema。
