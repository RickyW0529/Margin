# Margin 文档

这里放项目文档，不是用户介绍页。用户快速了解项目请看根目录 `README.zh-CN.md`。

## 怎么读

- 想知道项目有什么用：看根目录 `README.zh-CN.md`。
- 想知道代码模块怎么跑：看 `docs/code/README.md`。
- 想查某个模块细节：看 `docs/code/NN-module.md`。
- 想看历史设计：看 `docs/design/`。

## 当前主流程

```text
配置策略和数据源
  -> 准备行情、财务、公告、新闻数据
  -> 生成公司池和量化特征
  -> 运行量化/ML 筛选
  -> 检索证据并做 AI 复核
  -> 发布到 Dashboard
  -> 留下审计和可追溯记录
```

`docs/code/README.md` 只解释当前代码怎么协作；`docs/design/` 保留历史设计，不随普通功能改动覆盖。
