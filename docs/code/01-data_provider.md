# 01-data_provider — 数据接入与质量层

这个模块负责把外部数据变成项目内部可信、可追溯、可按时间点使用的数据。

## 它做什么

- 接入 Tushare / AKShare 等数据源。
- 保存原始拉取结果、参数、抓取时间和来源信息。
- 做字段标准化、schema 校验、主键重复校验、日期校验和质量筛选。
- 发布行情、财务、估值、指数成分、停牌等数据到仓库层。

## 它怎么跑

```text
Provider 配置
  -> 拉取原始数据
  -> landing/raw 保存
  -> quality gate 判断可用性
  -> warehouse publisher 发布
  -> PIT / canonical 层供量化读取
```

量化、Agent、Dashboard 不应该直接调 Tushare / AKShare，而是读这个模块发布后的数据。

## 主要入口

- `src/margin/data/providers/`：Provider adapter。
- `src/margin/data/tushare_query.py`：Tushare 查询封装。
- `src/margin/data/tushare_quality.py`：质量检查。
- `src/margin/data/tushare_warehouse.py`：仓库发布。
- `src/margin/data/requirements.py`：量化所需数据目录和采集策略。
- `scripts/run_tushare_backfill.py`：数据回填入口。

## 输出给谁

- `11-valuation_discovery` 用它生成公司池和量化特征。
- `06-multi_agent_research` 通过 scoped tools 间接读取分析结果。
- `08-research_candidate_dashboard` 展示由上层 Mart 处理后的结果。
