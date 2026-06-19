---
task_id: 0301
parent_module: 03-filing_websearch
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §26-Phase3: 公告获取与原文快照; §6.2, §6.3]
status: active
estimate_days: 14
depends_on: [0104]
---

# 0301 公告获取与原文快照 — 实施计划

## 1. 任务目标

实现交易所公告的增量获取、原文下载、原始快照保存、格式识别、正文/表格解析、证券实体映射、时间与来源等级标注，并发布标准化文档事件进入向量化队列。来源按 L1–L5 分级，L1 交易所/监管/定期报告优先。

## 2. 工作项拆解

- 0301.1 Source Registry 与 Connector — 公告来源注册、API/文件连接器。
- 0301.2 Scheduler 与 Downloader — 交易日调度、增量获取。
- 0301.3 Snapshot 与格式识别 — 原始 PDF/HTML 保存、格式识别。
- 0301.4 正文/表格解析与证券映射 — 解析、证券实体映射、来源等级与时间标注、发布文档事件。

## 3. 依赖关系

- 前置：0104（时点与质量校验，对应 Gantt c1 after b2）。
- 被依赖：0302（WebSearch Provider）、0401（向量化队列）。
- 外部依赖：01-data_provider 证券元数据。

## 4. 工时估算

- 0301.1：3 天
- 0301.2：3 天
- 0301.3：4 天
- 0301.4：4 天
- 合计：14 天（对齐 Gantt c1）。

## 5. 里程碑与交付物

- M1：Source Registry 与 Connector 可用（第 3 天）。
- M2：调度与增量获取（第 6 天）。
- M3：原始快照与格式识别（第 10 天）。
- M4：解析、映射、文档事件发布（第 14 天）。

## 6. 验收动作

- 公告获取后产出原文快照与文档事件，含 source_url、抓取时间、content_hash、来源等级；
- 解析失败时保留原文并停止相关 AI 结论（对应 spec 03 §7）。

## 7. 审计追溯

- `source_refs`：架构 §26-Phase3 c1、§6.2 / §6.3；
- 关联 spec：`spec/v0.1/03-filing_websearch/spec.md` §3 / §4；
- 不可变产物：原文快照、content_hash、文档事件。
