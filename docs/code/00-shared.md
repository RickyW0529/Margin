# 00-shared — 共享基础能力

这个模块不是业务流程本身，而是所有模块共用的底座。

## 它做什么

- 读取配置、环境变量和运行参数。
- 管理数据库连接、迁移、事务和测试隔离。
- 提供 Provider 抽象、注册表、密钥存储和健康检查。
- 记录审计、快照、日志、指标、降级状态和后台任务状态。

## 它怎么跑

```text
应用启动
  -> 读取配置
  -> 初始化数据库和 Provider
  -> 注册 API / Worker 依赖
  -> 运行任务时写入日志、指标和审计
```

业务模块一般不会自己处理连接、密钥、日志和审计，而是调用这里的公共能力。

## 主要入口

- `src/margin/settings.py`：全局配置。
- `src/margin/storage/`：数据库和 session。
- `src/margin/core/`：Provider、secret、audit、metrics、degradation 等共享逻辑。
- `src/margin/api/`：FastAPI 依赖和中间件。
- `src/margin/worker.py`：后台调度入口。

## 输出给谁

- 数据模块用它读 Provider 和数据库。
- Agent 模块用它读配置、密钥和审计能力。
- Dashboard / API 用它拿 service dependency。
- 部署模块用它做健康检查和可观测性。
