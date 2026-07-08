# 04-text_indexing — 文本解析和向量索引

这个模块负责把新闻、公告、研报类文本变成 RAG 可以检索的结构化索引。

## 它做什么

- 解析 PDF、HTML、CSV、JSON、纯文本等内容。
- 保留页码、表格、quote span、URL、hash 等定位信息。
- 把长文本切成稳定 chunk。
- 生成 embedding，并把向量和 chunk 关系写入数据库。

## 它怎么跑

```text
原文快照
  -> parser 解析结构
  -> chunker 分块
  -> embedding provider 生成向量
  -> 写入 chunk / vector / index audit
  -> 供 RAG 检索
```

这个模块不判断股票好坏，只负责让文本“能被找到、能被定位、能复放”。

## 主要入口

- `src/margin/vector/`：parser、chunker、embedding、repository、retrieval。
- `src/margin/news/structured_parser.py`：新闻侧结构化解析。

## 输出给谁

- `05-rag_evidence` 用它检索相关证据。
- `06-multi_agent_research` 通过 RAG 工具读取证据片段。
