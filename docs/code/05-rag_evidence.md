# 05-rag_evidence — RAG 证据系统

这个模块负责把“检索到的文本”变成可以审计、可以引用、可以复盘的证据。

## 它做什么

- 管理 EvidencePackage、Claim、Evidence、Citation Locator。
- 校验证据是否真的能定位到原文。
- 检查 claim 与 evidence 是否冲突或缺证。
- 记录 evidence_id、source_id、snapshot、PIT 时间点和引用位置。

## 它怎么跑

```text
RAG 检索结果
  -> 证据分层和定位
  -> claim validation
  -> 冻结 EvidencePackage
  -> 绑定到研究结论 / Agent 输出
```

AI 输出不能只写“我认为”，必须能回链到这里保存的证据或明确说明证据不足。

## 主要入口

- `src/margin/evidence/`：证据模型、locator、validator、repository。
- `src/margin/research/evidence_tools.py`：Agent 可调用的 evidence 工具。

## 输出给谁

- `06-multi_agent_research` 用它支撑 AI 复核和问答引用。
- `08-research_candidate_dashboard` 展示证据摘要和原文定位。
