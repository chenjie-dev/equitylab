# EquityLab 可观测性（日志 / TraceId / Prometheus）

> 创建日：2026-10-16。全服务统一 `X-Trace-Id` + JSON stdout；Compose 采集栈为 Loki + Grafana Alloy + Grafana；**指标**由 Prometheus 抓取，Grafana 看板展示。

## 约定

| 项 | 值 |
|---|---|
| 请求头 / 响应头 | `X-Trace-Id`（小写传输时为 `x-trace-id`） |
| 缺失时 | 网关或入站服务生成 UUID v4 |
| 日志格式 | JSON 一行一条：`ts` / `level` / `service` / `traceId` / `msg` + 可选 `method` `path` `status` `latencyMs` |
| 指标 | `GET /metrics`（Prometheus text）；采集族独立端口 `:9101` / `:9102` |
| 本轮范围 | 日志关联 + Prometheus 指标与 Grafana 看板；**不上** OTel span / Alertmanager |
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
| prometheus | **9091**→9090 | 抓取 6 个 job；配置 `infra/observability/prometheus.yml` |
| loki | 3100 | 日志存储 |
| alloy | （内部 12345） | 采 Docker 容器日志；需挂载 `docker.sock` |
| grafana | **3003** | Explore（Loki）+ Dashboards（Prometheus）；匿名 Viewer；admin/admin（见 `.env`） |

### Scrape 目标

| job | target | 路径 |
|---|---|---|
| gateway | `gateway:3000` | `/metrics` |
| market-data | `market-data:3002` | `/metrics` |
| research | `research:8002` | `/metrics` |
| orchestrator | `orchestrator:8001` | `/metrics` |
| collector | `collector:9101` | `/metrics` |
| history-ingest | `history-ingest:9102` | `/metrics` |

数据面自定义指标示例：`equitylab_cn_equity_universe_size`、`equitylab_cn_equity_skip`、`equitylab_history_ingest_gaps_queued`、`equitylab_history_ingest_fill_total{status}`。

### Grafana 看板

- **EquityLab Platform**（uid `equitylab-platform`）：targets up、QPS、p95、5xx
- **EquityLab Market Data Plane**（uid `equitylab-market`）：宇宙规模、skip、WS、history-ingest 覆盖与 fill

预置 JSON：`infra/observability/grafana/dashboards/`。

查询示例（Grafana Explore / LogQL）：

```logql
{compose_project="equitylab"} |= "traceId"
{service="gateway"} | json | traceId="<粘贴的 id>"
```

PromQL 示例：

```promql
up{job="collector"}
equitylab_cn_equity_universe_size
histogram_quantile(0.95, sum by (le, service) (rate(http_request_duration_seconds_bucket[5m])))
```

## 冒烟

```bash
# TraceId
TID=$(uuidgen | tr '[:upper:]' '[:lower:]')
curl -sD - -o /dev/null -X POST http://localhost:3000/api/chat \
  -H "content-type: application/json" \
  -H "X-Trace-Id: $TID" \
  -d '{"message":"茅台现在多少钱？"}' | grep -i x-trace-id

# Prometheus
curl -s http://localhost:9091/-/ready
curl -s 'http://localhost:9091/api/v1/targets' | python3 -c "import sys,json;d=json.load(sys.stdin);print([(t['labels'].get('job'), t['health']) for t in d['data']['activeTargets']])"
curl -s 'http://localhost:9091/api/v1/query?query=equitylab_cn_equity_universe_size' | head -c 400

# 各服务 /metrics（示例）
curl -s http://localhost:3000/metrics | head
curl -s http://localhost:3002/metrics | head

# Grafana
open http://localhost:3003
```
