---
module_id: 07-strategy_config
product_version: v0.1
doc_version: v0.1
source_refs: [产品设计 §6, §13.2-7; 架构设计 §15, §26-Phase5]
status: draft
---

# 07 策略配置模块 — 功能规格

## 1. 模块目标

让用户自定义投资逻辑而非接受统一算法：配置股票池、行业偏好、持有周期、风险容忍度、估值方法、因子权重、新闻来源、模型供应商、自定义 Prompt、研究信号门槛、失效规则、组合限制与报告风格。提供策略模板、自定义 Prompt 分层、策略版本管理与策略沙箱。

## 2. 输入 / 输出

- **输入**：用户策略编辑、预置策略模板、安全规则（系统 Guardrail）。
- **触发**：用户创建/修改策略、启用策略、晚间研究运行加载 Active 策略。
- **输出**：策略版本（含 Schema 校验、Prompt 分层、约束）、策略状态（Draft/Validating/Backtesting/PaperTrading/Active/Archived/Suspended）。
- **消费方**：06-multi_agent_research（加载策略/Prompt/约束驱动研究）、08-research_candidate_dashboard（策略版本展示）。

## 3. 接口契约

策略配置流程（架构 §15）：策略编辑器 → Schema 校验 → 安全规则合并 → 生成策略版本 → 离线回测 → 模拟运行 → 用户启用 → Active / Draft/Archived。

策略组成（架构 §15.1）：Universe、Quant factors、Valuation、Quality、Catalyst、News source、AI Prompt、Evidence requirements、Horizon、Risk limits、Portfolio constraints、Decision thresholds、Output template。

策略配置结构（产品 §6.2）含 `universe`、`horizon`、`valuation`、`quality`、`risk`、`ai`（provider/model/websearch_provider/system_prompt_template/custom_instructions）、`evidence`（required_levels/min_evidence_count）、`decision`（research_states/position_review_states/prohibited_outputs）。

## 4. 数据模型

预置策略模板（产品 §6.1）：价值质量、低估修复、高股息、成长合理估值、周期反转、用户完全自定义。

Prompt 分层（架构 §15.2）：

```text
System Guardrail Prompt
    + Platform Research Prompt
    + Strategy Template Prompt
    + User Custom Prompt
    + Current Task Context
    + Retrieved Evidence
```

用户自定义 Prompt 可编辑项（产品 §6.3）：研究目标、风格偏好、重点关注指标、必须排除的公司类型、允许使用的信息源、输出风格、风险偏好、反方审查强度。用户 Prompt 不得覆盖：证据引用要求、数据时点限制、风险披露、结构化输出 Schema、禁止收益承诺、禁止自动下单、系统安全策略。

策略版本状态机（产品 §6.4）：Draft → Validating →（Invalid / Backtesting）→ PaperTrading → Active →（Archived / Suspended）。

核心实体（架构 §5.3）：`STRATEGY_PROFILE` 1→N `STRATEGY_VERSION` 1→N `RESEARCH_RUN`。

## 5. 与其他模块依赖

- **上游**：01-data_provider（universe/因子定义引用数据源）、用户编辑。
- **下游**：06-multi_agent_research（策略版本驱动研究）、08-research_candidate_dashboard（策略版本展示与过滤）。
- **规避循环**：策略不消费研究信号；回测结果只影响策略状态，不反向改写已发布研究信号。

## 6. 验收标准

对应产品设计 §15：

- 条目 5：用户可创建和版本化自定义策略；
- 条目 1：用户可在本地完成一键部署后配置策略。

## 7. 风险与降级

对应架构 §25：

- 策略错误 → 回滚上一版本（架构 §25）；
- 数据或风险异常 → Active → Suspended（产品 §6.4）；
- 配置校验失败 → Validating → Invalid，拒绝启用。

## 8. 审计追溯

- `source_refs` 指向产品设计 §6、架构设计 §15 / §26 Phase5；
- 每次策略修改生成新版本，`strategy_version_id` 落库不可篡改；
- 策略沙箱（架构 §15.3）记录配置校验、样例运行、历史回测、数据泄漏检查、交易成本测试、报告预览结果。
