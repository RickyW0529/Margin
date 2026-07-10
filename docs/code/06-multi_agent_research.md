# 06-multi_agent_research — 多 Agent 研究流程

这个模块负责把量化结果、证据、风险和用户问题交给 Agent 处理。

## 它做什么

- `src/margin/agents/` 提供新的三层 Agent 协议和控制面：L1 MainAgent -> L2 Domain ExpertAgent -> L3 WorkerAgent。
- L1 -> L2 和 L2 -> L3 都通过 A2A 1.0 `Message/Task/Artifact` 通信；当前使用可替换的进程内 transport，业务 envelope 不依赖 transport 实现。
- MainAgent 只负责规划、调度和最终复核；Domain ExpertAgent 负责一个业务域内的任务分解；WorkerAgent 只执行具体能力并输出 artifact。
- Main 和 Expert 生成的 `depends_on` 会交给通用 DAG executor；无依赖分支可并行，上游失败会结构化跳过下游。
- AgentCard/WorkerCard 从 `cards/manifests/*.json` 加载；manifest、ExecutorRegistry 和 ToolCatalog 在启动时做工具、runtime、输出契约一致性校验。
- CapabilityToken、DataAccessPolicy、ToolPolicy 控制 Agent 能读什么、能写什么、能调用什么工具。
- ContextPack、DomainContextCapsule、AuditReport 让上下文传递、压缩和最终输出可追溯。
- Context Engineering 已有独立 repository 和 `agent.context_*` 表，ContextPack/fact/omission/capsule/lineage 不再只藏在 artifact payload 里。
- ToolGateway 统一处理工具注册、Capability 绑定、调用预算、幂等、脱敏和审计；LangGraph tool/node 只能通过 ToolGateway wrapper 调用。
- PromptBundle / PromptRegistry / PromptRenderer 管理 v1 系统提示词、变量校验和 render hash；PromptBundle、render history 和 LLM call audit 已有 `prompt.*` 表持久化边界。
- Q&A API 已接入 `AgentRuntimeService`，由 v1 `GlobalPlan -> DomainContextCapsule -> FinalAudit -> FinalUserAnswerArtifact` 路径生成用户回答。
- Q&A 执行链路已改为 `MainAgent prompt plan -> Domain ExpertAgent worker plan -> WorkerAgent execution`；MainAgent 和 ExpertAgent 只看 AgentCard/WorkerCard 做计划、派活和审核，不直接查库、画图或调用工具。
- WorkerCard 的 skill `input_contract` 描述该 worker 需要哪些结构化输入；ExpertAgent 依据契约填充 `step.constraints.worker_inputs`，不在通用 prompt 里硬编码某个问题的字段。
- Q&A runtime 会按 MainAgent 返回的 `GlobalPlan.domain_tasks` DAG 执行全部专家任务，而不是只执行第一个 task；最终回答引用所有已批准的 DomainContextCapsule。
- `DataQuestionWorker` 内部使用固定 LangGraph 工具流完成数据问题：恢复上下文、检查指标 schema、解析证券、查询 PIT 指标、生成图表 artifact，并把工具步骤写入 `worker_activity`。
- `GeneralQnaWorker` 使用 LangGraph 完成 Dashboard 读取、回答生成和 artifact 收口。
- `CodeWorkspaceWorker` 使用动态 LangGraph plan/tool/observe/replan 循环，可通过受限 workspace 工具读取、搜索、原子写文件并运行 allowlist 校验命令。
- 定时股票研究已接入同一套 A2A 分层 runtime；schedule 只提供目标和约束，由 MainAgent 生成动态 `GlobalPlan`，Expert 再规划 LangGraph Worker，固定 `scheduled_l3` 流程已删除。
- 旧 `src/margin/agent_runtime/` 只保留 chat/context/schedule 存储模型、历史 MainAgent 测试和旧 flow loader，不再作为 API 或 worker 编排入口。

## 它怎么跑

```text
用户/定时任务触发
  -> MainAgent 读取 DomainAgentCard 并生成动态 GlobalPlan
  -> A2A message/send 把 DomainTask DAG 派给一个或多个 ExpertAgent
  -> ExpertAgent 根据 WorkerCard 生成 WorkerTask DAG 并通过 A2A 派发
  -> WorkerAgent 在 LangGraph 内规划并仅通过 ToolGateway 使用工具
  -> 产出 ContextPack / DomainContextCapsule / Artifact / Audit
  -> MainAgent 基于已批准 capsule 生成最终回答
```

定时任务现在是 `ScheduledTaskIntent -> MainAgent planning -> ExpertAgent planning/review -> LangGraph Worker -> Main review`，与用户问答共享 A2A、DAG、Capability 和 ToolGateway 边界。

MainAgent 不维护固定路由表。用户或定时任务可以提出任意自然语言目标，MainAgent 根据 DomainAgentCard 的 description、policy、required outputs 选择一个或多个专家，并把用户问题、输出要求和上下文约束写入每个专家任务。专家拿到任务后再根据 WorkerCard 和 skill `input_contract` 自行拆 worker step。

量化线由 `QuantExpertAgent` 负责规划和复查；它下面当前的量化 Worker 可以执行固定的 PIT 特征、模型和 Analysis Mart 发布流程，但 `QuantExpertAgent` 本身不是固定流程。财报/RAG/舆情等工作也由 MainAgent 按目标动态选择对应专家，不再由定时任务代码写死分支。

Agent 不应该直接读 raw/source 表，也不应该绕过 Evidence 和 Analysis Mart。

## 当前安全边界

- 用户 Q&A endpoint 和 worker 定时任务不再直接依赖旧 MainAgent runtime 或旧 ExpertAgent 执行器。
- Q&A service 只通过 v1 MainRuntime 生成 domain task，并把 context pack、domain capsule、domain audit、final audit、final answer 都写成 artifact。
- Q&A service 同时把 ContextPack、DomainContextCapsule 和 lineage edge 写入结构化 ContextRepository。
- scheduled runner 把 schedule intent 交给 MainAgent 规划，写入 `scheduled_global_plan`、`main_agent_plan`、`plan_validation` 与 `valuation_refresh` artifact。
- `CodeExecutionExpertAgent` 只有在 Code Worker、workspace tools 和 capability 同时可执行时才会暴露给 planner；workspace 根目录由 `MARGIN_AGENT_WORKSPACE_ROOT` 显式配置。
- 普通 `/agent-runs/user-qna` 永远不授予 workspace capability；代码修改只通过需要本地管理员鉴权的 `/agent-runs/workspace` 入口，并且还受 `MARGIN_AGENT_CODE_TOOLS_ENABLED` 总开关控制。
- ContextPack capability 同时绑定 pack ID 和去除 hop 路由字段后的内容 hash；Worker/Expert 返回的 artifact、capsule、audit 还会校验身份、payload hash 和审计记录。
- 当前 A2A transport 是可信进程内总线。替换成网络 transport 时，`source_agent` 必须来自 mTLS/JWT/service identity 等认证主体，不能信任请求声明的字符串。
- `workspace.run_command` 的 argv allowlist 不是操作系统沙箱。生产启用代码执行前必须放入禁网、非特权、资源受限且只挂载 workspace 的一次性容器或 microVM；当前管理员开关只降低暴露面，不提供宿主隔离。
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
- `src/margin/agents/a2a/`：A2A 1.0 类型、无损 JSON DataPart envelope、同步 client 和可替换 transport。
- `src/margin/agents/cards/manifests/`：用户问答与定时任务的版本化 Agent 能力清单。
- `src/margin/agents/prompts/`：v1 PromptBundle、schema 和系统提示词。
- `src/margin/agents/prompts/repository.py`：PromptBundle、prompt render history、LLM call audit 的正式持久化边界。
- `src/margin/agents/prompts/db_models.py`：`prompt.prompt_templates`、`prompt.prompt_bundles`、`prompt.prompt_render_history`、`prompt.llm_call_audits` ORM。
- `src/margin/agents/runtime/service.py`：用户 Q&A v1 应用服务。
- `src/margin/agents/runtime/expert_runtime.py`：Domain ExpertAgent 的 WorkerCard 驱动规划器。
- `src/margin/agents/runtime/hierarchy.py`：Main/Expert/Worker A2A endpoint、两层派发和 review 边界。
- `src/margin/agents/runtime/dag.py`：planner 生成 DAG 的校验、并行执行和失败传播。
- `src/margin/agents/runtime/langgraph_worker.py`：通用动态 Worker plan/tool/observe/replan 循环。
- `src/margin/agents/runtime/scheduled.py`：定时股票研究 v1 runner。
- `src/margin/agents/runtime/scheduled_workers.py`：manifest 绑定的定时 LangGraph Worker 与工具实现。
- `src/margin/agents/workers/data_question_worker.py`：数据问答 worker，内部固定 LangGraph 工具流。
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
