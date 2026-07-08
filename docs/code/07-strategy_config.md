# 07-strategy_config 模块文档

## 目录

1. [模块概述](#1-模块概述)
2. [文件级摘要](#2-文件级摘要)
3. [领域模型](#3-领域模型)
4. [模板](#4-模板)
5. [服务与生命周期](#5-服务与生命周期)
6. [Prompt 层](#6-prompt-层)
7. [仓库](#7-仓库)
8. [FastAPI 接口](#8-fastapi-接口)
9. [跨模块使用说明](#9-跨模块使用说明)

---

## 1. 模块概述

`07-strategy_config` 是 Margin 当前实现 的策略配置模块，负责定义、存储、验证、版本化以及生命周期管理投资策略。每个策略由可编辑的 `StrategyProfile`（档案）和一组不可变的 `StrategyVersion`（版本快照）组成，支持从内置模板创建、自定义创建、版本更新、沙盒验证、回测/模拟交易、激活、暂停与归档等完整生命周期。

主要职责包括：

- 定义策略领域模型（投资范围、估值、质量、风险、AI、证据、决策约束）。
- 提供 6 组内置策略模板（价值质量、低估修复、高股息、成长合理估值、周期反转、完全自定义）。
- 对策略配置执行校验与系统级护栏合并（禁止保证收益、禁止直接买卖指令）。
- 管理策略版本状态机（DRAFT → VALIDATING → BACKTESTING → PAPER_TRADING → ACTIVE 等）。
- 运行沙盒轻量检查，防止数据泄漏与配置错误。
- 按分层架构组装最终投研 Prompt（System Guardrail / Platform / Template / User Custom / Task Context / Evidence）。
- 提供内存与 PostgreSQL（SQLAlchemy）两种仓库实现。
- 通过 FastAPI 路由暴露 RESTful 接口。

### 1.1 v0.2 已实现配置边界

当前代码同时实现了独立于旧 `StrategyProfile` 的 v0.2 版本化配置边界：

- `ProviderConfigVersion`：Provider 非敏感配置和独立 `secret_version_id` 引用。
- `UniverseDefinitionVersion`：沪深 300、中证 500、全 A 等公司池规则和成员快照。
- `IndicatorViewVersion`：仅控制用户/AI 可见指标；不会删除量化所需指标。
- `QuantFeatureSetVersion`：定义量化 required/optional 指标、历史窗口和缺失策略。
- `QuantStrategyVersion`：定义因子权重、阈值与 calibration report 引用。
- `UserStylePromptVersion`、`ToolPolicyVersionRef`：冻结用户表达风格和工具权限版本。
- `ResearchScopeVersion`：冻结上述版本 ID、Canonical rule 和 Provider config；`scope_hash` 使用 canonical JSON + SHA-256 确定性计算。

配置生命周期为 `draft -> review -> active -> deprecated`。PostgreSQL partial unique index 和 repository 激活事务共同保证同一配置 family 只有一个 active 版本；Provider config 的运行时 family 进一步按 `llm`、`web_search`、`data_source`、`embedding`、`rerank` 分类互斥，允许每类各有一个 active。量化策略没有 calibration report 时不能激活；Research Scope 引用缺失、非 active 或 deprecated 版本时不能激活。激活公司池、量化策略、量化特征集、指标视图、风格 Prompt 或工具策略时，`StrategyService` 会复制当前 active Research Scope、替换对应版本引用并激活新的 scope，保证 `scope-current` 与最新配置一致；API 边界还会通过 `ensure_current_research_scope()` 校准历史遗留的 stale scope。

`StrategyBootstrapService.ensure_default_index_universes()` 会从数据层已落地的 Tushare 指数成分创建默认 `CSI300` / `CSI500` 公司池版本（`universe-csi300-default-v0.3.0`、`universe-csi500-default-v0.3.0`），状态保持 `review`，不自动切换当前 scope；用户在设置页显式切换后才会滚动新的 active Research Scope。`ALL_A` 仍由数据层 company pool 维护。

Provider URL 会通过 `provider_router` 在分类内自动识别供应商标签：LLM 支持 DeepSeek、OpenAI、OpenRouter、Qwen、Gemini、Anthropic、ModelScope、Zhipu、Ollama、VLLM 和本地 OpenAI-compatible；WebSearch 支持 Tavily、Exa、SerpAPI、Bing；数据源支持 Tushare、AKShare；Embedding 支持 OpenAI-compatible、DashScope、Jina；Rerank 支持 Jina、Cohere。未匹配 URL 反显为 `Custom` 并保留用户提供的 URL。Token 仍只做加密写入，不参与持久化明文检测。

用户指标视图与量化特征集是正交配置：`IndicatorViewVersion` 可以隐藏 `pb`，但 `QuantFeatureSetVersion.required_indicators` 仍可要求 `pb`，因此前端展示偏好不会改变底层全量数据同步和量化输入。默认量化特征集当前要求 `n_income_attr_p`、`roe_ttm`、`pe_ttm`：`n_income_attr_p` 用于第四层 ETL 派生最近两年净利，`roe_ttm` 作为财务 freshness canary。

当前默认 bootstrap 会创建并激活 v0.4.1 ML 量化配置：`quant-feature-default-v0.4.1`、`quant-strategy-ml-lifecycle-v0.4.1`、`scope-default-v0.4.1`。历史 v0.2/v0.3/v0.4.0 配置不会被覆盖；当库里已有旧 active 版本时，repository 激活事务会先 flush/deprecate 旧 active 行，再激活新版本，以满足 PostgreSQL partial unique index 的“一类一个 active”约束。v0.4.1 将旧多因子底层字段 `n_income_attr_p` 从必需字段降为可选，量化 serving 使用第四层派生的 `net_profit_y1` / `net_profit_y2`。

### 1.2 Secret Store 与权限边界

- `SecretStore` 使用 AES-GCM-256、每次写入随机 96-bit nonce，并把 provider、secret name、version ID、key version 作为 associated data。
- 数据库只保存密文、nonce、key version、algorithm、last four 和审计元数据；API 不返回明文、密文、nonce 或 key material。
- Secret 按版本保存；策略配置层把 provider config version ID 作为 secret scope，因此替换一个新 config version 的 token 不会停用其他 config version 绑定的 token。
- active Provider config 不允许原地换 secret；前端在保存 active 配置的新 token 时会自动创建 draft config version，再把加密 secret 绑定到新版本。
- Provider secret API 在个人本地模式下不要求 admin Bearer 或 CSRF；写入仍要求 `Idempotency-Key` 并记录 append-only 审计。
- 所有 v0.2 create/activate mutation 都把 actor/action/idempotency key 写入 append-only `strategy_config_audits`；数据库唯一 partial index 保证并发重放只产生一个审计事件。
- 前端 Provider Settings 启动时读取 `/api/v1/provider-configs` 的安全元数据，优先展示最近已配置 encrypted secret 的版本；密码输入框永远不反显明文，保存/测试后立即清空，只显示 `•••• last_four`，不再要求用户输入管理员 token 或 CSRF token。
- 前端读取 `/api/v1/provider-configs` 与 `/api/v1/provider-status` 使用 `no-store`，避免保存/激活后被 30 秒 revalidate 缓存挡住；激活成功后本地状态立即反显 `active`。
- Provider health 使用冻结的 config/secret version，真实调用 Tushare、AKShare、Tavily、LLM、Embedding 或 Rerank 的轻量 `healthcheck()`；错误经过 secret redaction。
- Provider 激活成功后会清理 dashboard/news/agentic news/valuation discovery runtime cache，后续研究刷新会重新从数据库读取 active config 和加密 secret。
- Provider URL 同时执行 scheme、DNS/IP 禁止网段和 provider host allowlist 校验；自定义公网 host 必须显式 `allow_custom_base_url=true`，且不能绕过 loopback/private/link-local 限制。

---

## 2. 文件级摘要

| 文件路径 | 职责 |
| --- | --- |
| `src/margin/strategy/__init__.py` | 模块公开 API，聚合导出主要类、函数与常量。 |
| `src/margin/strategy/models.py` | 定义全部 Pydantic 领域模型与状态枚举。 |
| `src/margin/strategy/db_models.py` | SQLAlchemy 持久化表：`strategy_profiles`、`strategy_versions`。 |
| `src/margin/strategy/templates.py` | 内置策略模板定义与模板元数据列表。 |
| `src/margin/strategy/validator.py` | 配置校验与系统护栏合并。 |
| `src/margin/strategy/lifecycle.py` | 策略版本状态机与合法状态转移。 |
| `src/margin/strategy/sandbox.py` | 沙盒评估：校验、样例运行、回测、数据泄漏、成本、预览可用性。 |
| `src/margin/strategy/prompt.py` | 分层 Prompt 构建器。 |
| `src/margin/strategy/repository.py` | 仓库协议及内存、SQLAlchemy 两种实现。 |
| `src/margin/strategy/service.py` | 业务入口 `StrategyService`，编排创建、更新、校验、生命周期与 Prompt。 |
| `src/margin/strategy/scope.py` | `ScopeResolver`，解析 active 配置并生成冻结 Research Scope。 |
| `src/margin/strategy/bootstrap.py` | 默认 Provider、ALL_A scope、CSI300/CSI500 公司池版本 bootstrap。 |
| `src/margin/strategy/provider_config.py` | Provider health、SSRF guard、secret-safe 结果。 |
| `src/margin/strategy/provider_router.py` | Provider 分类与 URL 正则识别；输出安全的 `detected_label` / `router_rule_id` / Custom metadata。 |
| `src/margin/strategy/provider_runtime.py` | 按 active Provider category 解析运行时 adapter，并只在构造 adapter 时内存解密 token。 |
| `src/margin/core/secret_store.py` | AES-GCM 版本化 Secret Store 与脱敏。 |
| `src/margin/api/routes/strategy.py` | FastAPI 路由，前缀 `/strategies`。 |
| `src/margin/api/routes/strategy_config.py` | v0.2 配置路由，前缀 `/api/v1`。 |
| `web/components/provider-settings-panel.tsx` | Provider 设置页：LLM、网页搜索、数据源、向量化模型、Rerank 五个独立配置块；URL 自动反显供应商标签，token write-only 加密写入。 |
| `web/lib/provider-settings.ts` | 前端 Provider 分类、URL 标签识别和默认 secret name 规则。 |

---

## 3. 领域模型

### 3.1 枚举

#### `StrategyState`

位置：`src/margin/strategy/models.py`

策略版本生命周期状态。

| 值 | 含义 |
| --- | --- |
| `DRAFT` | 草稿 |
| `VALIDATING` | 校验中 |
| `INVALID` | 校验失败 |
| `BACKTESTING` | 回测中 |
| `PAPER_TRADING` | 模拟交易中 |
| `ACTIVE` | 已激活，用于实盘/实研究运行 |
| `ARCHIVED` | 已归档 |
| `SUSPENDED` | 已暂停 |

#### `ProhibitedOutput`

| 值 | 含义 |
| --- | --- |
| `GUARANTEED_RETURN` | 禁止承诺/保证收益 |
| `DIRECT_BUY_SELL_ORDER` | 禁止直接发出买卖指令 |

### 3.2 配置子模型

#### `AIConfig`

AI 提供商与 Prompt 设置。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `provider` | `str` | `"openai"` | AI 服务提供商 |
| `model` | `str` | `"deepseek-v4-pro"` | 模型名称 |
| `websearch_provider` | `str` | `"tavily"` | 联网搜索提供商 |
| `system_prompt_template` | `str` | `"default"` | 系统提示模板标识 |
| `custom_instructions` | `str` | `""` | 用户自定义指令 |

#### `EvidenceConfig`

证据要求。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `required_levels` | `list[str]` | `["L1", "L2", "L3"]` | 需要的证据等级 |
| `min_evidence_count` | `int` | `3` | 最少证据数量，必须 `>= 0` |

校验器：`validate_min_evidence` 保证 `min_evidence_count` 非负。

#### `DecisionConfig`

决策边界与禁止输出。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `research_states` | `list[str]` | `["research_candidate", "watch", "abstained"]` | 研究阶段可输出状态 |
| `position_review_states` | `list[str]` | `["hold", "review", "close"]` | 持仓复盘可输出状态 |
| `prohibited_outputs` | `list[str]` | `[]` | 额外禁止输出，系统会自动合并 `GUARANTEED_RETURN` 与 `DIRECT_BUY_SELL_ORDER` |

#### `ValuationConfig`

估值方法配置。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `method` | `str` | `"pe"` | 估值方法，如 `pe`、`peg`、`pb`、`dividend_yield` |
| `eps` | `float` | `1.0` | 每股收益基准 |
| `pe` | `float` | `10.0` | 市盈率基准 |

#### `QualityConfig`

数据质量与来源约束。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `min_source_level` | `str` | `"L3"` | 最低来源等级 |
| `require_primary_source` | `bool` | `True` | 是否要求一手来源 |

#### `RiskConfig`

风险限制。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `max_position_weight` | `float` | `0.1` | 单个头寸最大权重，必须落在 `(0, 1]` |
| `max_sector_weight` | `float` | `0.3` | 单个行业最大权重，必须落在 `(0, 1]` |
| `max_drawdown` | `float \| None` | `None` | 最大回撤限制 |
| `risk_score_threshold` | `float` | `0.7` | 风险评分阈值 |

校验器：`validate_weights` 保证权重在 `(0, 1]` 之间。

#### `StrategyConfig`

完整的用户可编辑策略配置。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `universe` | `list[str]` | `["000001.SZ"]` | 投资标的列表 |
| `horizon` | `int` | `90` | 研究/持有时间 horizon，必须 `>= 1` |
| `valuation` | `ValuationConfig` | 默认实例 | 估值配置 |
| `quality` | `QualityConfig` | 默认实例 | 质量配置 |
| `risk` | `RiskConfig` | 默认实例 | 风险配置 |
| `ai` | `AIConfig` | 默认实例 | AI 配置 |
| `evidence` | `EvidenceConfig` | 默认实例 | 证据配置 |
| `decision` | `DecisionConfig` | 默认实例 | 决策配置 |

### 3.3 版本与档案模型

#### `PromptLayer`

单个 Prompt 层，用于审计与序列化。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `layer` | `str` | 必填 | 层标识，如 `system_guardrail` |
| `content` | `str` | 必填 | 层内容 |
| `editable` | `bool` | `True` | 是否允许用户编辑 |

模型为 `frozen=True`。

#### `StrategySandboxResult`

沙盒执行结果。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `validation_ok` | `bool` | `False` | 配置校验是否通过 |
| `sample_run_ok` | `bool` | `False` | 样例运行是否通过 |
| `backtest_ok` | `bool` | `False` | 回测检查是否通过 |
| `data_leak_ok` | `bool` | `False` | 数据泄漏检查是否通过 |
| `cost_ok` | `bool` | `False` | 成本检查是否通过 |
| `preview_ok` | `bool` | `False` | 报告预览是否可用 |
| `messages` | `list[str]` | `[]` | 失败信息列表 |

#### `StrategyVersion`

不可变的策略版本快照。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `strategy_id` | `str` | 必填 | 所属档案 ID |
| `version_id` | `str` | `sv_<uuid[:12]>` | 版本唯一标识 |
| `name` | `str` | 必填 | 版本名称 |
| `description` | `str` | `""` | 版本描述 |
| `config` | `StrategyConfig` | 必填 | 策略配置快照 |
| `prompt_layers` | `tuple[PromptLayer, ...]` | `()` | 分层 Prompt |
| `state` | `StrategyState` | `DRAFT` | 生命周期状态 |
| `prompt_version` | `str` | `""` | Prompt 版本号 |
| `sandbox_result` | `StrategySandboxResult \| None` | `None` | 沙盒结果 |
| `created_at` | `datetime` | `utc_now()` | 创建时间，强制 UTC |

模型为 `frozen=True`；提供 `normalize_created_at` 校验器统一时区。

#### `StrategyProfile`

可变的策略档案，拥有多个不可变版本。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `strategy_id` | `str` | `st_<uuid[:12]>` | 档案唯一标识 |
| `owner_id` | `str` | 必填 | 所有者 ID |
| `name` | `str` | 必填 | 档案名称 |
| `active_version_id` | `str` | `""` | 当前激活的版本 ID |
| `versions` | `tuple[StrategyVersion, ...]` | `()` | 版本快照集合 |
| `created_at` | `datetime` | `utc_now()` | 创建时间，强制 UTC |
| `updated_at` | `datetime` | `utc_now()` | 更新时间，强制 UTC |

模型为 `frozen=True`；通过 `model_copy` 实现不可变更新。

| 方法 | 参数 | 返回值 | 说明 |
| --- | --- | --- | --- |
| `with_version` | `version: StrategyVersion` | `StrategyProfile` | 返回追加新版本后的新档案，并更新 `updated_at` |
| `with_active_version` | `version_id: str` | `StrategyProfile` | 返回更新 `active_version_id` 后的新档案，并更新 `updated_at` |

#### `StrategyTemplateMeta`

内置模板元数据。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `template_id` | `str` | 模板唯一标识 |
| `name` | `str` | 模板中文名 |
| `description` | `str` | 模板描述 |
| `category` | `str` | 分类，如 `value`、`growth`、`income` |

模型为 `frozen=True`。

---

## 4. 模板

### 4.1 `StrategyTemplate`

位置：`src/margin/strategy/templates.py`

内置策略模板，包含元数据与默认配置。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `meta` | `StrategyTemplateMeta` | 模板元数据 |
| `config` | `StrategyConfig` | 默认策略配置 |

### 4.2 `list_templates`

| 签名 | 返回值 | 说明 |
| --- | --- | --- |
| `list_templates() -> list[StrategyTemplateMeta]` | 所有内置模板元数据列表 | 用于前端模板选择页 |

### 4.3 `BUILTIN_TEMPLATES`

常量字典 `dict[str, StrategyTemplate]`，包含以下 6 个模板：

| template_id | 名称 | 类别 | 主要特点 |
| --- | --- | --- | --- |
| `value_quality` | 价值质量 | `value` | 低估值高质量龙头，关注 ROE 与现金流，horizon 180 天 |
| `undervalued_recovery` | 低估修复 | `value` | 短期利空后估值修复，horizon 90 天 |
| `high_dividend` | 高股息 | `income` | 连续分红、股息率稳定，horizon 365 天 |
| `growth_at_reasonable_price` | 成长合理估值 | `growth` | 合理估值下的可持续成长，horizon 120 天 |
| `cyclical_reversal` | 周期反转 | `cyclical` | 周期行业供需拐点，horizon 180 天 |
| `custom` | 用户完全自定义 | `custom` | 全部使用 `StrategyConfig` 默认值 |

---

## 5. 服务与生命周期

### 5.1 `StrategyLifecycle`

位置：`src/margin/strategy/lifecycle.py`

策略版本状态机。

| 方法 | 参数 | 返回值 | 说明 |
| --- | --- | --- | --- |
| `can_transition` | `from_state: StrategyState`, `to_state: StrategyState` | `bool` | 判断状态转移是否合法 |
| `transition` | `version: StrategyVersion`, `to_state: StrategyState`, `reason: str = ""` | `StrategyVersion` | 返回状态更新后的新版本；非法转移抛出 `ValueError`；`reason` 会追加到 `description` |

合法转移关系：

- `DRAFT` → `VALIDATING`
- `VALIDATING` → `INVALID` / `BACKTESTING`
- `BACKTESTING` → `PAPER_TRADING`
- `PAPER_TRADING` → `ACTIVE`
- `ACTIVE` → `ARCHIVED` / `SUSPENDED`
- `SUSPENDED` → `ACTIVE` / `ARCHIVED`
- `INVALID` / `ARCHIVED` 为终态

### 5.2 `StrategyValidator`

位置：`src/margin/strategy/validator.py`

| 方法 | 参数 | 返回值 | 说明 |
| --- | --- | --- | --- |
| `validate` | `config: StrategyConfig` | `tuple[bool, list[str]]` | 执行模型校验与护栏检查，返回是否通过及错误列表 |
| `merge_with_guardrails` | `config: StrategyConfig` | `StrategyConfig` | 合并系统强制禁止输出，并保证 `min_evidence_count >= 1` |
| `validate_dict` | `data: dict[str, Any]` | `tuple[bool, list[str]]` | 先解析为 `StrategyConfig`，再调用 `validate` |

`validate` 额外检查项：

- `universe` 非空
- `evidence.min_evidence_count >= 1`
- `horizon >= 1`
- `risk.max_position_weight` 在 `(0, 1]`

`merge_with_guardrails` 强制追加的 `prohibited_outputs`：

- `GUARANTEED_RETURN`
- `DIRECT_BUY_SELL_ORDER`

### 5.3 `StrategySandbox`

位置：`src/margin/strategy/sandbox.py`

| 方法 | 参数 | 返回值 | 说明 |
| --- | --- | --- | --- |
| `evaluate` | `config: StrategyConfig` | `StrategySandboxResult` | 运行全部沙盒检查并返回结构化结果 |
| `_check_data_leak` | `config: StrategyConfig` | `bool` | 占位实现：检查 `horizon >= 0` 且 `min_evidence_count >= 1` |

`evaluate` 检查逻辑：

- `validation_ok`：调用 `StrategyValidator.validate`
- `sample_run_ok`：校验通过且 `universe` 非空
- `backtest_ok` / `cost_ok`：跟随 `sample_run_ok`
- `data_leak_ok`：调用 `_check_data_leak`
- `preview_ok`：`validation_ok && sample_run_ok && data_leak_ok`

### 5.4 `StrategyService`

位置：`src/margin/strategy/service.py`

业务入口，编排仓库、校验、生命周期、沙盒与 Prompt。

构造函数参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `repository` | `StrategyRepository \| None` | `MemoryStrategyRepository()` | 持久化仓库 |
| `validator` | `StrategyValidator \| None` | `StrategyValidator()` | 校验器 |
| `lifecycle` | `StrategyLifecycle \| None` | `StrategyLifecycle()` | 生命周期状态机 |
| `sandbox` | `StrategySandbox \| None` | `StrategySandbox(self._validator)` | 沙盒 |
| `prompt_builder` | `PromptLayerBuilder \| None` | `PromptLayerBuilder()` | Prompt 构建器 |

| 方法 | 参数 | 返回值 | 说明 |
| --- | --- | --- | --- |
| `create_from_template` | `owner_id: str`, `template_id: str`, `name: str = ""`, `description: str = ""` | `StrategyProfile` | 从内置模板创建策略档案 |
| `create_custom` | `owner_id: str`, `config: StrategyConfig`, `name: str`, `description: str = ""` | `StrategyProfile` | 从自定义配置创建策略档案 |
| `update_strategy` | `strategy_id: str`, `config_delta: dict \| None = None`, `name: str \| None = None`, `description: str \| None = None` | `StrategyProfile` | 基于最新版本生成新版本，支持深度合并配置增量 |
| `validate_version` | `strategy_id: str`, `version_id: str` | `StrategyProfile` | 校验并运行沙盒；失败则进入 `INVALID`，成功则推进到 `BACKTESTING` |
| `backtest_version` | `strategy_id: str`, `version_id: str` | `StrategyProfile` | 将版本从 `BACKTESTING` 推进到 `PAPER_TRADING` |
| `paper_trade_version` | `strategy_id: str`, `version_id: str` | `StrategyProfile` | 确认模拟交易就绪 |
| `activate_version` | `strategy_id: str`, `version_id: str` | `StrategyProfile` | 激活版本为 `ACTIVE`，并设为档案的 `active_version_id` |
| `suspend_version` | `strategy_id: str`, `version_id: str`, `reason: str = ""` | `StrategyProfile` | 暂停活跃版本 |
| `archive_strategy` | `strategy_id: str` | `StrategyProfile` | 归档当前 `active_version_id` 对应的版本 |
| `get_profile` | `strategy_id: str` | `StrategyProfile` | 获取策略档案 |
| `list_profiles` | `owner_id: str` | `list[StrategyProfile]` | 列出某所有者的全部策略 |
| `get_prompt` | `strategy_id: str`, `version_id: str`, `task: str = ""`, `evidence_context: str = ""` | `str` | 获取合并后的完整 Prompt |
| `list_templates` | 无 | `list[StrategyTemplateMeta]` | 列出内置模板元数据 |

内部辅助方法：

| 方法 | 说明 |
| --- | --- |
| `_create_version` | 创建首个版本并生成 `strategy_id`，持久化档案 |
| `_must_get_profile` | 强获取档案，缺失抛出 `KeyError` |
| `_must_get_version` | 在档案中强获取版本，缺失抛出 `KeyError` |
| `_replace_version` | 用新版本替换档案中同 ID 版本，返回新档案 |

`_deep_merge_config_delta` 函数：递归合并嵌套字典，用于 `update_strategy` 的配置增量。

---

## 6. Prompt 层

### 6.1 `PromptLayerBuilder`

位置：`src/margin/strategy/prompt.py`

按架构第 15.2 节定义的分层顺序（由外到内）组装投研 Prompt：

1. System Guardrail Prompt
2. Platform Research Prompt
3. Strategy Template Prompt
4. User Custom Prompt
5. Current Task Context
6. Retrieved Evidence（可选）

| 方法 | 参数 | 返回值 | 说明 |
| --- | --- | --- | --- |
| `build_layers` | `config: StrategyConfig`, `*`, `custom_instructions: str \| None = None`, `evidence_context: str = ""`, `task: str = ""` | `tuple[PromptLayer, ...]` | 返回所有 Prompt 层，便于审计与序列化 |
| `build` | 同上 | `str` | 返回合并后的最终 Prompt 字符串，过滤空内容 |
| `_guardrail_prompt` | 无 | `str` | 系统护栏提示：要求引用证据、平衡风险披露、禁止保证收益与直接买卖 |
| `_platform_prompt` | 无 | `str` | 平台研究角色提示 |
| `_template_prompt` | `config: StrategyConfig` | `str` | 将策略配置（horizon、universe、证据要求、风险约束）转换为提示 |
| `_default_task` | `config: StrategyConfig` | `str` | 默认任务描述，要求输出结构化研究信号 |

---

## 7. 仓库

### 7.1 `StrategyRepository`（Protocol）

位置：`src/margin/strategy/repository.py`

`StrategyService` 消费的持久化契约。

| 方法 | 参数 | 返回值 | 说明 |
| --- | --- | --- | --- |
| `add_profile` | `profile: StrategyProfile` | `None` | 持久化新策略档案 |
| `get_profile` | `strategy_id: str` | `StrategyProfile \| None` | 按 ID 查询档案 |
| `list_profiles` | `owner_id: str` | `list[StrategyProfile]` | 列出某所有者的档案 |
| `update_profile` | `profile: StrategyProfile` | `None` | 持久化更新后的档案 |

### 7.2 `MemoryStrategyRepository`

内存实现，用于测试与本地使用。

| 方法 | 说明 |
| --- | --- |
| `add_profile` | 若 `strategy_id` 已存在则抛出 `ValueError` |
| `get_profile` | 从字典读取 |
| `list_profiles` | 按 `owner_id` 过滤 |
| `update_profile` | 若 `strategy_id` 不存在则抛出 `KeyError` |

### 7.3 `SQLAlchemyStrategyRepository`

PostgreSQL 实现。

| 方法 | 说明 |
| --- | --- |
| `add_profile` | 开启事务，插入 `StrategyProfileRow` 及其全部 `StrategyVersionRow`；配置与 Prompt 层序列化为 JSONB |
| `get_profile` | 按 ID 读取并重建 `StrategyProfile` 与 `StrategyVersion`；状态字符串反转为 `StrategyState` |
| `list_profiles` | 按 `owner_id` 查询档案头，再逐个 `get_profile` 重建 |
| `update_profile` | 更新档案头字段；已存在版本更新描述、状态与沙盒结果；新出现版本执行插入 |

---

## 8. FastAPI 接口

位置：`src/margin/api/routes/strategy.py`

路由前缀：`/strategies`

| 方法 | 路径 | 摘要 | 请求 | 响应 |
| --- | --- | --- | --- | --- |
| `GET` | `/templates` | 列出内置策略模板 | 无 | `list[dict[str, str]]`（模板元数据） |
| `POST` | `/` | 从模板创建策略 | `CreateStrategyRequest` | `dict[str, Any]`（策略档案 JSON） |
| `POST` | `/custom` | 从自定义配置创建策略 | `CreateCustomStrategyRequest` | `dict[str, Any]`（策略档案 JSON） |
| `GET` | `/` | 列出某所有者的策略 | 查询参数 `owner_id: str` | `list[dict[str, Any]]` |
| `GET` | `/{strategy_id}` | 获取单个策略档案 | 路径参数 `strategy_id` | `dict[str, Any]` |
| `PUT` | `/{strategy_id}` | 更新策略（创建新版本） | `UpdateStrategyRequest` | `dict[str, Any]` |
| `POST` | `/{strategy_id}/versions/{version_id}/validate` | 校验版本并推进到回测 | 路径参数 | `dict[str, Any]` |
| `POST` | `/{strategy_id}/versions/{version_id}/backtest` | 推进到模拟交易 | 路径参数 | `dict[str, Any]` |
| `POST` | `/{strategy_id}/versions/{version_id}/paper-trade` | 确认模拟交易就绪 | 路径参数 | `dict[str, Any]` |
| `POST` | `/{strategy_id}/versions/{version_id}/activate` | 激活版本 | 路径参数 | `dict[str, Any]` |
| `POST` | `/{strategy_id}/archive` | 归档当前激活版本 | 路径参数 | `dict[str, Any]` |
| `GET` | `/{strategy_id}/versions/{version_id}/prompt` | 获取合并 Prompt | 路径参数 + 查询参数 `task: str` | `PromptResponse` |

### 8.1 v0.2 配置 API

位置：`src/margin/api/routes/strategy_config.py`，前缀 `/api/v1`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET/POST` | `/provider-configs` | 列出安全 Provider 摘要/创建 Provider config version；响应包含 provider category、detected provider label 和 Custom 标记 |
| `PUT` | `/provider-configs/{version_id}/secret` | 加密写入 secret，仅返回 last-four metadata |
| `POST` | `/provider-configs/{version_id}/test` | 使用冻结 config/secret 做真实只读 healthcheck |
| `POST` | `/provider-configs/{version_id}/activate` | 激活 Provider config |
| `GET/POST` | `/universe-configs` | 公司池版本 |
| `POST` | `/universe-configs/{version_id}/activate` | 激活公司池版本 |
| `GET/POST` | `/indicator-views` | 用户可见指标版本 |
| `POST` | `/indicator-views/{version_id}/activate` | 激活指标视图 |
| `GET/POST` | `/quant-feature-sets` | 量化输入特征集版本 |
| `POST` | `/quant-feature-sets/{version_id}/activate` | 激活量化特征集 |
| `GET/POST` | `/quant-strategies` | 量化策略版本 |
| `POST` | `/quant-strategies/{version_id}/activate` | 激活已校准量化策略 |
| `GET/POST` | `/style-prompts` | 用户风格 Prompt 版本 |
| `POST` | `/style-prompts/{version_id}/activate` | 校验系统边界后激活风格 Prompt |
| `GET/POST` | `/research-scopes` | 冻结 Research Scope |
| `POST` | `/research-scopes/{version_id}/activate` | 校验引用并激活 Scope |

所有 v0.2 mutating API 在个人本地模式下不要求 local admin Bearer 或 CSRF，但仍要求 `Idempotency-Key` 以支持幂等重放和审计。Secret Store 默认使用稳定本地 key 加密，生产环境可配置 32-byte/base64 `MARGIN_SECRET_MASTER_KEY` 覆盖。

### 8.2 真实 Provider smoke

真实 smoke 不由单元测试替代：

1. 在前端 Provider Settings 写入 Tushare、Tavily、LLM、Embedding、Rerank 凭据；手工 smoke 脚本可使用显式环境变量，但应用运行路径不再从 `.env` 读取 provider token。
2. 对对应 config version 调用 `POST /api/v1/provider-configs/{id}/test`。
3. Tushare/AKShare/Tavily/LLM/Embedding/Rerank adapter 分别执行现有轻量 `healthcheck()`。
4. 输出只记录 provider、status、latency、error code 和脱敏错误；不得打印 header、token、密文或原始响应。
5. 外部网络、代理、额度或 Provider 端故障记录为真实失败证据，不切换 mock 冒充成功。

请求模型字段：

- `CreateStrategyRequest`：`owner_id`, `template`, `name`, `description`
- `CreateCustomStrategyRequest`：`owner_id`, `config`, `name`, `description`
- `UpdateStrategyRequest`：`config_delta`, `name`, `description`
- `PromptResponse`：`prompt: str`

异常处理：

- `KeyError` → `404 Not Found`
- `ValueError` / `ValidationError` → `400 Bad Request`

依赖注入：`service: StrategyService = Depends(get_strategy_service)`。

---

## 9. 跨模块使用说明

- `models.py` 中的 `utc_now` 与 `ensure_utc` 来自 `src/margin/news/models.py`，保证时间戳统一 UTC。
- `db_models.py` 依赖 `src/margin/storage/base.py` 提供的 SQLAlchemy `Base`。
- API 层通过 `src/margin/api/dependencies.py` 中的 `get_strategy_service` 解析 `StrategyService` 实例。
- data/quant/news/AI run 创建时应保存 `ResearchScopeVersion.version_id` 与 `scope_hash`，后续重试或重启不得重新解析当前 active 配置。
- 投研执行模块（如 `09-holdings_monitoring`、`10-research_execution`）应使用 `StrategyService.get_prompt` 获取最终 Prompt，并使用 `StrategyProfile.active_version_id` 确定当前生效版本。
- 决策输出必须遵守 `DecisionConfig.prohibited_outputs`，其中 `GUARANTEED_RETURN` 与 `DIRECT_BUY_SELL_ORDER` 由 `StrategyValidator.merge_with_guardrails` 强制注入，无法被用户覆盖。
- `PromptLayer` 的 `editable` 标记用于前端区分可编辑层（`user_custom`、`task_context`）与系统只读层。
- 沙盒当前为轻量级占位实现；未来可扩展真实回测、成本估算、数据泄漏扫描等子检查。
