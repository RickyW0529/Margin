# 06-multi_agent_research — 多 Agent 研究流程

这个模块负责把量化结果、证据、风险和用户问题交给 Agent 处理。

## 它做什么

- MainAgent 负责规划、调度和最终复核。
- ExpertAgent 负责数据检查、量化分析、新闻获取、股票分析、问答等任务。
- Guardrail 控制 Agent 能读什么、能写什么、什么时候失败。
- Context Store 保存 Agent 运行过程和产物引用。

## 它怎么跑

```text
用户/定时任务触发
  -> MainAgent 生成计划
  -> ExpertAgent 分步执行
  -> 读取 Analysis Mart 和 Evidence
  -> 写入复核结果和 Dashboard 投影
  -> MainAgent 最终检查
```

Agent 不应该直接读 raw/source 表，也不应该绕过 Evidence 和 Analysis Mart。

## 主要入口

- `src/margin/agent_runtime/`：MainAgent、ExpertAgent、guardrail、schedule、context store。
- `src/margin/research/`：研究流程、工具和快照。
- `src/margin/prompts/`：Prompt 模板和版本。
- `src/margin/api/routes/agent_runtime.py`：Agent API。

## 输出给谁

- `08-research_candidate_dashboard` 展示 Agent 任务状态和调整后的推荐。
- 首页问答读取 Agent 输出和证据引用。
