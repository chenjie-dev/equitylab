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

### 行情数据面指标（新鲜度 + 覆盖）

| 指标 | 来源 | 中文含义（怎么读） |
|---|---|---|
| `equitylab_quote_last_success_unixtime{market}` | collector | 该市场**最后一次成功写报价**的时间戳；看板用 `time()-…` 显示「报价年龄」秒数。`cn_equity`=A 股，`binance`=币安 |
| `equitylab_quotes_written_total{market}` | collector | 写入报价累计条数；`rate()` 即**每秒写入吞吐**，盘中接近 0 不正常 |
| `equitylab_write_gate_pending{kind}` | collector | 写 qdb 前的**队列积压**：`quotes` 报价 / `trades` 成交 / `docs` 文档。报价积压高 → 盘口滞后 |
| `equitylab_write_gate_trade_drops_total` | collector | 成交队列溢出**丢掉**的累计条数；上升说明成交写不过来 |
| `equitylab_cn_equity_full_cycle_seconds` | collector | 估测扫完**一整轮 A 股报价**大约要多少秒；越大边缘票越旧 |
| `equitylab_snapshot_age_seconds{sample="seed"}` | collector | **种子标的**里最旧一只距上次写入的秒数（核心票新鲜度） |
| `equitylab_snapshot_stale_count{sample="seed"}` | collector | 种子中超过 `STALE_QUOTE_SEC`（默认 120s）未更新的只数；**休市偏高正常**，盘中宜≈0 |
| `equitylab_history_ingest_coverage_ratio` | history-ingest | 日线**覆盖率** = 达标只数 / 宇宙（0–1），越接近 1 越好 |
| `equitylab_market_bar_daily_rows` | history-ingest | Postgres `market.bar_daily` **总行数**，随回补应单调增加 |
| `equitylab_cn_equity_universe_size` | collector | 正在轮询的 A 股标的数 |
| `equitylab_cn_equity_skip` | collector | `1`=已跳过 A 股采集（排障应急），行情会空 |
| `equitylab_history_ingest_gaps_queued` / `*_fill_total` | history-ingest | 本轮**缺口队列**长度；fill 按 status 计回补尝试 |

推荐 PromQL：

```promql
# 报价年龄（秒）——越小越新鲜；休市会变大
time() - equitylab_quote_last_success_unixtime{market="cn_equity"}
time() - equitylab_quote_last_success_unixtime{market="binance"}
rate(equitylab_quotes_written_total[1m])          # 写入吞吐
equitylab_write_gate_pending                        # 写队列积压
equitylab_snapshot_stale_count{sample="seed"}       # 种子发僵只数
equitylab_history_ingest_coverage_ratio             # 日线覆盖率
equitylab_market_bar_daily_rows                     # 日线总行数
```

### Grafana 看板

- **EquityLab 平台**（uid `equitylab-platform`）：抓取存活、QPS、p95、5xx（面板标题与悬停说明为中文）
- **EquityLab 行情**（uid `equitylab-market`）：三区 — **源健康** / **新鲜度** / **覆盖缺口**（面板悬停有中文释义）

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

# 行情新鲜度 / 覆盖（collector:9101 仅 compose 网内；经 Prometheus 查亦可）
docker compose exec -T collector wget -qO- http://127.0.0.1:9101/metrics | rg 'last_success|stale_count|write_gate_pending|quotes_written'
docker compose exec -T history-ingest wget -qO- http://127.0.0.1:9102/metrics | rg 'coverage_ratio|bar_daily_rows'

# 各服务 /metrics（示例）
curl -s http://localhost:3000/metrics | head
curl -s http://localhost:3002/metrics | head

# Grafana
open http://localhost:3003
```
