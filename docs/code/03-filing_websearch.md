# 03-filing_websearch — 公告、新闻和 WebSearch

这个模块负责补充文本资料，让股票推荐不只依赖量化分数。

## 它做什么

- 根据候选股票生成新闻、公告和 WebSearch 目标。
- 拉取官方公告、新闻、网页搜索结果和原文快照。
- 做去重、转载链识别、robots / 合规检查和来源记录。
- 给后续文本索引和证据系统提供可追溯材料。

## 它怎么跑

```text
量化候选股票
  -> 生成新闻/公告目标
  -> Provider 拉取资料
  -> 保存原文和快照
  -> 去重和合规判断
  -> 交给文本索引
```

它只负责“把材料找回来并保存好”，不直接做投资结论。

## 主要入口

- `src/margin/news/`：新闻、公告、WebSearch、去重和目标队列。
- `src/margin/sql/news_queries.py`：新闻任务和查询。
- API / Worker 会在刷新流程中触发该模块。

## 输出给谁

- `04-text_indexing` 解析和向量化这些文本。
- `05-rag_evidence` 从这些文本中构建证据。
- `06-multi_agent_research` 用证据辅助 AI 复核。
