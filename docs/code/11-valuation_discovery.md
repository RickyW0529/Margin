# 11 valuation_discovery — 公司池与估值发现模块

## 模块概述

`src/margin/valuation_discovery/` 实现 v0.2 的公司池、量化筛选、新闻目标选择、行业估值、置信度校准、有效结论指针和刷新编排。模块只消费冻结的数据仓库输入和策略 scope，不直接调用 AKShare、Tushare、Tavily、LLM 或交易接口。

## 数据模型与迁移

| 表 | 说明 |
|----|------|
| `universe_definitions` / `universe_versions` / `universe_memberships` / `universe_snapshots` | 内置和未来自定义公司池，支持 valid time + system time。 |
| `quant_input_snapshots` / `quant_input_snapshot_facts` | 量化唯一输入契约，记录 scope、universe、指标集合、事实 lineage、PIT/freshness/quality 标记。 |
| `quant_screen_runs` / `quant_screen_results` / `quant_factor_values` | 量化运行、单票结果、分组因子值、rank、原因摘要。 |
| `valuation_assessments` / `confidence_components` / `effective_assessment_pointers` | 估值结论、置信度组成和当前有效结论指针。 |
| `valuation_refresh_runs` / `valuation_refresh_steps` / `research_refresh_events` / `research_context_snapshots` | 估值发现刷新、步骤、事件和研究上下文快照。 |

新增迁移：`20260622_0021` 至 `20260622_0024`。

## 关键代码

| 文件 | 主要对象 | 说明 |
|------|----------|------|
| `models.py` | `UniverseMembership`, `QuantInputSnapshot`, `QuantRun`, `QuantResult`, `NewsTarget`, `EffectiveAssessmentPointer` | 不可变领域模型。 |
| `universe.py` | `UniverseResolver` | 按业务时间和系统时间解析 `CSI300`、`CSI500`、`ALL_A`。 |
| `scope.py` / `quant_input.py` | `ScopeBinding`, `QuantInputSnapshotBuilder` | 冻结用户可见指标和底层量化指标，构建 PIT 输入快照。 |
| `quant/filters.py` | `HardFilterEngine` | ST、停牌、上市时间、流动性、财务缺失、亏损、负债、商誉、现金流、审计意见过滤。 |
| `quant/scoring.py` / `quant/service.py` | `FactorScorer`, `QuantService` | 行业内标准化、五因子加权、状态/guardrail、rank 和结果持久化。 |
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

## 跨模块依赖

- 读取：数据仓库 canonical/fact lineage、策略 scope、module 10 orchestration。
- 输出：量化候选、NewsTarget、估值结论、effective pointer、Dashboard/API 可读 run 状态。
- 边界：量化层不调用外部 Provider；新闻、索引、RAG 和 AI 由后续模块服务承接。
