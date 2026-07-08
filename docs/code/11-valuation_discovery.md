# 11 valuation_discovery — 公司池与估值发现模块

## 模块概述

`src/margin/valuation_discovery/` 实现 v0.2/v0.3 的公司池、量化筛选、第四层 Quant Feature Mart / Analysis Mart、新闻目标选择、行业估值、置信度校准、有效结论指针和刷新编排。模块只消费冻结的数据仓库输入和策略 scope，不直接调用 AKShare、Tushare、Tavily、LLM 或交易接口。

v0.3 中，公司池来源切到数据层 materialized company pool：`SQLAlchemyScopeBindingProvider` 对 `ALL_A` / `ALL_A_NON_ST` scope 优先读取最新 `company_pool_snapshots`，量化输入不再使用静态 universe membership。公司池排除 ST、`退市*` 名称、未来上市和已退市证券。指数池 `CSI300` / `CSI500` 由策略配置层从 Tushare `index_weight` 最新成分生成 `UniverseDefinitionVersion.member_security_ids`，用户切换公司池后，`scope-current` 会滚动到对应 universe version，量化输入按该成员集合构建。

当前量化服务支持版本化手工池策略：当 `QuantInputSnapshot.quant_feature_set.metadata.quant_strategy.thresholds.presets` 提供因子权重时，`QuantService` 使用 `manual_all_a_score` 作为真实 `QuantResult.final_score`、rank 和 screening status 的输入。`theme_hotness` 是确认后的题材/行业热点加分项，来自 PIT 安全 cross-section 中的 `theme_hot_score`、`theme_member_confidence`、`theme_signal_confirmed` 字段；未确认或非成员公司不加分。无版本化策略 metadata 的兼容路径仍使用旧五组分 `FactorScorer.combine()`。

当前量化服务也支持 `strategy_family=ml_lgbm_lifecycle` 的 ML 生命周期 serving 路径。该路径位于 `quant/ml_lifecycle.py`，不在 API/worker 内重训模型、不调用 Tushare/AKShare、不读取 `quant_ml_backtest` 文件，只消费 `QuantRepository.load_cross_section()` 返回的 PIT-safe Mart 特征。输出写入 `QuantResult.factor_details.ml_strategy`，包含 `model_family`、`strategy_version`、`feature_coverage`、`score_components`、`risk_controls`、`target_weight`、`cash_policy`、`execution_boundary=research_only_no_order` 和 `fallback_used`。组合层默认最高股票仓位 80%、最低现金 20%；单票不设硬上限，停牌/ST/硬过滤候选在 ML 前被拒绝且 `target_weight=0`。`QuantAdapter.run()` 在使用 Feature Mart 物化或从持久化恢复的 `QuantInputSnapshot` 时，会按 `scope_version_id` 重新绑定 `quant_feature_set.metadata.quant_strategy`，避免重载快照丢失策略 metadata 后退回旧 `quant-v0.2` 兼容路径。

v0.3 已新增第四层 Mart：第三层唯一化数据先由 ETL 管道物化为 `quant_feature_snapshots` / `quant_feature_rows`，量化层只读第四层特征快照；量化结果再通过 ETL 管道发布为 `analysis_snapshots`、`analysis_metrics`、`analysis_findings` 和 `analysis_evidence_links`。这一层面向 Quant、Dashboard 与 LangGraph scoped read tools，保存 AI 可直接读取的结构化指标、主要发现、质量标记、输入/结果 hash 和 lineage，避免 AI 每次自行从第三层重算指标。Feature Mart cross-section loader 会额外读取 PIT 安全的年度 `n_income_attr_p` 历史并在 ETL 阶段派生 `net_profit_y1` / `net_profit_y2`，供连续两年亏损过滤使用。停牌硬过滤优先读取数据层 `suspend_d` 发布的 `is_suspended` / `suspend_type`；缺行情兜底只在最新市场日期覆盖率达到 80% 时启用，避免局部 smoke/backfill 的单日行情把全市场误判为停牌。刷新编排在 `RESEARCH_CONTEXT_BUILD` 后先执行 `DASHBOARD_REFRESH`，把量化 pass/near_threshold/watchlist 投影到今日推荐页；如果生产依赖注入 `StockAnalystAgent`，publisher 会立刻发布专家 adjusted dashboard run，并把 `portfolio_adjustment` / `dashboard_projection_event` 写入 MainAgent Context Store。随后流程继续耗时的 AI 复核和估值发布。`NewsRefreshAdapter` 只在 news refresh terminal 或 provider wait 状态明确时放行；如果 refresh run 仍是 `pending` / `running`，会返回 `news_refresh_incomplete` 的 retryable step，避免 target retry 期间提前构造 partial research context 并触发 AI 延期结论。

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

相关迁移：`20260622_0021` 至 `20260622_0024`，v0.3 公司池/源系统/量化历史索引迁移 `20260623_0036` 至 `20260624_0041`，Analysis Mart 迁移 `20260624_0042_analysis_mart.py`，Quant Feature Mart 迁移 `20260625_0043_quant_feature_mart.py`，死表清理迁移 `20260625_0044_remove_dead_tables.py`，以及 ML dashboard 权重与新增 Tushare landing 表迁移 `20260708_0049_dashboard_ml_weights.py` / `20260708_0050_ml_tushare_endpoint_landing.py`。

## 关键代码

| 文件 | 主要对象 | 说明 |
|------|----------|------|
| `models.py` | `UniverseMembership`, `QuantInputSnapshot`, `QuantRun`, `QuantResult`, `NewsTarget`, `EffectiveAssessmentPointer` | 不可变领域模型。 |
| `universe.py` | `UniverseResolver` | 按业务时间和系统时间解析 `CSI300`、`CSI500`、`ALL_A`。 |
| `scope.py` / `quant_input.py` | `ScopeBinding`, `QuantInputSnapshotBuilder` | 冻结用户可见指标和底层量化指标，构建 PIT 输入快照。 |
| `quant_adapter.py` | `SQLAlchemyScopeBindingProvider`, `WarehouseFactAdapter`, `build_cross_section_loader`, `QuantAdapter` | 连接策略 scope、数据层公司池、warehouse canonical/fact history、第四层特征 ETL 和量化服务；历史行情读取按每证券/指标最近 260 个 PIT 点限流，并单独读取年度 `n_income_attr_p` 历史派生 `net_profit_y1` / `net_profit_y2`；停牌状态强制读取显式 hard-filter 指标，并对缺行情兜底使用覆盖率阈值；运行前会把持久化/重载快照重新绑定到当前 frozen scope 的策略 metadata。 |
| `quant/filters.py` | `HardFilterEngine` | ST、停牌、上市时间、流动性、财务缺失、亏损、负债、商誉、现金流、审计意见过滤；默认财务缺失 canary 为 `roe_ttm`，连续亏损仍消费 ETL 派生的 `net_profit_y1` / `net_profit_y2`。 |
| `quant/scoring.py` / `quant/service.py` | `FactorScorer`, `QuantService` | 行业内标准化、五因子加权、版本化手工池最终分、状态/guardrail、rank 和结果持久化。 |
| `quant/ml_lifecycle.py` | `score_ml_lifecycle`, `MLLifecycleConfig` | ML 生命周期 serving scorer；只读 PIT-safe cross-section，生成 ML 分数、风险门控、特征覆盖、80% 组合仓位分配和研究用途 profile。 |
| `quant/manual_all_a.py` / `quant/theme_tilt.py` | `score_manual_all_a`, `score_theme_components`, `confirmation_states` | 手工三池量化分、确认后的题材/行业热点加分、题材热度进入/退出确认。 |
| `etl.py` | `SQLAlchemyQuantFeatureMartETLPipeline`, `QuantFeatureMartETLPipeline`, `AnalysisResultMartETLPipeline`, `build_feature_mart_cross_section_loader` | v0.3 ETL 管道层统一入口；第三层到第四层特征发布、量化只读第四层、量化结果反写 Analysis Mart 都从这里编排。 |
| `analysis_mart.py` | `AnalysisMartPublisher`, `SQLAlchemyAnalysisMartRepository`, `MemoryAnalysisMartRepository`, `QuantFeatureSnapshot`, `AnalysisSnapshot`, `AnalysisMetric`, `AnalysisFinding` | 第四层特征/分析结果发布与读取；同输入重放幂等，冲突重放拒绝。 |
| `news_targets.py` | `NewsTargetSelector` | PASS 全量进入新闻目标；允许的 NEAR_THRESHOLD 可进入；不做 top-N 裁剪。 |
| `valuation.py` | `IndustryValuationRegistry` | 银行、保险、周期资源、消费/制造、成长/科技、公用事业估值模型族。 |
| `confidence.py` | `ConfidenceCalibrator` | 确定性置信度校准，不接受 LLM 置信度覆盖。 |
| `assessments.py` | `EffectiveAssessmentService` | deferred/abstain 保留旧结论，invalidate/update 指向新结论。 |
| `adapters.py` | `NewsRefreshAdapter`, `ResearchContextBuilderAdapter`, `AIReviewAdapter`, `ValuationPublisherAdapter` | 将 news、context、AI、publish/dashboard 等生产服务接入 durable orchestrator；news refresh 仍在 pending/running 时保持 retryable，不向 context builder 放行；publisher 可注入 `StockAnalystAgent`，在默认量化 dashboard run 之后发布 adjusted run。 |
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
- ML metrics：当 `factor_details.ml_strategy` 存在时额外发布 `ml_lifecycle_score`、`ml_target_weight`、`ml_feature_coverage` 和各 score component，供 Agent/Dashboard 不重算即可读取；
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
- 该 run 真实走完 DATA_FRESHNESS_CHECK、DATA_SYNC、SCOPE_RESOLVE、QUANT_INPUT_BUILD、QUANT_RUN、NEWS_TARGET_SELECTION、NEWS_REFRESH、NEWS_INDEXING、RESEARCH_CONTEXT_BUILD、DASHBOARD_REFRESH、AI_DELTA_REVIEW、VALUATION_PUBLISH；Tavily 与 embedding provider 均有真实 HTTP 调用记录。

最新 Tushare 数据链路验收 run：

- 公司池快照：`cps_29518c0fec90836c57609b6f1f24`
- Tushare 增量补数 run：`tsr_ca63bc9d4f91`，完成 `moneyflow`、`margin_detail`、`forecast`、`express`、`limit_list_d` 五类 ML 增强 endpoint 的 landing/quality/warehouse 发布。
- 当前默认 active scope：`scope-default-v0.4.1`，绑定 `quant-strategy-ml-lifecycle-v0.4.1` 和 `quant-feature-default-v0.4.1`。
- 最新 ML serving 验证 run：`qr_a7b782b514cc43bd`
- 决策时间：`2026-06-30T08:05:00Z`
- `QuantInputSnapshot`：`qis_4f1a7cbddef048d7`
- 输入公司数：5317
- 结果分布：62 `pass`，249 `near_threshold`，424 `watchlist`，4582 `reject`
- 输出字段：所有 ML scoring 行写入 `factor_details.ml_strategy.profile_id=liquid-large-mid-lgbm-recent-trend80-ddstop-v1`、`target_weight`、风险门控、特征覆盖和 cash policy。

Top pass：

| rank | code | final | target_weight | status |
|---:|---|---:|---:|---|
| 1 | 000792.SZ | 79.84 | 16.10% | pass |
| 2 | 300308.SZ | 79.82 | 15.91% | pass |
| 3 | 688525.SH | 78.80 | 8.59% | pass |
| 4 | 301308.SZ | 78.07 | 5.52% | pass |
| 5 | 001309.SZ | 77.94 | 5.10% | pass |

## 跨模块依赖

- 读取：数据仓库 canonical/fact lineage、策略 scope、module 10 orchestration。
- 输出：量化候选、Analysis Mart 快照/指标/发现/证据链、NewsTarget、估值结论、effective pointer、Dashboard/API 可读 run 状态。
- 边界：量化层不调用外部 Provider；Analysis Mart 只由第三层唯一化数据、量化结果和受控证据引用派生；新闻、索引、RAG 和 AI 由后续模块服务承接。
