# 10-deployment_audit — 部署、审计和可观测性

这个模块负责让系统能跑、能查、能降级、能复盘。

## 它做什么

- 提供 Docker / Compose / migration / bootstrap / smoke 脚本。
- 暴露健康检查、Prometheus 指标和结构化日志。
- 保存审计记录、快照、任务状态和降级原因。
- 在 Provider 不可用、配置缺失或任务失败时给出明确状态。

## 它怎么跑

```text
部署启动
  -> migration
  -> bootstrap 配置
  -> api / worker / web 启动
  -> health / metrics / audit 持续记录
```

这个模块不产生股票推荐，但它决定系统出问题时能不能定位原因。

## 主要入口

- `Dockerfile`、`web/Dockerfile`、`docker-compose.yml`。
- `scripts/`：开发、迁移、回填、smoke。
- `src/margin/core/`：audit、metrics、degradation、run states。
- `src/margin/api/routes/health.py` 和 `/metrics`。

## 输出给谁

- 开发者用它启动和排错。
- CI / 部署环境用它验证服务状态。
- Agent 和 Dashboard 用它展示 degraded / unhealthy 状态。
