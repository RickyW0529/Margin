# 07-strategy_config — 策略和 Provider 配置

这个模块负责告诉系统“这次研究用哪些数据、模型、范围和策略”。

## 它做什么

- 管理 Provider 配置和密钥版本。
- 管理研究范围、公司池、指标视图和策略模板。
- 管理 Prompt、自定义配置、版本生命周期和启用状态。
- 做配置校验、健康检查和 fail-closed 降级。

## 它怎么跑

```text
用户保存设置
  -> 写入配置版本
  -> Provider health 检查
  -> 激活可用配置
  -> 今日研究读取 active 配置
```

密钥只写入，不在前端回显。依赖不可用 Provider 的任务应该明确失败，而不是假装成功。

## 主要入口

- `src/margin/strategy/`：策略模板、scope、provider runtime。
- `src/margin/core/secret_store.py`：密钥存储。
- `src/margin/api/routes/strategy*.py`：配置 API。
- `web/components/provider-settings-panel.tsx`：Provider 设置界面。

## 输出给谁

- `01-data_provider` 用它读取数据源配置。
- `06-multi_agent_research` 用它读取模型和 Prompt 配置。
- `08-research_candidate_dashboard` 用它展示设置页和 Provider 状态。
