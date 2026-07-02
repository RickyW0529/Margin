# 11 valuation_discovery — 公司池与估值发现模块

## 模块概述

`src/margin/valuation_discovery/` 实现 v0.2/v0.3 的公司池、量化筛选、第四层 Quant Feature Mart / Analysis Mart、新闻目标选择、行业估值、置信度校准、有效结论指针和刷新编排。模块只消费冻结的数据仓库输入和策略 scope，不直接调用 AKShare、Tushare、Tavily、LLM 或交易接口。

v0.3 中，公司池来源切到数据层 materialized company pool：`SQLAlchemyScopeBindingProvider` 对 `ALL_A` / `ALL_A_NON_ST` scope 优先读取最新 `company_pool_snapshots`，量化输入不再使用静态 universe membership。公司池排除 ST、`退市*` 名称、未来上市和已退市证券。指数池 `CSI300` / `CSI500` 由策略配置层从 Tushare `index_weight` 最新成分生成 `UniverseDefinitionVersion.member_security_ids`，用户切换公司池后，`scope-current` 会滚动到对应 universe version，量化输入按该成员集合构建。

当前量化服务支持版本化手工池策略：当 `QuantInputSnapshot.quant_feature_set.metadata.quant_strategy.thresholds.presets` 提供因子权重时，`QuantService` 使用 `manual_all_a_score` 作为真实 `QuantResult.final_score`、rank 和 screening status 的输入。`theme_hotness` 是确认后的题材/行业热点加分项，来自 PIT 安全 cross-section 中的 `theme_hot_score`、`theme_member_confidence`、`theme_signal_confirmed` 字段；未确认或非成员公司不加分。无版本化策略 metadata 的兼容路径仍使用旧五组分 `FactorScorer.combine()`。

v0.3 已新增第四层 Mart：第三层唯一化数据先由 ETL 管道物化为 `quant_feature_snapshots` / `quant_feature_rows`，量化层只读第四层特征快照；量化结果再通过 ETL 管道发布为 `analysis_snapshots`、`analysis_metrics`、`analysis_findings` 和 `analysis_evidence_links`。这一层面向 Quant、Dashboard 与 LangGraph scoped read tools，保存 AI 可直接读取的结构化指标、主要发现、质量标记、输入/结果 hash 和 lineage，避免 AI 每次自行从第三层重算指标。

## 数据模型与迁移

| 表 | 说明 |
|----|------|
| `company_pool_snapshots` / `company_pool_members` | v0.3 数据层物化的非 ST/非退市全 A 公司池快照，供 `ALL_A_NON_ST` scope 直接消费。 |
| `quant_input_snapshots` / `quant_input_snapshot_facts` | 量化唯一输入契约，记录 scope、universe、指标集合、第四层 `feature_snapshot_id`、事实 lineage、PIT/freshness/quality 标记。 |
| `quant_feature_snapshots` | 第四层量化特征快照，按 scope/universe/decision/trading date 保存第三层 ETL 输入 hash、特征列、lineage summary、质量标记和行数。 |
| `quant_feature_rows` | 第四层逐证券量化特征行，保存量化可直接读取的字段、source refs、ST/停牌等行级质量标记。 |
| `quant_screen_runs` / `quant_screen_results` / `quant_factor_values` | 量化运行、单票结果、分组因子值、rank、原因摘要。 |
| `analysis_snapshots` | 第四层单证券分析快照，绑定 security/scope/decision time、quant run/result、QuantInput、策略版本、输入 hash、结果 hash、摘要和质量标记。 |
| `analysis_metrics` | 第四层结构化指标，保存最终分、五组因子分、rank、分位、数据质量和 review 标记等 AI/Dashboard 直接消费字段。 |
| `analysis_findings` | 第四层可读发现，保存筛选结论、主要正负因子、风险/缺失原因、严重度、置信度和证据引用。 |
| `analysis_evidence_links` | 第四层 lineage 边，把 snapshot/metric/finding 反链到 quant result、QuantInput、canonical fact、Evidence 或后续 ML feature run。 |
| `valuation_assessments` / `effective_assessment_pointers` | 估值结论和当前有效结论指针。 |
| `research_context_snapshots` | 供 AI 复核读取的冻结研究上下文快照。 |

相关迁移：`20260622_0021` 至 `20260622_0024`，v0.3 公司池/源系统/量化历史索引迁移 `20260623_0036` 至 `20260624_0041`，Analysis Mart 迁移 `20260624_0042_analysis_mart.py`，Quant Feature Mart 迁移 `20260625_0043_quant_feature_mart.py`，以及死表清理迁移 `20260625_0044_remove_dead_tables.py`。

## 关键代码

| 文件 | 主要对象 | 说明 |
|------|----------|------|
| `models.py` | `UniverseMembership`, `QuantInputSnapshot`, `QuantRun`, `QuantResult`, `NewsTarget`, `EffectiveAssessmentPointer` | 不可变领域模型。 |
| `universe.py` | `UniverseResolver` | 按业务时间和系统时间解析 `CSI300`、`CSI500`、`ALL_A`。 |
| `scope.py` / `quant_input.py` | `ScopeBinding`, `QuantInputSnapshotBuilder` | 冻结用户可见指标和底层量化指标，构建 PIT 输入快照。 |
| `quant_adapter.py` | `SQLAlchemyScopeBindingProvider`, `WarehouseFactAdapter`, `build_cross_section_loader`, `QuantAdapter` | 连接策略 scope、数据层公司池、warehouse canonical/fact history、第四层特征 ETL 和量化服务；历史行情读取按每证券/指标最近 260 个 PIT 点限流，避免加载两年全量事实。 |
| `quant/filters.py` | `HardFilterEngine` | ST、停牌、上市时间、流动性、财务缺失、亏损、负债、商誉、现金流、审计意见过滤。 |
| `quant/scoring.py` / `quant/service.py` | `FactorScorer`, `QuantService` | 行业内标准化、五因子加权、版本化手工池最终分、状态/guardrail、rank 和结果持久化。 |
| `quant/manual_all_a.py` / `quant/theme_tilt.py` | `score_manual_all_a`, `score_theme_components`, `confirmation_states` | 手工三池量化分、确认后的题材/行业热点加分、题材热度进入/退出确认。 |
| `etl.py` | `SQLAlchemyQuantFeatureMartETLPipeline`, `QuantFeatureMartETLPipeline`, `AnalysisResultMartETLPipeline`, `build_feature_mart_cross_section_loader` | v0.3 ETL 管道层统一入口；第三层到第四层特征发布、量化只读第四层、量化结果反写 Analysis Mart 都从这里编排。 |
| `analysis_mart.py` | `AnalysisMartPublisher`, `SQLAlchemyAnalysisMartRepository`, `MemoryAnalysisMartRepository`, `QuantFeatureSnapshot`, `AnalysisSnapshot`, `AnalysisMetric`, `AnalysisFinding` | 第四层特征/分析结果发布与读取；同输入重放幂等，冲突重放拒绝。 |
| `news_targets.py` | `NewsTargetSelector` | PASS 全量进入新闻目标；允许的 NEAR_THRESHOLD 可进入；不做 top-N 裁剪。 |
| `valuation.py` | `IndustryValuationRegistry` | 银行、保险、周期资源、消费/制造、成长/科技、公用事业估值模型族。 |
| `confidence.py` | `ConfidenceCalibrator` | 确定性置信度校准，不接受 LLM 置信度覆盖。 |
| `assessments.py` | `EffectiveAssessmentService` | deferred/abstain 保留旧结论，invalidate/update 指向新结论。 |
| `orchestrator.py` / `service.py` | `ValuationDiscoveryOrchestrator`, `ValuationDiscoveryService` | 12 步刷新编排、幂等启动、失败/等待/跳过语义。 |

## 第四层 Mart 与 ETL

发布路径：

```text
第三层 canonical/company pool/history
  -> SQLAlchemyQuantFeatureMartETLPipeline.materialize(...)
  -> quant_feature_snapshots / quant_feature_rows
  -> QuantService 只读 feature_snapshot_id 对应的第四层截面
  -> QuantResult + quant run lineage
  -> AnalysisResultMartETLPipeline.publish_quant_result(...)
  -> analysis_snapshots / analysis_metrics / analysis_findings / analysis_evidence_links
  -> ResearchContext payload.analysis_snapshot_id / analysis_summary
  -> 06 analysis_* scoped read tools
```

事务边界：

- `SQLAlchemyQuantFeatureMartETLPipeline` 在一个数据库事务内写入绑定 `feature_snapshot_id` 后的 `quant_input_snapshots`、`quant_input_snapshot_facts`、`quant_feature_snapshots` 和 `quant_feature_rows`；
- `AnalysisMartRepository.upsert_bundle()` 在一个事务内写入 `analysis_snapshots`、metrics、findings 和 links；
- 任一 child row 冲突或写入失败都会回滚本次 ETL，不留下只有 header 或只有部分 rows 的脏数据；
- `QuantAdapter.build_input()` 配置 feature ETL 后先物化第四层特征，再把绑定后的 `QuantInputSnapshot` 交给量化运行。

`AnalysisMartPublisher` 当前从量化结果加工：

- snapshot summary：`screening_status`、`data_status`、`research_guardrail`、`review_required`、rank、主要原因、风险/缺失字段；
- metrics：`final_score`、`quality_score`、`value_score`、`growth_score`、`momentum_score`、`risk_score`、rank 和 review/data quality 指标；
- findings：`quant_screening` 发现，包含筛选状态、数据状态、风险标记、正负因子和置信度；
- evidence links：至少反链到 `quant_screen_results`、`quant_screen_runs` 和 `quant_input_snapshots`。

Repository 行为：

- `upsert_bundle()` 在一个事务内写入 snapshot、metrics、findings 和 links；
- 相同主键且内容一致的重放视为幂等；
- 相同主键但内容/hash 不一致的重放抛错，避免覆盖历史分析结果；
- `latest_snapshot(security_id, scope_version_id, as_of)` 按 decision time 返回当前可见快照；
- `list_metrics()`、`list_findings()`、`list_evidence_links()` 供 Dashboard 和 AI 工具读取。

`ResearchContextBuilderAdapter` 在构造后置 AI 上下文时会尝试发布 Analysis Mart，并把 `analysis_snapshot_id` 与 `analysis_summary` 写入冻结 payload；没有 repository 时保持兼容路径，不阻断旧测试和离线用法。

## FastAPI 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/valuation-discovery/refreshes` | 启动估值发现刷新；个人本地模式无需本地 admin/CSRF，仍要求 `Idempotency-Key`，返回 `202` 与 `run_id`。请求中的 `scope-current` 会在 API 边界先校准 active Research Scope 与最新激活配置，再解析为冻结 scope 版本；未配置 service 或 active scope 时 fail-closed 为 `503`。 |
| `GET` | `/api/v1/valuation-discovery/runs` | 分页列出最近的 valuation discovery refresh run。 |
| `GET` | `/api/v1/valuation-discovery/runs/{run_id}` | 查询单个 refresh run 的状态与各步骤。 |
| `GET` | `/api/v1/valuation-discovery/companies/{security_id}/quant` | 返回某证券最新的量化筛选 profile，含 5 大因子组分数、排名、筛选状态、风险标记、复核原因和原因摘要。无结果时返回 `404`。 |
| `GET` | `/api/v1/valuation-discovery/companies/{security_id}/analysis` | 返回某证券的第四层 Analysis Mart profile，含 snapshot 头、metrics（带市场和行业百分位/排名）、findings（带 severity/confidence/evidence）和 evidence link 数量。`scope_version_id` 可选，省略时跨所有 scope 取最新。 |

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

2026-07-02 本地端到端 refresh 验证：

- 激活公司池：`universe-csi300-default-v0.3.0`
- active scope：`scope-universe-b03f5214e056900f`
- refresh run：`vdr_abcdbd61a870a9e1e8024343`
- Feature snapshot：`qfsnap_f8f45785b803e4c2cc9b37f7`，`row_count=300`
- Quant run：`qr_b0b6297bde0e43f8`
- 结果分布：300 条结果，0 `pass`，1 `near_threshold`，299 `reject`
- Dashboard run：`dr_5e4501525fbe8434615c1994`，发布 1 条可见候选 `000001.SZ`
- 该 run 真实走完 DATA_FRESHNESS_CHECK、DATA_SYNC、SCOPE_RESOLVE、QUANT_INPUT_BUILD、QUANT_RUN、NEWS_TARGET_SELECTION、NEWS_REFRESH、NEWS_INDEXING、RESEARCH_CONTEXT_BUILD、AI_DELTA_REVIEW、VALUATION_PUBLISH、DASHBOARD_REFRESH；Tavily 与 embedding provider 均有真实 HTTP 调用记录。

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
- 输出：量化候选、Analysis Mart 快照/指标/发现/证据链、NewsTarget、估值结论、effective pointer、Dashboard/API 可读 run 状态。
- 边界：量化层不调用外部 Provider；Analysis Mart 只由第三层唯一化数据、量化结果和受控证据引用派生；新闻、索引、RAG 和 AI 由后续模块服务承接。
