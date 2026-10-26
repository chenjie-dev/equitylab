# qdb 多语言客户端（独立包）设计

> 创建日：2026-10-20。权威 HTTP/WS 契约以同级仓 `../qdb/docs/manual/` 为准；本文件只定 EquityLab 包边界与迁移顺序。

## Intent

把散落在 collector / market-data / research / frontend 的 qdb HTTP·WS 调用收成 **三套独立包**（Python / TypeScript / Rust），同一契约、读写齐全，方便以后复用与对齐手册变更。

## 硬性约定（后续一律遵守）

- **读路径零外呼**：frontend / research / market-data / orchestrator **禁止**直查币安、新浪、AlphaFeed 等公开行情 HTTP/WS；一律读 qdb（经本包）或经 market-data 已 qdb 化的 REST/`/qdb/ws`。缺数据空返回或 503，由 collector 补写，**不回源**。  
- **以后增加任何 qdb 用法**（新交易所、新页面、新 sidecar、脚本）**都必须走这些 client**。  
- **业务代码禁止直连** qdb：不得在业务层手写 `QDB_URL` + `/v1/quotes|trades|docs|snapshots|klines|ws`。  
- 缺方法 / 缺语言绑定：先改 `packages/qdb-*`，再改调用方。  
- 写路径调用纪律不变：只有 collector（及其明确授权的采集进程）可回源并调用写 API；读路径只用读表面。

## Goals

- 读：`GET /v1/snapshots`、`/v1/klines`（含 `limit` / `endTime`）、`/v1/docs`；`GET /v1/ws`（SELECT … SUBSCRIBE）
- 写：`POST /v1/quotes`（`last` + 可选 `bid_px`/`ask_px`）、`/v1/trades`、`/v1/docs`（含 wait/ready 探测）
- 三语言公共表面尽量同名：`Client`、`wait_ready`、`snapshots`、`klines`、`get_doc` / `put_docs`、`post_quotes`、`post_trades`、`subscribe`
- 配置只认 `QDB_URL`（缺省 Compose 内 `http://qdb:9090`）；浏览器订阅读再认 `QDB_WS_PROXY`（缺省 `ws://localhost:3002/qdb/ws`）
- 价格整数 `last` / `bid_px` / `ask_px`：包内提供 `PRICE_SCALE=10000` 与 `scale` / `unscale` 工具
- **不封装**（本仓未用）：`GET /v1/changes`、集群/复制（`/v1/replicate`、`/v1/info`…）；需要时再扩包

## Non-goals

- 不在客户端做币安 K 线折叠、A 股代码映射、RWA 解析（仍属各服务 adapter）
- 不把 market-data 的 `/qdb/ws` 代理迁进包（代理仍是服务职责；TS 包只做客户端）
- 不发布到公共 npm/crates.io/PyPI（workspace / path 依赖即可）
- 不恢复「读路径回源公开上游」

## Anti-goals

- 三套 API 形状长期漂移（改一处手册却只改一种语言）
- 写接口暴露给前端或 research 默认路径（包可做写，**调用纪律**仍是 collector 唯一回源）

## Constraints

- AGENTS：行情只经 qdb；collector 唯一写；改契约前对 `../qdb/docs/manual/server.md` / `limits.md`
- Compose 内 `QDB_FEED=0`
- 网关不升级 WebSocket；浏览器订阅读走 market-data `:3002`

## Layout（独立包）

```text
packages/
  qdb-py/          # equitylab-qdb（Python）
  qdb-ts/          # @equitylab/qdb（TypeScript）
  qdb-rs/          # equitylab-qdb（Rust crate）
```

| 包 | 消费者（首批迁移） |
|---|---|
| `qdb-py` | `services/collector`、`apps/research` |
| `qdb-ts` | `apps/frontend`（含 React hook `useSnapshot`） |
| `qdb-rs` | `services/market-data` |

共享说明（非代码）：`packages/README.md` 指向本设计 + qdb 手册；契约变更时三包与 `docs/market/2026-10-20-qdb-行情库.md` 同步改。

## 接口草图（三语言同形）

```text
Client(base_url = env QDB_URL)
  wait_ready(timeout) -> bool
  snapshots(symbols?: string[]) -> Snapshot[]
  klines(symbol, period, limit?, endTimeMs?) -> Kline[]   # HTTP 窗口读
  get_doc(key) -> json | null
  put_docs(items: {key, value}[]) -> written
  post_quotes(items) -> written   # last/bid_px/ask_px 为 scale 整数或提供 helper
  post_trades(items) -> written
  subscribe(sql, handlers) -> close()   # Node/浏览器：浏览器默认连 QDB_WS_PROXY
  # Rust 另：ws_url() → qdb GET /v1/ws；klines_window(...)
```

TS 另导出：

- `PRICE_SCALE` / `scale` / `unscale`
- `Client.subscribe`（浏览器订阅读）
- React hook：`apps/frontend/.../useQdbSnapshot` 薄封装（避免 Next 解析 peer `react`）；包内可选 `@equitylab/qdb/react` 供非 Next 复用

Rust：`equitylab_qdb::Client`（reqwest + 可选 tungstenite）；market-data 的 `qdb_read` / `qdb_ws` 改为调 crate 或薄封装。

Python：同步 `requests` 客户端即可（collector / research 现状）；WS subscribe 可选（collector 当前不订阅读）。

## 迁移顺序

1. ~~落地三包骨架 + 最小读写冒烟（对本地 qdb）~~
2. ~~collector → `qdb-py`（写 quotes/trades/docs + wait）~~
3. ~~research `cn_equity/qdb_client.py` → 依赖 `qdb-py`（行映射留在 research）~~
4. ~~market-data → `qdb-rs`（`qdb_read` / `qdb_ws`；上游 URL 由 crate `ws_url`）~~
5. ~~frontend → `@equitylab/qdb`（`useQdbSnapshot` / `useQdbKlines` / `useQdbSnapshots`）~~
6. 手册对齐时同步 `docs/market/2026-10-20-qdb-行情库.md`、containers、本设计（就地改）

## 验证

```bash
# 包级：对 Compose qdb
curl -s http://localhost:9090/v1/snapshots | head -c 200
# 迁移后：collector 仍写、前端 /qdb/ws 仍有 row、research /cn-equity/quotes 仍 200
```

## Builder 可自决

- 各包内部目录与测试框架
- Rust 是否 `workspace` 成员、TS 是否用 `workspace:` / `file:` 依赖
- Python 用 `pip install -e packages/qdb-py` 或复制进镜像的路径策略（Compose Dockerfile 需能装到）
