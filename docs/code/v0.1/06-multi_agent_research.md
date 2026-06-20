# 06-multi_agent_research 模块文档

## 目录

1. [模块概览与职责](#1-模块概览与职责)
2. [文件级摘要](#2-文件级摘要)
3. [领域模型](#3-领域模型)
4. [工作流](#4-工作流)
5. [LLM 层](#5-llm-层)
6. [Agent](#6-agent)
7. [工具系统](#7-工具系统)
8. [快照与仓库](#8-快照与仓库)
9. [服务与 API](#9-服务与-api)
10. [跨模块使用说明](#10-跨模块使用说明)

---

## 1. 模块概览与职责

`06-multi_agent_research` 是 Margin v0.1 的**多智能体研究模块**，负责针对单个标的（symbol）执行一套完整的自动化研究流水线，最终生成结构化的研究信号（`ResearchSignal`）及不可变的审计快照（`ResearchSnapshot`）。

### 核心职责

| 职责 | 说明 |
|------|------|
| 多智能体编排 | 按固定状态机顺序调度 12 个研究 Agent 协同工作 |
| 数据与证据采集 | 调用市场数据、财务数据、因子、网络搜索、文档采集、向量检索等工具 |
| 结构化输出 | 通过 JSON Schema 与护栏（guardrail）约束 LLM 输出 |
| 信号合成 | 综合量化、估值、风险、反向论证、组合约束结果，输出 `research_candidate` / `watch` / `abstained` |
| 引用校验 | 校验信号引用的证据是否真实存在于 Claim/Evidence 体系 |
| 审计持久化 | 生成 append-only 快照，支持内存与 PostgreSQL 两种仓库 |
| 对外服务 | 通过 FastAPI 暴露 `/research/run` 与 `/research/tools` 接口 |

### 典型调用链

```
ResearchService.run(symbol)
  └─ ResearchWorkflow.run()
       ├─ UniverseFilterAgent      标的筛选
       ├─ QuantResearchAgent       因子打分
       ├─ WebSearchAgent           生成查询并搜索
       ├─ DocumentCollectorAgent   快照网页/文档
       ├─ TextSummaryAgent         摘要文档
       ├─ EvidenceResearchAgent    向量检索证据
       ├─ ValuationToolAgent       估值计算
       ├─ RiskReviewAgent          风险审查
       ├─ ReflectCounterArgumentAgent 反向论证
       ├─ PortfolioConstraintAgent 组合约束
       ├─ ResearchSignalComposer   合成信号
       └─ CitationValidatorAgent   引用校验
```

---

## 2. 文件级摘要

| 文件路径 | 说明 |
|----------|------|
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/research/__init__.py` | 模块公共导出，聚合各子模块的核心类 |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/research/models.py` | 领域模型：信号、快照、工作流状态、Agent 轨迹 |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/research/workflow.py` | 工作流状态机 `ResearchWorkflow` 与结果 `WorkflowResult` |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/research/llm.py` | LLM 适配器、模型路由、结构化输出护栏 |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/research/agents.py` | Agent 抽象基类与 12 个研究 Agent 实现 |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/research/tools.py` | 工具抽象、权限控制、工具注册表 |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/research/production_tools.py` | 生产环境工具注册表构造，接入 AKShare、Tavily、向量库 |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/research/snapshot.py` | 不可变研究快照构建器 `ResearchSnapshotBuilder` |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/research/repository.py` | 快照仓库协议及内存/PostgreSQL 实现 |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/research/service.py` | 高层服务入口 `ResearchService` |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/api/routes/research.py` | FastAPI 路由：运行研究与列出工具 |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/research/db_models.py` | SQLAlchemy 实体 `ResearchSnapshotRow` |

---

## 3. 领域模型

定义位置：`/Users/wangruiqi/PycharmProjects/Margin/src/margin/research/models.py`

### 3.1 枚举

#### `SignalType`

研究信号分类。

| 成员 | 值 | 含义 |
|------|-----|------|
| `RESEARCH_CANDIDATE` | `research_candidate` | 通过初筛，进入候选池 |
| `WATCH` | `watch` | 需持续观察 |
| `ABSTAINED` | `abstained` | 放弃/不建议 |

#### `WorkflowState`

工作流生命周期状态。

| 成员 | 值 |
|------|-----|
| `INITIALIZED` | `initialized` |
| `DATA_READY` | `data_ready` |
| `EVIDENCE_READY` | `evidence_ready` |
| `ANALYSIS_READY` | `analysis_ready` |
| `REVIEW_READY` | `review_ready` |
| `PUBLISHED` | `published` |
| `ABORTED` | `aborted` |
| `ABSTAINED` | `abstained` |

### 3.2 `AgentTrace`

单次 Agent 调用轨迹。

| 字段 | 类型 | 说明 |
|------|------|------|
| `trace_id` | `str` | 轨迹标识 |
| `agent_node` | `str` | Agent 节点名 |
| `model_version` | `str` | 模型版本 |
| `input_hash` | `str` | 输入哈希 |
| `output_hash` | `str` | 输出哈希 |
| `latency_ms` | `float \| None` | 耗时（毫秒） |
| `error` | `str \| None` | 错误信息 |
| `tool_call_ids` | `tuple[str, ...]` | 关联工具调用 ID |
| `timestamp` | `datetime` | 调用时间（UTC） |

### 3.3 `ResearchSignal`

工作流最终输出的结构化研究信号。

| 字段 | 类型 | 说明 |
|------|------|------|
| `signal_id` | `str` | 信号唯一 ID，默认 `sig_<uuid[:12]>` |
| `symbol` | `str` | 标的代码 |
| `signal_type` | `SignalType` | 信号类型 |
| `confidence` | `float` | 置信度，范围 `[0, 1]` |
| `statement` | `str` | 信号说明语句 |
| `evidence_refs` | `tuple[str, ...]` | 引用的证据 ID |
| `claim_ids` | `tuple[str, ...]` | 关联的 Claim ID |
| `risk_score` | `float \| None` | 风险评分 |
| `counter_arguments` | `tuple[str, ...]` | 反向论证 |
| `portfolio_constraint_violations` | `tuple[str, ...]` | 组合约束违规说明 |
| `generated_at` | `datetime` | 生成时间（UTC） |

### 3.4 `VersionRef`

组件版本引用，记录于快照中。

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | 组件名 |
| `version` | `str` | 版本号 |

### 3.5 `ResearchSnapshot`

一次研究运行的不可变审计快照。

| 字段 | 类型 | 说明 |
|------|------|------|
| `snapshot_id` | `str` | 快照 ID，默认 `snap_<uuid[:12]>` |
| `run_id` | `str` | 运行 ID |
| `workflow_state` | `WorkflowState` | 终态 |
| `decision_at` | `datetime` | 决策时间 |
| `symbols` | `tuple[str, ...]` | 研究标的 |
| `strategy_version` | `str` | 策略版本 |
| `prompt_version` | `str` | Prompt 版本 |
| `tool_versions` | `tuple[VersionRef, ...]` | 工具版本列表 |
| `model_versions` | `tuple[VersionRef, ...]` | 模型版本列表 |
| `evidence_ids` | `tuple[str, ...]` | 证据 ID |
| `claim_ids` | `tuple[str, ...]` | Claim ID |
| `signals` | `tuple[ResearchSignal, ...]` | 输出信号 |
| `input_hash` | `str` | 输入载荷哈希 |
| `output_hash` | `str` | 输出载荷哈希 |
| `traces` | `tuple[AgentTrace, ...]` | Agent 调用轨迹 |
| `tool_call_ids` | `tuple[str, ...]` | 工具调用 ID |
| `agent_outputs_json` | `str` | Agent 输出 JSON |
| `tool_calls_json` | `str` | 工具调用 JSON |
| `error` | `str \| None` | 错误信息 |
| `created_at` | `datetime` | 创建时间（UTC） |

---

## 4. 工作流

定义位置：`/Users/wangruiqi/PycharmProjects/Margin/src/margin/research/workflow.py`

### 4.1 `WorkflowResult`

工作流运行结果数据类。

| 字段 | 类型 | 说明 |
|------|------|------|
| `run_id` | `str` | 运行 ID |
| `state` | `WorkflowState` | 终态 |
| `signals` | `list[ResearchSignal]` | 信号列表 |
| `prior_outputs` | `dict[str, Any]` | 各 Agent 原始输出 |
| `traces` | `list[AgentTrace]` | 轨迹列表 |
| `snapshot` | `dict[str, Any] \| None` | 快照字典 |
| `snapshot_persisted` | `bool` | 是否持久化成功 |
| `error` | `str \| None` | 错误信息 |

### 4.2 `ResearchWorkflow`

多智能体研究工作流状态机。

#### 构造参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `symbol` | `str` | 必填 | 研究标的 |
| `decision_at` | `datetime` | 必填 | 决策时间 |
| `tool_registry` | `ToolRegistry` | 必填 | 工具注册表 |
| `llm_provider` | `LLMProvider \| None` | `None` | LLM 提供者 |
| `model_router` | `ModelRouter \| None` | `None` | 模型路由器 |
| `strategy_config` | `dict[str, Any] \| None` | `None` | 策略配置 |
| `portfolio_id` | `str \| None` | `None` | 组合 ID |
| `claims` | `list[Claim] \| None` | `None` | 初始 Claim |
| `evidences` | `dict[str, Evidence] \| None` | `None` | 初始 Evidence |
| `snapshot_resolver` | `Any \| None` | `None` | 快照解析器 |
| `repository` | `ResearchRepository \| None` | `None` | 快照仓库 |

#### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `run_id` | `str` | 运行 ID |
| `state` | `WorkflowState` | 当前状态 |

#### 方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `run` | `run() -> WorkflowResult` | 执行工作流，异常时转为 `ABORTED` |
| `_execute` | `_execute() -> WorkflowResult` | 实际编排 12 个 Agent |
| `_make_context` | `_make_context() -> AgentContext` | 构造 Agent 共享上下文 |
| `_run_agent` | `_run_agent(agent) -> Any` | 运行单个 Agent 并记录轨迹 |
| `_finish` | `_finish(state, *, signals=None, error=None) -> WorkflowResult` | 结束工作流并持久化快照 |
| `_build_snapshot` | `_build_snapshot(state, signals, error) -> ResearchSnapshot` | 构建审计快照 |

#### `_execute` 执行顺序

1. `DATA_READY`
   - `UniverseFilterAgent`
   - `QuantResearchAgent`
2. `EVIDENCE_READY`
   - `WebSearchAgent`
   - `DocumentCollectorAgent`
   - `TextSummaryAgent`
   - `EvidenceResearchAgent`
3. `ANALYSIS_READY`
   - `ValuationToolAgent`
4. `REVIEW_READY`
   - `RiskReviewAgent`
   - `ReflectCounterArgumentAgent`
   - `PortfolioConstraintAgent`
5. `PUBLISHED` / `ABSTAINED`
   - `ResearchSignalComposer`
   - `CitationValidatorAgent`

---

## 5. LLM 层

定义位置：`/Users/wangruiqi/PycharmProjects/Margin/src/margin/research/llm.py`

### 5.1 `TaskType`

研究任务类型枚举，用于模型路由。

| 成员 | 值 |
|------|-----|
| `UNIVERSE_FILTER` | `universe_filter` |
| `QUANT` | `quant` |
| `WEBSEARCH` | `websearch` |
| `SUMMARY` | `summary` |
| `EVIDENCE` | `evidence` |
| `VALUATION` | `valuation` |
| `RISK` | `risk` |
| `REFLECT` | `reflect` |
| `PORTFOLIO` | `portfolio` |
| `SIGNAL` | `signal` |
| `EXTRACTION` | `extraction` |
| `VALIDATION` | `validation` |

### 5.2 `LLMResult`

LLM 调用结果数据类。

| 字段 | 类型 | 说明 |
|------|------|------|
| `output` | `dict[str, Any]` | 结构化输出 |
| `model` | `str` | 模型名 |
| `success` | `bool` | 是否成功 |
| `latency_ms` | `float` | 耗时（毫秒） |
| `error` | `str \| None` | 错误信息 |
| `raw_response` | `str \| None` | 原始响应字符串 |

### 5.3 `LLMProvider`

OpenAI 兼容的 LLM 提供者，支持结构化 JSON 输出。

#### 构造参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `str` | `"openai_llm"` | 提供者名称 |
| `api_key` | `str \| None` | `MARGIN_LLM_API_KEY` | API 密钥 |
| `base_url` | `str \| None` | `MARGIN_LLM_BASE_URL` | 基础 URL |
| `model` | `str \| None` | `MARGIN_LLM_MODEL` / `gpt-4o-mini` | 模型名 |
| `client` | `httpx.Client \| None` | 新建 | HTTP 客户端 |
| `timeout` | `float` | `60.0` | 超时（秒） |

#### 方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `descriptor` | `descriptor() -> ProviderDescriptor` | 返回提供者描述符 |
| `complete` | `complete(prompt, *, response_schema=None, temperature=0.0) -> LLMResult` | 执行补全调用 |
| `complete_or_raise` | `complete_or_raise(prompt, *, response_schema=None, temperature=0.0) -> LLMResult` | 失败时抛出 `ProviderError` |
| `configure_secrets` | `configure_secrets(secrets: dict[str, str]) -> None` | 从注册表接收 `llm_api_key` |
| `healthcheck` | `healthcheck() -> HealthCheckResult` | 检查 LLM 健康状态 |

### 5.4 `DeterministicLLMProvider`

测试替身，忽略 prompt，返回固定 JSON。

#### 构造参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `str` | `"deterministic_llm"` | 提供者名 |
| `response` | `dict[str, Any] \| None` | `{"result": "ok"}` | 固定返回 |
| `fail` | `bool` | `False` | 是否模拟失败 |
| `error` | `str` | `"injected failure"` | 模拟错误信息 |

#### 方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `descriptor` | `descriptor() -> ProviderDescriptor` | 提供者描述符 |
| `complete` | `complete(prompt, *, response_schema=None, temperature=0.0) -> LLMResult` | 返回固定结果 |
| `healthcheck` | `healthcheck() -> HealthCheckResult` | 始终健康 |

### 5.5 `ModelRouter`

按任务类型路由到不同模型/规则配置。

#### 默认路由 `DEFAULTS`

| 任务 | 默认后端 |
|------|----------|
| `UNIVERSE_FILTER` | `rule` |
| `QUANT` | `rule` |
| `WEBSEARCH` | `rule` |
| `SUMMARY` | `cheap-llm` |
| `EVIDENCE` | `cheap-llm` |
| `VALUATION` | `rule` |
| `RISK` | `cheap-llm` |
| `REFLECT` | `capable-llm` |
| `PORTFOLIO` | `rule` |
| `SIGNAL` | `cheap-llm` |
| `EXTRACTION` | `cheap-llm` |
| `VALIDATION` | `cheap-llm` |

#### 构造参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `overrides` | `dict[TaskType, str] \| None` | `None` | 路由覆盖 |
| `llm_providers` | `dict[str, LLMProvider] \| None` | `None` | 命名 LLM 提供者 |
| `provider_registry` | `ProviderRegistry \| None` | 新建 | 提供者注册表 |

#### 方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `select` | `select(task: TaskType) -> str` | 返回任务对应后端名 |
| `get_provider` | `get_provider(name: str) -> LLMProvider \| None` | 获取命名提供者 |
| `register_provider` | `register_provider(name, provider, *, fallback_names=None) -> None` | 注册提供者 |
| `complete` | `complete(task, prompt, *, response_schema=None, trace_id="") -> LLMResult` | 路由完成调用 |

### 5.6 `StructuredOutputGuardrail`

校验 LLM 输出是否符合 JSON Schema 子集。

#### 构造参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `schema` | `dict[str, Any]` | JSON Schema |

#### 方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `validate` | `validate(output: dict[str, Any]) -> tuple[bool, str]` | 校验输出，返回 `(是否通过, 错误原因)` |
| `_validate_value` | `_validate_value(value, schema, path) -> tuple[bool, str]` | 递归校验值 |

支持校验：`object`、`array`、`string`、`number`、`integer`、`boolean`、`null`、`enum`、`minimum`/`maximum`、`required`、`properties`、`items`。

---

## 6. Agent

定义位置：`/Users/wangruiqi/PycharmProjects/Margin/src/margin/research/agents.py`

### 6.1 `AgentContext`

Agent 共享上下文。

| 字段 | 类型 | 说明 |
|------|------|------|
| `symbol` | `str` | 标的 |
| `decision_at` | `datetime` | 决策时间 |
| `tool_registry` | `ToolRegistry` | 工具注册表 |
| `llm_provider` | `LLMProvider \| None` | LLM 提供者 |
| `model_router` | `ModelRouter \| None` | 模型路由器 |
| `portfolio_id` | `str \| None` | 组合 ID |
| `strategy_config` | `dict[str, Any]` | 策略配置 |
| `prior_outputs` | `dict[str, Any]` | 上游 Agent 输出 |
| `claims` | `list[Claim]` | Claim 列表 |
| `evidences` | `dict[str, Evidence]` | Evidence 字典 |
| `snapshot_resolver` | `Any \| None` | 快照解析器 |
| `trace_id` | `str` | 当前轨迹 ID |

### 6.2 `AgentOutput`

Agent 输出数据类。

| 字段 | 类型 | 说明 |
|------|------|------|
| `agent_node` | `str` | Agent 节点名 |
| `success` | `bool` | 是否成功 |
| `data` | `dict[str, Any]` | 输出数据 |
| `error` | `str \| None` | 错误信息 |
| `trace_id` | `str` | 轨迹 ID |
| `model_version` | `str` | 模型版本 |
| `latency_ms` | `float` | 耗时 |
| `tool_calls` | `list[ToolResult]` | 工具调用结果 |
| `input_hash` | `str` | 输入哈希 |
| `output_hash` | `str` | 输出哈希 |
| `tool_call_ids` | `tuple[str, ...]` | 工具调用 ID |

### 6.3 `Agent`（抽象基类）

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `__init__(llm_provider=None)` | 初始化 |
| `node_name` | `node_name -> str` | 节点名（抽象属性） |
| `output_schema` | `output_schema -> dict[str, Any]` | 默认空 schema |
| `_hash` | `_hash(data) -> str` | SHA256 哈希 |
| `_call_llm` | `_call_llm(context, prompt, task, provider=None, schema=None) -> LLMResult` | 调用 LLM，经 ModelRouter 或直接调用 |
| `_call_tool` | `_call_tool(context, name, params) -> ToolResult` | 调用工具 |
| `run` | `run(context: AgentContext) -> AgentOutput` | 执行（抽象） |
| `_make_output` | `_make_output(context, success, data, error=None, llm_result=None, tool_calls=None) -> AgentOutput` | 构造输出并计算哈希 |

### 6.4 `RuleAgent`

纯规则/工具 Agent 基类，不调用 LLM。

| 方法 | 签名 | 说明 |
|------|------|------|
| `run` | `run(context) -> AgentOutput` | 调用 `_run_rule`，异常返回失败 |
| `_run_rule` | `_run_rule(context) -> dict[str, Any]` | 规则逻辑（抽象） |

### 6.5 `UniverseFilterAgent`

| 属性/方法 | 说明 |
|-----------|------|
| `node_name` | `universe_filter` |
| 逻辑 | 读取 `strategy_config.universe`（默认 `[symbol]`），对每个标的调用 `market_data` 工具；失败则抛出异常；收集 `filtered` 与 `degraded` |
| 输出字段 | `symbols`, `filtered`, `degraded` |

### 6.6 `QuantResearchAgent`

| 属性/方法 | 说明 |
|-----------|------|
| `node_name` | `quant_research` |
| 逻辑 | 取上游 `universe_filter.filtered`，调用 `factor` 工具，按得分降序排列 |
| 输出字段 | `scores`, `ranked`, `top_symbol` |

### 6.7 `WebSearchAgent`

| 属性/方法 | 说明 |
|-----------|------|
| `node_name` | `websearch` |
| `output_schema` | `{"queries": [...]}` |
| 逻辑 | LLM 生成 1-3 条中文查询，对每个查询调用 `websearch` 工具，合并结果 |
| 输出字段 | `queries`, `results` |

### 6.8 `DocumentCollectorAgent`

| 属性/方法 | 说明 |
|-----------|------|
| `node_name` | `document_collector` |
| 逻辑 | 遍历 `websearch.results`，对每个结果调用 `document_collector` 工具，校验必填字段 |
| 输出字段 | `collected`, `count` |

### 6.9 `TextSummaryAgent`

| 属性/方法 | 说明 |
|-----------|------|
| `node_name` | `text_summary` |
| `output_schema` | `{"summaries": [{"source_url", "summary", "key_points"}]}` |
| 逻辑 | 对 `document_collector.collected` 调用 LLM 生成结构化摘要 |
| 输出字段 | `summaries` |

### 6.10 `EvidenceResearchAgent`

| 属性/方法 | 说明 |
|-----------|------|
| `node_name` | `evidence_research` |
| 逻辑 | 调用 `retrieval` 工具检索 `"{symbol} 经营"`，将 `Chunk` 转换为 `Evidence` 与 `Claim`，写入上下文 |
| 输出字段 | `retrieval_results`, `count`, `evidence_ids`, `claim_ids` |

### 6.11 `ValuationToolAgent`

| 属性/方法 | 说明 |
|-----------|------|
| `node_name` | `valuation_tool` |
| 逻辑 | 从策略配置读取 `eps`、`pe`，调用 `valuation` 工具计算 PE 估值 |
| 输出字段 | `value`, `error` |

### 6.12 `RiskReviewAgent`

| 属性/方法 | 说明 |
|-----------|------|
| `node_name` | `risk_review` |
| `output_schema` | `{"risk_score": [0,1], "risk_factors": [...]}` |
| 逻辑 | LLM 基于证据输出风险评分与风险因素（非收益概率） |
| 输出字段 | `risk_score`, `risk_factors` |

### 6.13 `ReflectCounterArgumentAgent`

| 属性/方法 | 说明 |
|-----------|------|
| `node_name` | `reflect_counter_argument` |
| `output_schema` | `{"counter_arguments": [...], "unknowns": [...], "conflict_flags": [...]}` |
| 逻辑 | LLM 输出反向论证、未知项与冲突标记 |
| 输出字段 | `counter_arguments`, `unknowns`, `conflict_flags` |

### 6.14 `PortfolioConstraintAgent`

| 属性/方法 | 说明 |
|-----------|------|
| `node_name` | `portfolio_constraint` |
| 逻辑 | 读取 `max_position_weight`、`current_weight`，调用 `portfolio` 工具检查权重约束 |
| 输出字段 | `violations`, `passed` |

### 6.15 `ResearchSignalComposer`

| 属性/方法 | 说明 |
|-----------|------|
| `node_name` | `signal_composer` |
| `output_schema` | `{"signal_type", "confidence", "statement", "evidence_refs"}` |
| 逻辑 | 若市场数据降级或组合约束不通过，直接 `abstained`；否则由 LLM 综合风险、估值、量化、约束生成信号；LLM 失败时回退规则信号 |
| 方法 | `_normalize_llm_signal(output, evidence_ids) -> dict[str, Any]` 规范化 LLM 输出；`_rule_signal(context, risk, reflect, evidence_ids) -> dict[str, Any]` 规则兜底 |

### 6.16 `CitationValidatorAgent`

| 属性/方法 | 说明 |
|-----------|------|
| `node_name` | `citation_validator` |
| 逻辑 | 校验 `signal_composer.evidence_refs` 是否存在于上下文 `evidences`、是否被 `claims` 引用，并调用 `CitationValidator.validate_batch` 校验来源等级与时效 |
| 输出字段 | `valid`, `reason`, `failed_refs`, `requires_counter_review`, `capped_confidence` |

---

## 7. 工具系统

定义位置：`/Users/wangruiqi/PycharmProjects/Margin/src/margin/research/tools.py`

### 7.1 `ToolResult`

单次工具调用结果。

| 字段 | 类型 | 说明 |
|------|------|------|
| `tool_name` | `str` | 工具名 |
| `success` | `bool` | 是否成功 |
| `data` | `Any` | 返回数据 |
| `error` | `str \| None` | 错误信息 |
| `latency_ms` | `float` | 耗时 |
| `params` | `dict[str, Any] \| None` | 调用参数 |
| `call_id` | `str \| None` | 调用记录 ID |

### 7.2 `ToolPermission`

| 成员 | 值 | 说明 |
|------|-----|------|
| `READ` | `read` | 只读 |
| `WRITE_WITH_CONFIRM` | `write_with_confirm` | 写操作需显式确认 |
| `FORBIDDEN` | `forbidden` | 禁止 |

### 7.3 `ToolCallRecord`

不可变工具调用审计记录。

| 字段 | 类型 | 说明 |
|------|------|------|
| `call_id` | `str` | 调用 ID |
| `trace_id` | `str` | 轨迹 ID |
| `tool_name` | `str` | 工具名 |
| `params_json` | `str` | 参数 JSON（已脱敏） |
| `permission` | `ToolPermission` | 权限 |
| `success` | `bool` | 是否成功 |
| `data_hash` | `str \| None` | 数据哈希 |
| `data_json` | `str \| None` | 数据 JSON（已脱敏） |
| `error` | `str \| None` | 错误 |
| `latency_ms` | `float` | 耗时 |
| `called_at` | `datetime` | 调用时间 |

| 属性/方法 | 说明 |
|-----------|------|
| `params` | 反序列化参数 |
| `data` | 反序列化数据 |
| `serialize_params` | 将参数序列化为 JSON |

### 7.4 `BaseTool`

所有工具抽象基类。

| 方法 | 签名 | 说明 |
|------|------|------|
| `name` | `name -> str` | 工具名（抽象属性） |
| `permission` | `permission -> ToolPermission` | 默认 `READ` |
| `run` | `run(params: dict[str, Any]) -> ToolResult` | 执行（抽象） |
| `_hash` | `_hash(data) -> str` | SHA256 哈希 |

### 7.5 `PythonTool`

受控数值计算工具，禁止 shell 与导入。

| 项目 | 说明 |
|------|------|
| `name` | `python` |
| 允许名称 | `abs`, `round`, `max`, `min`, `sum`, `pow`, `math` |
| 执行方式 | `compile(..., "eval")` + 白名单校验 + 空 builtins |
| 参数 | `expression: str` |

### 7.6 `RetrievalTool`

向量检索包装器。

| 项目 | 说明 |
|------|------|
| `name` | `retrieval` |
| 参数 | `symbol`, `query`, `decision_at` |
| 依赖 | `margin.vector.retrieval.RetrievalTool` + pipeline |
| 输出 | `list[dict]`（Chunk 序列化） |

### 7.7 `_AdapterTool`

带类型处理程序的适配器基类；无 handler 时失败关闭。

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `__init__(handler=None)` | 传入处理函数 |
| `name` | `name -> str` | 返回 `tool_name` |
| `run` | `run(params) -> ToolResult` | 调用 handler 并包装结果 |

### 7.8 具体适配器工具

| 类 | `tool_name` | 说明 |
|----|-------------|------|
| `MarketDataTool` | `market_data` | 市场数据适配 |
| `FinancialTool` | `financial` | 财务报表适配 |
| `FactorTool` | `factor` | 因子计算适配 |
| `PortfolioTool` | `portfolio` | 组合约束适配 |
| `WebSearchTool` | `websearch` | 网络搜索适配 |
| `CalendarTool` | `calendar` | 交易日历适配 |
| `AlertTool` | `alert` | 告警创建适配，权限 `WRITE_WITH_CONFIRM` |
| `BacktestTool` | `backtest` | 回测适配 |
| `FilingTool` | `filing` | 公告/文件查询适配 |
| `DocumentCollectorTool` | `document_collector` | 合规文档采集适配 |

### 7.9 `ValuationTool`

简易估值工具，内部使用 `PythonTool`。

| 项目 | 说明 |
|------|------|
| `name` | `valuation` |
| 方法 | `pe`（默认）：`value = eps * pe` |
| 参数 | `method`, `eps`, `pe` |
| 输出 | `{"method", "value"}` |

### 7.10 `ToolRegistry`

工具注册表，管理 Agent 可调用工具及审计记录。

#### 方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `__init__()` | 初始化空注册表与审计列表 |
| `register` | `register(tool: BaseTool) -> None` | 注册工具 |
| `register_defaults` | `register_defaults(pipeline=None) -> None` | 注册默认工具集 |
| `get` | `get(name: str) -> BaseTool \| None` | 获取工具 |
| `list_tools` | `list_tools() -> list[str]` | 列出工具名 |
| `describe_tools` | `describe_tools() -> list[dict[str, str]]` | 返回公开元数据（不含 handler） |
| `audit_records` | `audit_records -> tuple[ToolCallRecord, ...]` | 审计记录 |
| `call` | `call(name, params, *, trace_id="", confirmed=False) -> ToolResult` | 调用工具并记录审计 |
| `_record` | `_record(result, *, permission, trace_id) -> ToolResult` | 生成审计记录并返回带 `call_id` 的结果 |

#### `call` 权限控制

- 工具不存在：返回错误，权限 `FORBIDDEN`。
- 工具权限为 `FORBIDDEN`：返回错误。
- 工具权限为 `WRITE_WITH_CONFIRM` 且未确认：返回 `"confirmation required"`。
- 否则执行 `tool.run(params)`。

### 7.11 `_redact`

递归脱敏函数。

| 参数 | 类型 | 说明 |
|------|------|------|
| `value` | `Any` | 待脱敏值 |
| `key` | `str` | 当前键 |

脱敏关键词：`api_key`, `token`, `password`, `secret`, `authorization`。

---

## 8. 生产工具注册表

定义位置：`/Users/wangruiqi/PycharmProjects/Margin/src/margin/research/production_tools.py`

### `build_production_tool_registry`

构造具备真实只读适配器的生产工具注册表。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `settings` | `MarginSettings` | 必填 | 应用配置 |
| `market_data_provider` | `Any \| None` | `AKShareProvider()` | 市场数据提供者 |
| `embedding_provider` | `Any \| None` | `None` | Embedding 提供者 |
| `news_repository` | `NewsRepository \| None` | `None` | 新闻仓库 |
| `snapshot_store` | `SnapshotStore \| None` | `SnapshotStore()` | 快照存储 |
| `vector_repository` | `VectorRepository \| None` | `None` | 向量仓库 |

#### 内部实现要点

| 工具 | 实现来源 |
|------|----------|
| `market_data` | `AKShareProvider.get_bars`，取最近 120 天最新一根 K 线 |
| `factor` | 基于 120 天首尾收盘价计算收益率 |
| `financial` | `AKShareProvider.get_financials`，最近 550 天 |
| `portfolio` | 规则检查 `current_weight > max_weight` |
| `websearch` | `TavilySearchAdapter` + `WebSearchProvider` |
| `document_collector` | `OriginalContentVerifier` 快照原文，生成 `DocumentEvent` |

---

## 9. 快照与仓库

### 9.1 `ResearchSnapshotBuilder`

定义位置：`/Users/wangruiqi/PycharmProjects/Margin/src/margin/research/snapshot.py`

不可变审计快照的构建器，采用链式 API。

#### 方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `for_run` | `for_run(run_id: str) -> ResearchSnapshotBuilder` | 设置运行 ID |
| `with_state` | `with_state(state: WorkflowState) -> ResearchSnapshotBuilder` | 设置状态 |
| `with_decision_at` | `with_decision_at(decision_at: datetime) -> ResearchSnapshotBuilder` | 设置决策时间 |
| `with_symbols` | `with_symbols(symbols: list[str]) -> ResearchSnapshotBuilder` | 设置标的 |
| `with_strategy_version` | `with_strategy_version(version: str) -> ResearchSnapshotBuilder` | 策略版本 |
| `with_prompt_version` | `with_prompt_version(version: str) -> ResearchSnapshotBuilder` | Prompt 版本 |
| `with_tool_versions` | `with_tool_versions(versions: dict[str, str]) -> ResearchSnapshotBuilder` | 工具版本 |
| `with_model_versions` | `with_model_versions(versions: dict[str, str]) -> ResearchSnapshotBuilder` | 模型版本 |
| `with_evidence_ids` | `with_evidence_ids(ids: list[str]) -> ResearchSnapshotBuilder` | 证据 ID |
| `with_claim_ids` | `with_claim_ids(ids: list[str]) -> ResearchSnapshotBuilder` | Claim ID |
| `with_signals` | `with_signals(signals: list[ResearchSignal]) -> ResearchSnapshotBuilder` | 信号 |
| `with_traces` | `with_traces(traces: list[AgentTrace]) -> ResearchSnapshotBuilder` | 轨迹 |
| `with_prior_outputs` | `with_prior_outputs(outputs: dict[str, Any]) -> ResearchSnapshotBuilder` | Agent 原始输出 |
| `with_tool_call_ids` | `with_tool_call_ids(call_ids: list[str]) -> ResearchSnapshotBuilder` | 工具调用 ID |
| `with_tool_calls` | `with_tool_calls(tool_calls: list[dict[str, Any]]) -> ResearchSnapshotBuilder` | 工具调用记录 |
| `with_error` | `with_error(error: str \| None) -> ResearchSnapshotBuilder` | 错误信息 |
| `_hash` | `_hash(data: Any) -> str` | 静态哈希方法 |
| `build` | `build() -> ResearchSnapshot` | 构建快照并计算 input/output 哈希 |

### 9.2 `ResearchRepository`

定义位置：`/Users/wangruiqi/PycharmProjects/Margin/src/margin/research/repository.py`

快照持久化协议。

| 方法 | 签名 | 说明 |
|------|------|------|
| `add_snapshot` | `add_snapshot(snapshot: ResearchSnapshot) -> None` | 幂等地持久化快照 |
| `get_snapshot` | `get_snapshot(snapshot_id: str) -> ResearchSnapshot \| None` | 按 ID 获取 |
| `get_snapshot_for_run` | `get_snapshot_for_run(run_id: str) -> ResearchSnapshot \| None` | 获取某运行最新快照 |

### 9.3 `MemoryResearchRepository`

进程内内存仓库，用于测试与本地调用。

| 字段 | 说明 |
|------|------|
| `_snapshots` | `dict[str, ResearchSnapshot]` |
| `_run_snapshots` | `dict[str, str]` 运行到最新快照 ID 的映射 |

| 方法 | 说明 |
|------|------|
| `add_snapshot` | 若 snapshot_id 已存在且内容不同，抛出 `ValueError` |
| `get_snapshot` | 按 ID 返回 |
| `get_snapshot_for_run` | 返回运行最新快照 |

### 9.4 `SQLAlchemyResearchRepository`

PostgreSQL 持久化仓库。

| 字段 | 说明 |
|------|------|
| `_session_factory` | `Callable[[], Session]` |

| 方法 | 说明 |
|------|------|
| `add_snapshot` | 将 `ResearchSnapshot` 序列化为 JSONB 存入 `research_snapshots`；若 ID 已存在但 payload 不同则抛异常 |
| `get_snapshot` | 按主键读取 payload 并反序列化 |
| `get_snapshot_for_run` | 按 `run_id` 倒序取第一条 |

### 9.5 `ResearchSnapshotRow`

定义位置：`/Users/wangruiqi/PycharmProjects/Margin/src/margin/research/db_models.py`

| 字段 | 类型 | 说明 |
|------|------|------|
| `snapshot_id` | `String(64)` | 主键 |
| `run_id` | `String(64)` | 运行 ID，索引 |
| `workflow_state` | `String(32)` | 工作流状态 |
| `payload` | `JSONB` | 序列化快照 |
| `input_hash` | `String(96)` | 输入哈希 |
| `output_hash` | `String(96)` | 输出哈希 |
| `created_at` | `DateTime(timezone=True)` | 创建时间 |

索引：`ix_research_snapshots_run_created` 覆盖 `(run_id, created_at)`。

---

## 10. 服务与 API

### 10.1 `ResearchService`

定义位置：`/Users/wangruiqi/PycharmProjects/Margin/src/margin/research/service.py`

高层研究服务入口。

#### 构造参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `tool_registry` | `ToolRegistry \| None` | `ToolRegistry()` | 工具注册表 |
| `llm_provider` | `LLMProvider \| None` | `None` | LLM 提供者 |
| `strategy_config` | `dict[str, Any] \| None` | `{}` | 策略配置 |
| `repository` | `ResearchRepository \| None` | `MemoryResearchRepository()` | 快照仓库 |
| `audit_repository` | `AuditRepository \| None` | `None` | 审计仓库 |

#### 方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `run` | `run(symbol, decision_at=None, portfolio_id=None) -> WorkflowResult` | 构造并执行 `ResearchWorkflow`；成功后写入审计日志 |
| `list_tools` | `list_tools() -> list[dict[str, str]]` | 返回已注册工具元数据 |
| `get_snapshot` | `get_snapshot(snapshot_id: str) -> ResearchSnapshot \| None` | 获取持久化快照 |

### 10.2 FastAPI 路由

定义位置：`/Users/wangruiqi/PycharmProjects/Margin/src/margin/api/routes/research.py`

#### `ResearchRunRequest`

| 字段 | 类型 | 校验 |
|------|------|------|
| `symbol` | `str` | `1 <= len <= 32`，自动 `strip().upper()` |
| `decision_at` | `datetime \| None` | 可选 |
| `portfolio_id` | `str \| None` | 可选 |

#### `ResearchRunResponse`

| 字段 | 类型 | 说明 |
|------|------|------|
| `run_id` | `str` | 运行 ID |
| `state` | `str` | 终态字符串 |
| `signals` | `list[dict[str, Any]]` | 信号字典列表 |
| `snapshot_id` | `str \| None` | 持久化后的快照 ID |
| `error` | `str \| None` | 错误信息 |

#### 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/research/run` | 执行研究；若状态为 `aborted` 返回 `422` |
| `GET` | `/research/tools` | 列出可用工具及其权限 |

---

## 11. 跨模块使用说明

### 11.1 依赖模块

| 模块 | 用途 |
|------|------|
| `margin.core.provider` / `margin.core.registry` / `margin.core.resilience` | LLM 提供者抽象、注册表与错误 |
| `margin.core.audit_repository` | 审计日志写入 |
| `margin.core.models` | `AuditLogRecord` |
| `margin.news.models` | UTC 时间、文档事件、来源等级 |
| `margin.news.acquirer` / `margin.news.providers.tavily` / `margin.news.websearch` | 网络搜索与文档快照 |
| `margin.evidence.models` / `margin.evidence.validator` | Claim/Evidence 模型与引用校验 |
| `margin.vector.models` / `margin.vector.retrieval` / `margin.vector.persistent_pipeline` | 向量检索与 Embedding |
| `margin.data.providers.akshare_provider` | A 股市场数据 |
| `margin.settings` | 应用配置 |
| `margin.api.dependencies` | FastAPI 依赖注入 `get_research_service` |

### 11.2 典型使用方式

```python
from margin.research.service import ResearchService
from margin.research.production_tools import build_production_tool_registry
from margin.settings import MarginSettings

settings = MarginSettings()
tools = build_production_tool_registry(settings)
service = ResearchService(tool_registry=tools)
result = service.run(symbol="000001")
```

### 11.3 重要约定

- **不可变性**：`ResearchSnapshot`、`ToolCallRecord`、Pydantic 模型均不可变；仓库拒绝同一 ID 的内容变更。
- **只读工具**：默认工具权限为 `READ`；`alert` 为 `WRITE_WITH_CONFIRM`。
- **失败模式**：Agent 与工具多采用“失败关闭（fail-closed）”，无 handler 或调用失败时返回错误而非静默忽略。
- **审计**：所有工具调用与 Agent 轨迹均被记录哈希与耗时，便于回溯。
- **LLM 可选**：当未配置 LLM 时，纯规则 Agent 仍可运行；依赖 LLM 的 Agent 会返回失败，`Workflow` 可能进入 `ABSTAINED` 或 `ABORTED`。
