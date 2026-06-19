---
module_id: 10-deployment_audit
product_version: v0.1
doc_version: v0.1
source_refs: [产品设计 §13.1, §13.2-10; 架构设计 §5, §21, §22, §23, §24, §25, §26-Phase1]
status: active
---

# 10 部署与审计模块 — 功能规格

## 1. 模块目标

提供一键本地部署（Docker Compose）、存储分层与不可变快照、安全设计、可观测性（指标与 Trace）、测试策略与故障降级。v0.1 运行时采用 PostgreSQL + pgvector、本地不可变文件快照、Worker/Scheduler、日志与审计；Parquet/DuckDB 与外部对象存储保留为后续扩展。MVP 可在 4C8G 主机运行，不依赖 GPU。

## 2. 输入 / 输出

- **输入**：所有业务模块的持久化需求、调度配置、Secret 配置、外部 Provider 健康状态。
- **触发**：部署启动、调度任务、异常事件、审计查询。
- **输出**：运行中的服务集合（migrate/seed/web/api/worker/postgres/prometheus/grafana）、不可变审计日志与快照、指标与 Trace、降级处理结果。
- **消费方**：全部模块（存储、调度、审计、可观测性横切能力）。

## 3. 接口契约

Docker Compose 服务（架构 §21.2）：migrate、seed、web、api、worker、postgres、prometheus、grafana。Redis/Qdrant 不进入 v0.1 默认栈。

部署架构（架构 §21.1）：Next.js（web）→ FastAPI（api）→ PostgreSQL+pgvector；Worker/Scheduler → PostgreSQL / Raw-Parquet / LLM API / 外部数据源。

Trace 字段（架构 §23）：`trace_id`、`job_run_id`、`strategy_version_id`、`research_run_id`、`symbol`、`agent_node`、`model_version`、`provider_version`。

## 4. 数据模型

存储组合（架构 §5.1）：PostgreSQL（主业务数据、策略、持仓、研究信号、证据元数据）、本地不可变文件（原始 PDF/HTML/JSON/CSV 快照）与 pgvector（文本向量）。Parquet/DuckDB、S3、Qdrant、Redis 属于后续可插拔扩展。

数据分层（架构 §5.2）：ODS 原始层 → DWD 标准明细层 → PIT 时点层 → DWS 特征与主题层 → ADS 研究信号与面板层。

不可变研究信号快照（架构 §5.4）：每次研究运行冻结股票池版本、数据快照、策略版本、Prompt 版本、工具版本、模型版本、检索结果、证据 ID、结构化输出、生成时间、输入哈希、输出哈希。

横切能力（架构 §3）：认证与权限、任务调度、审计与追踪、日志与可观测性、配置与 Secret、插件注册中心、数据质量与异常隔离。

## 5. 与其他模块依赖

- **上游**：无（基础设施层，被所有模块依赖）。
- **下游**：01–09 全部模块（存储、调度、审计、可观测性）。
- **规避循环**：本模块不包含业务逻辑，仅提供横切能力与持久化。

## 6. 验收标准

对应产品设计 §15：

- 条目 1：用户可在本地完成一键部署（Docker Compose）；
- 条目 9：所有研究信号保留不可变审计记录（不可变快照）；
- 条目 10：系统默认不执行真实交易（部署层面不内置自动下单能力）。

## 7. 风险与降级

对应架构 §25「故障降级」全量：

- 数据源失败 → 备用源/使用旧数据并降级；
- 文本解析失败 → 保留原文并停止相关 AI 结论；
- 向量库失败 → 关键词检索降级；
- LLM 失败 → 规则型报告；
- 策略错误 → 回滚上一版本；
- 核心数据冲突 → 停止发布高置信研究信号。

原则：宁可 `ABSTAINED`，也不输出虚假的高置信结论（架构 §25）。

## 8. 审计追溯

- `source_refs` 指向产品设计 §13.1 / §13.2-10、架构设计 §5 / §21 / §22 / §23 / §24 / §25 / §26 Phase1-Phase6；
- 审计日志不可修改（架构 §22）；研究信号快照落库不可篡改（架构 §5.4）；
- 安全设计（架构 §22）：API Key 使用 Secret、数据库最小权限、内部工具权限分级、Prompt Injection 防护、用户 Prompt 不能覆盖系统 Guardrail、原始文件类型与大小限制、任意代码执行默认关闭、持仓数据默认不上传、数据源授权与版权责任边界在设置页明确展示。
