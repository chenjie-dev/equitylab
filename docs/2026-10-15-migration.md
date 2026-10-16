# 从 Java 数据底座到 Agent 平台的改造说明

## 为什么改

立项文档要求：自然语言驱动的研报 / 因子 / 回测 / 行情平台——计算生态以 **Python** 为主，编排与交付以 **TypeScript** 为主，网关与行情以 **Rust** 为主。原 Java Spring Boot 单体无法覆盖该分层选型，且本地推理层（vLLM）不在目标架构内。

## 做了什么

1. **删除** Java 源码、`pom.xml`、旧 Dockerfile / Maven Wrapper / 业务 Flyway 应用模型。  
2. **新建** monorepo：`apps/*`（frontend / orchestrator / research）+ `services/*`（gateway / market-data）+ Compose 容器组。  
3. **保留** 项目名 EquityLab 与研究向定位；交易仍仅为模拟/研究，不接实盘。  
4. **MVP** 聚焦可运行链路：健康检查、网关反代与限流、编排工具调用、研究层占位、行情 Mock、文档与注释基线。

## 旧能力映射

| 旧 Java 能力 | 新落点 |
|---|---|
| asOf / 财务公告版本化 | 后续迁入 Python research + PostgreSQL 领域表 |
| 模拟交易账务 | 后续 Strategy / Paper 模块（非本 MVP） |
| 单体外 REST | Gateway 统一入口 + 分服务 API（见 [API 参考](./2026-10-15-api.md)） |

## 下一步

见立项文档第八、九章 TODO，以及 [架构说明](./2026-10-15-architecture.md) 中标注的后续项：LangGraph、完整 RAG、MCP、真实行情 Provider、Token 预算与可观测性。
