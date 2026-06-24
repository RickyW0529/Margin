# 11 valuation_discovery — 公司池与估值发现模块

## 模块概述

`src/margin/valuation_discovery/` 实现 v0.2/v0.3 的公司池、量化筛选、新闻目标选择、行业估值、置信度校准、有效结论指针和刷新编排。模块只消费冻结的数据仓库输入和策略 scope，不直接调用 AKShare、Tushare、Tavily、LLM 或交易接口。

v0.3 中，公司池来源切到数据层 materialized company pool：`SQLAlchemyScopeBindingProvider` 对 `ALL_A` / `ALL_A_NON_ST` scope 优先读取最新 `company_pool_snapshots`，量化输入不再使用静态 universe membership。公司池排除 ST、`退市*` 名称、未来上市和已退市证券。

当前量化服务支持版本化手工池策略：当 `QuantInputSnapshot.quant_feature_set.metadata.quant_strategy.thresholds.presets` 提供因子权重时，`QuantService` 使用 `manual_all_a_score` 作为真实 `QuantResult.final_score`、rank 和 screening status 的输入。`theme_hotness` 是确认后的题材/行业热点加分项，来自 PIT 安全 cross-section 中的 `theme_hot_score`、`theme_member_confidence`、`theme_signal_confirmed` 字段；未确认或非成员公司不加分。无版本化策略 metadata 的兼容路径仍使用旧五组分 `FactorScorer.combine()`。

## 数据模型与迁移

| 表 | 说明 |
|----|------|
| `universe_definitions` / `universe_versions` / `universe_memberships` / `universe_snapshots` | 内置和未来自定义公司池，支持 valid time + system time。 |
| `company_pool_snapshots` / `company_pool_members` | v0.3 数据层物化的非 ST/非退市全 A 公司池快照，供 `ALL_A_NON_ST` scope 直接消费。 |
| `quant_input_snapshots` / `quant_input_snapshot_facts` | 量化唯一输入契约，记录 scope、universe、指标集合、事实 lineage、PIT/freshness/quality 标记。 |
| `quant_screen_runs` / `quant_screen_results` / `quant_factor_values` | 量化运行、单票结果、分组因子值、rank、原因摘要。 |
| `valuation_assessments` / `confidence_components` / `effective_assessment_pointers` | 估值结论、置信度组成和当前有效结论指针。 |
| `valuation_refresh_runs` / `valuation_refresh_steps` / `research_refresh_events` / `research_context_snapshots` | 估值发现刷新、步骤、事件和研究上下文快照。 |

相关迁移：`20260622_0021` 至 `20260622_0024`，以及 v0.3 公司池/源系统/量化历史索引迁移 `20260623_0036` 至 `20260624_0041`。

## 关键代码

| 文件 | 主要对象 | 说明 |
|------|----------|------|
| `models.py` | `UniverseMembership`, `QuantInputSnapshot`, `QuantRun`, `QuantResult`, `NewsTarget`, `EffectiveAssessmentPointer` | 不可变领域模型。 |
| `universe.py` | `UniverseResolver` | 按业务时间和系统时间解析 `CSI300`、`CSI500`、`ALL_A`。 |
| `scope.py` / `quant_input.py` | `ScopeBinding`, `QuantInputSnapshotBuilder` | 冻结用户可见指标和底层量化指标，构建 PIT 输入快照。 |
| `quant_adapter.py` | `SQLAlchemyScopeBindingProvider`, `WarehouseFactAdapter`, `build_cross_section_loader`, `QuantAdapter` | 连接策略 scope、数据层公司池、warehouse canonical/fact history 和量化服务；历史行情读取按每证券/指标最近 260 个 PIT 点限流，避免加载两年全量事实。 |
| `quant/filters.py` | `HardFilterEngine` | ST、停牌、上市时间、流动性、财务缺失、亏损、负债、商誉、现金流、审计意见过滤。 |
| `quant/scoring.py` / `quant/service.py` | `FactorScorer`, `QuantService` | 行业内标准化、五因子加权、版本化手工池最终分、状态/guardrail、rank 和结果持久化。 |
| `quant/manual_all_a.py` / `quant/theme_tilt.py` | `score_manual_all_a`, `score_theme_components`, `confirmation_states` | 手工三池量化分、确认后的题材/行业热点加分、题材热度进入/退出确认。 |
| `news_targets.py` | `NewsTargetSelector` | PASS 全量进入新闻目标；允许的 NEAR_THRESHOLD 可进入；不做 top-N 裁剪。 |
| `valuation.py` | `IndustryValuationRegistry` | 银行、保险、周期资源、消费/制造、成长/科技、公用事业估值模型族。 |
| `confidence.py` | `ConfidenceCalibrator` | 确定性置信度校准，不接受 LLM 置信度覆盖。 |
| `assessments.py` | `EffectiveAssessmentService` | deferred/abstain 保留旧结论，invalidate/update 指向新结论。 |
| `orchestrator.py` / `service.py` | `ValuationDiscoveryOrchestrator`, `ValuationDiscoveryService` | 12 步刷新编排、幂等启动、失败/等待/跳过语义。 |

## FastAPI 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/valuation-discovery/refreshes` | 启动估值发现刷新，要求本地 admin、CSRF 和 `Idempotency-Key`，返回 `202` 与 `run_id`。默认未配置 service 时 fail-closed 为 `503`。 |

## Smoke

```bash
python scripts/smoke_valuation_discovery_p0.py \
  --scope-version-id scope-active \
  --decision-at 2026-06-22T00:00:00Z \
  --cross-section-csv /path/to/real_warehouse_cross_section.csv

python scripts/smoke_valuation_discovery_p1.py \
  --scope-version-id scope-active \
  --decision-at 2026-06-22T00:00:00Z \
  --api-url http://127.0.0.1:8000
```

P0/P1 smoke 不生成假数据。缺少真实快照、真实截面、API 或密钥时输出明确 `external_blocker`。

## v0.3 真实量化输出

最新 Tushare 数据链路验收 run：

- 公司池快照：`cps_29518c0fec90836c57609b6f1f24`
- 量化 run：`qr_df48cd92fdf1424d`
- 决策时间：`2026-06-22T16:00:00Z`
- 输入公司数：5304
- `QuantInputSnapshot`：`qis_432bf2fba3e741cb`，`fact_count=76462`，`missing_required=[]`，`data_status=ok`
- 结果分布：3 `pass`，54 `near_threshold`，447 `watchlist`，4800 `reject`；其中 4 条 `data_status=insufficient`，3495 条需 review
- 行业/题材热点最终分接线已通过内存仓库服务级回归；下列实库分布来自接线前的数据链路验收 run，重新跑实库 quant 后需要刷新本节统计。

Top pass：

| rank | code | name | final | quality | value | growth | momentum | risk | status |
|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | 002416.SZ | 爱施德 | 92.50 | 100.00 | 70.00 | 100.00 | 100.00 | 100.00 | pass |
| 2 | 603223.SH | 恒通股份 | 90.50 | 100.00 | 70.00 | 100.00 | 100.00 | 80.00 | pass |
| 3 | 000592.SZ | 平潭发展 | 80.25 | 100.00 | 25.00 | 100.00 | 100.00 | 90.00 | pass |

## 跨模块依赖

- 读取：数据仓库 canonical/fact lineage、策略 scope、module 10 orchestration。
- 输出：量化候选、NewsTarget、估值结论、effective pointer、Dashboard/API 可读 run 状态。
- 边界：量化层不调用外部 Provider；新闻、索引、RAG 和 AI 由后续模块服务承接。
