# Margin 功能规格 v0.1 — spec 总索引

本目录存放 Margin v0.1 的 10 个功能模块规格（spec）。每个模块一份 `spec.md`，定义模块目标、输入输出、接口契约、数据模型、依赖、验收标准、风险降级与审计追溯。

模块编号与子任务编号规则见仓库根 `AGENTS.md`。

## 模块清单

| 编号 | 模块 | spec | 设计稿来源 | plan 子任务数 |
|------|------|------|------------|----------------|
| 01 | data_provider 数据 Provider 模块 | `01-data_provider/spec.md` | 产品 §4.1/§4.3.1/§13.2-1；架构 §4/§8.1 | 4 |
| 02 | holdings 持仓模块 | `02-holdings/spec.md` | 产品 §4.8/§8/§13.2-2；架构 §17 | 3 |
| 03 | filing_websearch 公告与 WebSearch 模块 | `03-filing_websearch/spec.md` | 产品 §4.3/§4.3.1/§13.2-3；架构 §6 | 3 |
| 04 | text_indexing 文本索引模块 | `04-text_indexing/spec.md` | 产品 §4.4/§13.2-4；架构 §7 | 3 |
| 05 | rag_evidence RAG 证据模块 | `05-rag_evidence/spec.md` | 产品 §9/§13.2-5；架构 §10 | 3 |
| 06 | multi_agent_research 多 Agent 研究流程模块 | `06-multi_agent_research/spec.md` | 产品 §4.5/§5.2/§13.2-6；架构 §8/§9/§11/§12/§14 | 6 |
| 07 | strategy_config 策略配置模块 | `07-strategy_config/spec.md` | 产品 §6/§13.2-7；架构 §15 | 3 |
| 08 | research_candidate_dashboard 研究候选面板模块 | `08-research_candidate_dashboard/spec.md` | 产品 §7/§9.1/§13.2-8；架构 §16 | 3 |
| 09 | holdings_monitoring 持仓监控模块 | `09-holdings_monitoring/spec.md` | 产品 §5.3/§8/§10/§13.2-9；架构 §17/§19 | 3 |
| 10 | deployment_audit 部署与审计模块 | `10-deployment_audit/spec.md` | 产品 §13.1/§13.2-10；架构 §5/§21/§22/§23/§24/§25 | 4 |

合计 10 个 spec、35 个 plan 子任务。

## 验收标准映射

每个 spec 的 §6「验收标准」对应产品设计 §15「产品验收标准」条目：

| 产品 §15 条目 | 覆盖模块 |
|----------------|----------|
| 1. 本地一键部署 | 10 |
| 2. 可配置数据源/WebSearch/LLM | 01、03、06 |
| 3. 完整晚间工作流 | 06 |
| 4. 研究结论含证据引用 | 04、05、06、08 |
| 5. 创建与版本化自定义策略 | 07 |
| 6. 研究候选面板查看候选与拒绝 | 08 |
| 7. 持仓面板查看盈亏/风险/逻辑状态 | 02、09 |
| 8. 数据异常时停止高置信信号 | 01、05、06、09 |
| 9. 研究信号不可变审计记录 | 06、10 |
| 10. 默认不执行真实交易 | 02、10 |

## 状态

- 所有 spec `status: draft`，待进入实现阶段后转为 `review` → `active`。
- 修改已 `active` 的 spec 应新建版本目录（见 `AGENTS.md` §8 版本迭代流程）。
- 2026-06-19 范围修订：模块 06 与 10 删除 MCP 实施含义；v0.1 仅使用内部 `ToolRegistry`、类型化 Provider Adapter 与工具权限分级，不开发 MCP 或自定义 HTTP 工具。
