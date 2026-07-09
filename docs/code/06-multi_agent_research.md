# 06-multi_agent_research — 多 Agent 研究流程

这个模块负责把量化结果、证据、风险和用户问题交给 Agent 处理。

## 它做什么

- `src/margin/agents/` 提供新的三层 Agent 协议和控制面：L1 MainAgent -> L2 Domain ExpertAgent -> L3 WorkerAgent。
- MainAgent 只负责规划、调度和最终复核；Domain ExpertAgent 负责一个业务域内的任务分解；WorkerAgent 只执行具体能力并输出 artifact。
- CapabilityToken、DataAccessPolicy、ToolPolicy 控制 Agent 能读什么、能写什么、能调用什么工具。
- ContextPack、DomainContextCapsule、AuditReport 让上下文传递、压缩和最终输出可追溯。
- Context Engineering 已有独立 repository 和 `agent.context_*` 表，ContextPack/fact/omission/capsule/lineage 不再只藏在 artifact payload 里。
- ToolGateway 统一处理工具注册、权限、幂等、脱敏和审计；LangGraph tool/node 只能通过 ToolGateway wrapper 调用。
- PromptBundle / PromptRegistry / PromptRenderer 管理 v1 系统提示词、变量校验和 render hash；PromptBundle、render history 和 LLM call audit 已有 `prompt.*` 表持久化边界。
- Q&A API 已接入 `AgentRuntimeService`，由 v1 `GlobalPlan -> DomainContextCapsule -> FinalAudit -> FinalUserAnswerArtifact` 路径生成用户回答。
- 定时股票研究已接入 `ScheduledAgentRuntimeRunner`，由 v1 scheduled global plan 触发 valuation refresh。
- 旧 `src/margin/agent_runtime/` 只保留 chat/context/schedule 存储模型、历史 MainAgent 测试和旧 flow loader，不再作为 API 或 worker 编排入口。

## 它怎么跑

```text
用户/定时任务触发
  -> MainAgent 生成计划
  -> 数据检查
  -> 量化分支 + 财报/RAG 分支
  -> 融合研究
  -> 写入 Dashboard 投影
  -> MainAgent 最终检查
```

量化分支只读结构化 PIT 数据和 Mart，不做 WebSearch。财报/RAG 分支先检查资料覆盖，缺资料或过期才触发资料刷新；舆情线暂时使用 WebSearch 做增量验证。

Agent 不应该直接读 raw/source 表，也不应该绕过 Evidence 和 Analysis Mart。

## 当前安全边界

- 用户 Q&A endpoint 和 worker 定时任务不再直接依赖旧 MainAgent runtime 或旧 ExpertAgent 执行器。
- Q&A service 只通过 v1 MainRuntime 生成 domain task，并把 context pack、domain capsule、domain audit、final audit、final answer 都写成 artifact。
- Q&A service 同时把 ContextPack、DomainContextCapsule 和 lineage edge 写入结构化 ContextRepository。
- scheduled runner 把固定 flow 映射为 v1 DomainTask，并写入 `scheduled_global_plan` 与 `valuation_refresh` artifact。
- `CodeSandboxAgent` 默认不会暴露给 planner，只有注册可执行 executor 后才可见。
- Q&A 执行状态按 `step_id` 记录，避免同一 Agent 多个步骤互相覆盖。
- API 返回 artifact detail 时默认使用 safe view，对密钥、token、原始长文本等敏感字段做脱敏和裁剪。
- API 提供 `context-packs/{id}`、`runs/{id}/context-graph`、`artifacts/{id}/safe` 的 safe view，默认只暴露结构化上下文、元数据、hash 和脱敏内容。
- ToolGateway 审计默认写入 `tool.tool_calls` 与 `tool.tool_results`，API 只返回 redacted input/output 和 hash。
- Prompt render history 与 LLM call audit 默认只保存 hash、模型、token、状态和时间，不保存 prompt 原文或模型响应 payload。
- MainAgent final review 会检查 artifact 是否存在、payload hash、预期 producer/type，以及 evidence/source 引用边界，并写入 `final_audit_report` artifact。

## 主要入口

- `src/margin/agents/`：三层 Agent 协议、card、context、capability、runtime service、executor registry 和审计工具。
- `src/margin/agents/context/repository.py`：ContextPack、ContextFact、ContextOmission、DomainContextCapsule 和 lineage edge 的正式持久化边界。
- `src/margin/agents/context/db_models.py`：`agent.context_packs`、`agent.context_facts`、`agent.context_omissions`、`agent.domain_context_capsules`、`agent.artifact_lineage_edges` ORM。
- `src/margin/agents/tools/`：ToolGateway、ToolCatalog、authz、audit 和 scoped tools。
- `src/margin/agents/tools/langgraph_adapter.py`：LangGraph-facing ToolGateway wrapper。
- `src/margin/agents/prompts/`：v1 PromptBundle、schema 和系统提示词。
- `src/margin/agents/prompts/repository.py`：PromptBundle、prompt render history、LLM call audit 的正式持久化边界。
- `src/margin/agents/prompts/db_models.py`：`prompt.prompt_templates`、`prompt.prompt_bundles`、`prompt.prompt_render_history`、`prompt.llm_call_audits` ORM。
- `src/margin/agents/runtime/service.py`：用户 Q&A v1 应用服务。
- `src/margin/agents/runtime/scheduled.py`：定时股票研究 v1 runner。
- `src/margin/agents/workers/dashboard_publisher_worker.py`：发布 Agent 调整后的 Dashboard projection。
- `src/margin/agents/domains/`、`src/margin/agents/workers/`：BackfillExpertAgent 与回填 worker skeleton。
- `src/margin/agent_runtime/`：历史 chat/context/schedule 存储模型和旧 flow loader。
- `src/margin/research/`：研究流程、工具和快照。
- `src/margin/prompts/`：Prompt 模板和版本。
- `src/margin/api/routes/agent_runtime.py`：Agent API。
- `src/margin/api/routes/context.py`：ContextPack、安全 artifact 和 context graph 读取 API。
- `src/margin/api/routes/tool_audit.py`：ToolGateway 审计 safe view。

## 输出给谁

- `08-research_candidate_dashboard` 展示 Agent 任务状态和调整后的推荐。
- 首页问答读取 Agent 输出和证据引用。
