# EquityLab packages

| 包 | 说明 |
|---|---|
| [`qdb-py`](./qdb-py) | Python qdb 读写客户端（`equitylab_qdb`） |
| [`qdb-ts`](./qdb-ts) | TypeScript（`@equitylab/qdb`） |
| [`qdb-rs`](./qdb-rs) | Rust crate（`equitylab-qdb`） |
| [`market-py`](./market-py) | Python Postgres `market` 冷库写 + 采集侧 sina/符号（`equitylab_market`） |

**约定：**

- 访问 qdb **只走** `qdb-*` client；业务禁止直连 `QDB_URL` / 自拼 `/v1/*`。
- 写 Postgres `market` schema **只走** `equitylab_market.pg`（collector / history-ingest）；读历史由 research `cn_equity.pg_client`。
- 缺能力先改包再接业务（见根目录 `AGENTS.md` 与 [行情模块边界](../docs/market/2026-10-26-行情模块边界.md)）。

权威 qdb HTTP/WS：同级仓 `../qdb/docs/manual/`。
