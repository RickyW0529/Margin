# 11-valuation_discovery — 公司池、量化和 Analysis Mart

这个模块负责把可信数据变成可用的股票候选和分析结果。

## 它做什么

- 生成公司池快照，排除 ST、退市、未来上市和不可交易证券。
- 从 PIT-safe 数据构建量化特征。
- 运行 ML / 量化筛选策略。
- 把量化结果、评分、解释、风险和 lineage 发布到 Analysis Mart。

## 它怎么跑

```text
公司池快照
  -> Quant Feature Mart
  -> ML / 量化策略
  -> Analysis Mart
  -> Agent 复核
  -> Dashboard 推荐
```

它是数据层和 Agent / Dashboard 之间的核心桥梁。上层不要直接读原始财务或行情数据。

## 主要入口

- `src/margin/valuation_discovery/`：公司池、orchestrator、Analysis Mart。
- `src/margin/valuation_discovery/quant/`：量化因子、筛选、ML lifecycle。
- `src/margin/valuation_discovery/quant_adapter.py`：量化结果发布适配。

## 输出给谁

- `06-multi_agent_research` 读取 Analysis Mart 做 AI 复核。
- `08-research_candidate_dashboard` 展示推荐、评分和风险。
- `05-rag_evidence` 通过候选股票范围绑定证据。
