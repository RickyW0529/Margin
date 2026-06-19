---
task_id: 0302
parent_module: 03-filing_websearch
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §26-Phase3: WebSearch Provider 与合规去重; §6.2.1]
status: active
estimate_days: 7
depends_on: [0301]
---

# 0302 WebSearch Provider — 实施计划

## 1. 任务目标

实现可配置 WebSearch Provider：用户自行填写 API Key，系统保存搜索 query、返回 URL、标题、摘要、抓取时间、原文快照哈希。只有结果能落到可访问原文或合规快照时才进入 RAG 证据库。不绕过 robots、登录墙、付费墙或反爬机制，不把版权受限全文提交到开源样例数据。

## 2. 工作项拆解

- 0302.1 WebSearchProvider 接入 — 用户配置 API Key，调用搜索接口。
- 0302.2 搜索结果快照 — 保存 query/URL/标题/摘要/抓取时间/原文快照哈希。
- 0302.3 合规边界执行 — robots/付费墙/反爬不绕过，版权受限全文不入开源样例。
- 0302.4 原文落校验 — 仅当可落到可访问原文或合规快照时进入证据库。

## 3. 依赖关系

- 前置：0301（公告获取与文档事件机制）。
- 被依赖：0303（去重与合规分级）。
- 外部依赖：用户 WebSearch API Key。

## 4. 工时估算

- 0302.1：2 天
- 0302.2：2 天
- 0302.3：2 天
- 0302.4：1 天
- 合计：7 天。

## 5. 里程碑与交付物

- M1：WebSearchProvider 可配置调用（第 2 天）。
- M2：搜索结果快照完整（第 4 天）。
- M3：合规边界规则生效（第 6 天）。
- M4：原文落校验通过（第 7 天）。

## 6. 验收动作

- 可配置至少一个 WebSearch/新闻源（对应产品 §15 条目 2）；
- WebSearch 结果只引用搜索摘要而无原文时被拒绝入库；
- 合规边界触发时拒绝并提示。

## 7. 审计追溯

- `source_refs`：架构 §26-Phase3 c2、§6.2.1；
- 关联 spec：`spec/v0.1/03-filing_websearch/spec.md` §3 / §7；
- 不可变产物：搜索结果快照、原文快照哈希。
