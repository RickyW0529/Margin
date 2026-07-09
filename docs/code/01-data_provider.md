# 01-data_provider — 数据接入与质量层

这个模块负责把外部数据变成项目内部可信、可追溯、可按时间点使用的数据。

## 它做什么

- 接入 Tushare / AKShare 等数据源。
- 保存原始拉取结果、参数、抓取时间和来源信息。
- 做字段标准化、schema 校验、主键重复校验、日期校验和质量筛选。
- 发布行情、财务、估值、指数成分、停牌等数据到仓库层。
- 通过 `20260709_0059` 把旧 `public` 数据非破坏式迁移到 `raw_meta`、`source_*`、`vault`、`mart_dw`、`mart`、`app` 分层。
- 提供 20 年数据回补控制面：campaign、endpoint plan、partition、dry-run executor、quality report 和 publish guard；API 默认把 campaign、partition、quality report 和幂等记录写入 `ops.*` / `platform.idempotency_keys`。

## 它怎么跑

```text
Provider 配置
  -> 拉取原始数据
  -> landing/raw 保存
  -> quality gate 判断可用性
  -> raw_meta / source_* / vault
  -> PIT / mart_dw / mart
  -> app serving 层
```

量化、Agent、Dashboard 不应该直接调 Tushare / AKShare，而是读这个模块发布后的数据。
旧 `public` 表暂时保留为兼容层；新开发应优先写入和读取分层仓库。

20 年回补默认从 `2006-01-01` 开始，使用完整年度边界。CLI 入口是：

```bash
python -m margin.cli.backfill init --years 20 --start-date 2006-01-01 --end-date auto
```

当前执行器默认是 dry-run 元数据路径，不直接抓取真实 Provider 数据；真实抓取和 PIT promotion 仍必须通过确定性 data/backfill 工具接入。

## 主要入口

- `src/margin/data/providers/`：Provider adapter。
- `src/margin/data/tushare_query.py`：Tushare 查询封装。
- `src/margin/data/tushare_quality.py`：质量检查。
- `src/margin/data/tushare_warehouse.py`：仓库发布。
- `src/margin/data/requirements.py`：量化所需数据目录和采集策略。
- `src/margin/data/backfill/`：20 年回补 campaign、分区、质量和发布控制面。
- `src/margin/data/backfill/repository.py`：backfill campaign/partition/quality report 的 `ops.*` 持久化边界。
- `src/margin/cli/backfill.py`：回补 CLI。
- `scripts/run_tushare_backfill.py`：数据回填入口。
- `alembic/versions/20260708_0053` 到 `20260709_0059`：Raw/ODS、Data Vault/PIT、Kimball、Mart、App serving 分层迁移。

## 输出给谁

- `11-valuation_discovery` 用它生成公司池和量化特征。
- `06-multi_agent_research` 通过 scoped tools 间接读取分析结果。
- `08-research_candidate_dashboard` 展示由上层 Mart 处理后的结果。
