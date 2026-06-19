---
task_id: 0703
parent_module: 07-strategy_config
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §15.3 策略沙箱; 产品设计 §6.4]
status: active
estimate_days: 7
depends_on: [0702]
---

# 0703 策略版本管理与沙箱 — 实施计划

## 1. 任务目标

实现策略版本状态机（Draft→Validating→Invalid/Backtesting→PaperTrading→Active→Archived/Suspended）与策略沙箱（配置校验、样例运行、历史回测、数据泄漏检查、交易成本测试、报告预览、用户手工启用）。策略错误时回滚上一版本，数据或风险异常时 Active→Suspended。

## 2. 工作项拆解

- 0703.1 策略版本状态机 — 状态流转与归档。
- 0703.2 策略沙箱 — 校验/样例运行/回测/泄漏检查/成本测试/预览。
- 0703.3 启用与回滚 — 用户手工启用 Active，错误回滚上一版本。
- 0703.4 Suspended 触发 — 数据或风险异常时挂起。

## 3. 依赖关系

- 前置：0702（自定义 Prompt）。
- 被依赖：0605（研究信号生成加载 Active 策略版本）、0801（候选面板 e2 after e1）、0901（持仓监控 e3 after e1）。
- 外部依赖：06 回测能力（BacktestTool）。

## 4. 工时估算

- 0703.1：2 天
- 0703.2：3 天
- 0703.3：1 天
- 0703.4：1 天
- 合计：7 天。

## 5. 里程碑与交付物

- M1：策略版本状态机可用（第 2 天）。
- M2：策略沙箱六项检查齐全（第 5 天）。
- M3：启用与回滚（第 6 天）。
- M4：Suspended 触发（第 7 天）。

## 6. 验收动作

- 用户可版本化自定义策略（对应产品 §15 条目 5）；
- 策略错误时回滚上一版本（对应架构 §25）；
- 数据/风险异常时 Active→Suspended（对应 spec 07 §7）。

## 7. 审计追溯

- `source_refs`：架构 §15.3、产品 §6.4；
- 关联 spec：`spec/v0.1/07-strategy_config/spec.md` §4 / §7 / §8；
- 不可变产物：策略版本状态、沙箱检查结果、回滚记录。
