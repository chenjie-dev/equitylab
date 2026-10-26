# EquityLab 可观测性（日志 / TraceId）

> 创建日：2026-10-16。全服务统一 `X-Trace-Id` + JSON stdout；Compose 采集栈为 Loki + Grafana Alloy + Grafana。

## 约定

| 项 | 值 |
|---|---|
| 请求头 / 响应头 | `X-Trace-Id`（小写传输时为 `x-trace-id`） |
| 缺失时 | 网关或入站服务生成 UUID v4 |
| 日志格式 | JSON 一行一条：`ts` / `level` / `service` / `traceId` / `msg` + 可选 `method` `path` `status` `latencyMs` |
| 本轮范围 | 日志关联；**不上** OTel span 导出 |
| MCP stdio | 未接入（侧车可选后续） |

## 透传路径

```text
Browser / curl
  → Frontend BFF（生成或沿用）
  → Gateway（生成或沿用，写入响应头，转发下游）
  → Orchestrator / Research / Market-Data
       └─ Research → Market-Data（回测拉 /bars 时继续透传）
```

编排层工具调用一律附带 `X-Trace-Id`。

## Compose 服务

| 服务 | 端口 | 说明 |
|---|---|---|
| loki | 3100 | 日志存储 |
| alloy | （内部 12345） | 采 Docker 容器日志；需挂载 `docker.sock` |
| grafana | **3003** | Explore → Loki；匿名 Viewer；admin/admin（见 `.env`） |

查询示例（Grafana Explore / LogQL）：

```logql
{compose_project="equitylab"} |= "traceId"
{service="gateway"} | json | traceId="<粘贴的 id>"
```

## 冒烟

```bash
# 自带 traceId
TID=$(uuidgen | tr '[:upper:]' '[:lower:]')
curl -sD - -o /dev/null -X POST http://localhost:3000/api/chat \
  -H "content-type: application/json" \
  -H "X-Trace-Id: $TID" \
  -d '{"message":"茅台现在多少钱？"}' | grep -i x-trace-id

# Grafana
open http://localhost:3003
```
