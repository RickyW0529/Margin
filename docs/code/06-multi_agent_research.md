# 06-multi_agent_research — 多 Agent 研究流程

这个模块负责把量化结果、证据、风险和用户问题交给 Agent 处理。

## 它做什么

- `src/margin/agents/` 提供新的三层 Agent 协议和控制面：L1 MainAgent -> L2 Domain ExpertAgent -> L3 WorkerAgent。
- MainAgent 只负责规划、调度和最终复核；Domain ExpertAgent 负责一个业务域内的任务分解；WorkerAgent 只执行具体能力并输出 artifact。
- CapabilityToken、DataAccessPolicy、ToolPolicy 控制 Agent 能读什么、能写什么、能调用什么工具。
- ContextPack、DomainContextCapsule、AuditReport 让上下文传递、压缩和最终输出可追溯。
- ToolGateway 统一处理工具注册、权限、幂等、脱敏和审计；LangChain 工具只能通过 ToolGateway wrapper 调用。
- PromptBundle / PromptRegistry / PromptRenderer 管理 v1 系统提示词、变量校验和 render hash。
- 旧 `src/margin/agent_runtime/` 保留为兼容执行入口，继续服务 API、worker 和 Dashboard。

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

- Q&A planner 只能看到已经注册 executor 的 WorkerAgent card。
- `CodeSandboxAgent` 默认不会暴露给 planner，只有注册可执行 executor 后才可见。
- Q&A 执行状态按 `step_id` 记录，避免同一 Agent 多个步骤互相覆盖。
- API 返回 artifact detail 时默认使用 safe view，对密钥、token、原始长文本等敏感字段做脱敏和裁剪。
- API 提供 run trace、context graph、tool-call audit 的 safe view，默认只暴露元数据、hash 和脱敏内容。
- MainAgent final review 会检查 artifact 是否存在、payload hash、预期 producer/type，以及 evidence/source 引用边界，并写入 `final_audit_report` artifact。

## 主要入口

- `src/margin/agents/`：三层 Agent 协议、card、context、capability、executor registry 和审计工具。
- `src/margin/agents/tools/`：ToolGateway、ToolCatalog、authz、audit 和 scoped tools。
- `src/margin/agents/prompts/`：v1 PromptBundle、schema 和系统提示词。
- `src/margin/agents/domains/`、`src/margin/agents/workers/`：BackfillExpertAgent 与回填 worker skeleton。
- `src/margin/agent_runtime/`：兼容现有 API/worker/Dashboard 的 MainAgent runtime、schedule、context store。
- `src/margin/research/`：研究流程、工具和快照。
- `src/margin/prompts/`：Prompt 模板和版本。
- `src/margin/api/routes/agent_runtime.py`：Agent API。
- `src/margin/api/routes/tool_audit.py`：ToolGateway 审计 safe view。

## 输出给谁

- `08-research_candidate_dashboard` 展示 Agent 任务状态和调整后的推荐。
- 首页问答读取 Agent 输出和证据引用。
