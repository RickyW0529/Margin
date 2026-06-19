---
module_id: 03-filing_websearch
product_version: v0.1
doc_version: v0.1
source_refs: [产品设计 §4.3, §4.3.1, §13.2-3; 架构设计 §6, §26-Phase3]
status: active
---

# 03 公告与 WebSearch 模块 — 功能规格

## 1. 模块目标

统一获取所有非结构化投资信息：交易所公告、财报/IR、行业硬数据、权威财经媒体、用户自配 RSS/API/网页来源。MVP 不做无边界爬虫，而是通过可配置 WebSearch Provider 发现新闻与网页，并对来源进行 L1–L5 合规分级与去重，保证只有可落到可访问原文或合规快照的内容才能进入 RAG 证据库。

## 2. 输入 / 输出

- **输入**：交易所公告接口、用户配置的 WebSearch API Key、RSS/API/网页来源、交易日调度。
- **触发**：晚间调度增量获取、Agent 研究流程按需检索。
- **输出**：标准化文档事件（公告/新闻/网页），含原文快照、来源 URL、抓取时间、内容哈希、来源等级、证券实体映射；进入 04-text_indexing 的向量化队列。
- **消费方**：04-text_indexing、05-rag_evidence、06-multi_agent_research（WebSearch Agent / Document Collector / FilingTool）。

## 3. 接口契约

获取组件（架构 §6.2）：Source Registry、Connector（API/RSS/网页/文件）、Scheduler、Downloader、Snapshot、Deduplicator、Classifier、Quality Scorer、Event Publisher。

WebSearch Provider 合规约束（架构 §6.2.1）：

- 用户自行填写 API Key；
- 系统保存搜索 query、返回 URL、标题、摘要、抓取时间、原文快照哈希；
- 只有结果能落到可访问原文或合规快照时，才进入 RAG 证据库；
- 不绕过 robots、登录墙、付费墙或反爬机制；
- 不把版权受限全文提交到开源样例数据；
- L4/L5 只能触发调查或辅助解释，不能单独改变研究/持仓状态。

## 4. 数据模型

文档处理流程（架构 §6.3）：发现 URL/API 记录 → 下载原文 → 保存原始快照 → 格式识别 → 正文/表格解析 → 去重 → 证券实体映射 → 时间与来源等级 → 进入向量化队列。

来源优先级（架构 §6.1）：L1 交易所/监管/公司定期报告 → L2 IR/业绩说明会 → L3 行业硬数据 → L4 权威财经媒体 → L5 RSS/社交媒体。L1–L5 喂入证据质量评分。

## 5. 与其他模块依赖

- **上游**：01-data_provider（证券元数据用于实体映射）、用户 WebSearch 配置。
- **下游**：04-text_indexing（向量化）、05-rag_evidence（证据来源等级）、06-multi_agent_research。
- **规避循环**：本模块只产出文档事件，不消费研究结论。

## 6. 验收标准

对应产品设计 §15：

- 条目 2：可配置至少一个 WebSearch/新闻源；
- 条目 4：研究结论包含证据引用（依赖本模块产出可定位原文）。

## 7. 风险与降级

对应架构 §25：

- 文本解析失败 → 保留原文快照并停止相关 AI 结论（架构 §25）；
- WebSearch 限流/失败 → 降级为已有公告与快照，不伪造来源；
- 版权/合规边界触发 → 拒绝入库并提示用户。

## 8. 审计追溯

- `source_refs` 指向产品设计 §4.3 / §4.3.1、架构设计 §6 / §26 Phase3；
- 每条文档事件保留原文快照哈希、source_url、抓取时间、来源等级、content_hash，落库不可篡改；
- 去重保留最早可靠来源（架构 §6.4），转载链可追溯。
