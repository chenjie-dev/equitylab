# 币安现货公开行情模块

> 创建日：2026-10-16。代码落在 `services/market-data/src/exchanges/binance/`；无需 API Key。

## 模块边界

```text
exchanges/                 ← 多交易所 seam（登记 /exchanges）
  binance/                 ← 币安深模块
    mod.rs                 ← 对外：ID / BinanceModule::{router, provider}
    client.rs              ← REST/WS 基址
    http.rs · ws.rs        ← 原生路由
    provider.rs            ← 适配统一 MarketDataProvider
```

挂载：`/exchanges/binance/*`（规范）与 `/binance/*`（兼容别名）。目录：`GET /exchanges`。

## 能力

| 类型 | 路径 | 说明 |
|---|---|---|
| 交易所目录 | `GET /exchanges` | 已注册交易所列表 |
| 模块目录 | `GET /exchanges/binance` 或 `/binance` | 币安能力清单 |
| REST | `.../ping` `time` `exchangeInfo` `ticker/*` `depth` `trades` `klines` … | 现货公开面 |
| REST 透传 | `GET .../v3/{*path}` | 上游 `/api/v3/...`（仅 GET） |
| WebSocket | `WS .../ws?streams=` | 公开流代理（直连 :3002） |
| 统一接口 | `/quotes` `/bars` `/search` | `MARKET_PROVIDER=binance` |

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `BINANCE_REST_URL` | `https://data-api.binance.vision` | REST 基址 |
| `BINANCE_WS_URL` | `wss://data-stream.binance.vision` | WS 基址 |
| `MARKET_PROVIDER` | `mock` | 设为 `binance` 时统一 Quote/Bars 走币安 |

符号：`BTCUSDT`（也接受 `btc/usdt`）。

## 调用示例

经网关（HTTP）：

```bash
curl -s http://localhost:3000/api/market/exchanges
curl -s http://localhost:3000/api/market/exchanges/binance | head
curl -s 'http://localhost:3000/api/market/binance/ticker/24hr?symbol=BTCUSDT' | head -c 200
curl -s 'http://localhost:3000/api/market/exchanges/binance/klines?symbol=BTCUSDT&interval=1h&limit=3'
```

`MARKET_PROVIDER=binance` 时：

```bash
curl -s http://localhost:3000/api/market/quotes/BTCUSDT
curl -s 'http://localhost:3000/api/market/bars/ETHUSDT?period=1h&count=24'
```

WebSocket（**直连** market-data，网关不升级 WS）：

```bash
# 例：websocat
websocat 'ws://localhost:3002/binance/ws?streams=btcusdt@trade/btcusdt@ticker'
```

## 前端

币安风格现货台：http://localhost:3001/markets（BFF `/api/market/*` → 网关）。

## 边界

- 仅现货公开数据；不做合约/期权、签名账户、下单。
- `historicalTrades` 等需 Key 的接口不保证可用。
- 双均线回测默认仍可用 mock；要对加密货币回测时把 Provider 切到 `binance` 并传 `BTCUSDT` 等符号。
