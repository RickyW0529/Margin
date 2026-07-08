# 08-research_candidate_dashboard — 用户界面和推荐看板

这个模块负责把研究结果展示给用户。

## 它做什么

- 首页问答：让用户追问推荐理由和风险。
- Dashboard：展示今日推荐、评分、证据、风险和详情页。
- 设置页：配置 Provider、研究范围、数据策略和自动研究计划。
- Agent 进度：展示今日研究任务跑到哪一步、卡在哪里。

## 它怎么跑

```text
Analysis Mart / Agent 输出
  -> Dashboard API 聚合
  -> 前端列表和详情页展示
  -> 用户追问时调用 MainAgent Q&A
```

前端不直接读 raw/source 数据，只展示 API 聚合后的研究结果。

## 主要入口

- `src/margin/dashboard/`：Dashboard 聚合模型和 repository。
- `src/margin/api/routes/dashboard.py`：Dashboard API。
- `web/app/`：Next.js 页面。
- `web/components/`：推荐列表、详情、证据、设置和进度组件。

## 输出给谁

- 给用户看推荐结论。
- 给用户看证据、风险和 Agent 调整原因。
- 给用户提供启动今日研究和自动研究计划的入口。
