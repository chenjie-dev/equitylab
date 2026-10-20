# EquityLab packages

| 包 | 说明 |
|---|---|
| [`qdb-py`](./qdb-py) | Python qdb 读写客户端（`equitylab_qdb`） |
| [`qdb-ts`](./qdb-ts) | TypeScript（`@equitylab/qdb`） |
| [`qdb-rs`](./qdb-rs) | Rust crate（`equitylab-qdb`） |

**约定：** 以后凡访问 qdb **只走上述 client**；业务代码禁止直连 `QDB_URL` / 自拼 `/v1/*`。缺能力先改包再接业务（见根目录 `AGENTS.md` 硬性约束与 [qdb-client-design](../docs/2026-10-20-qdb-client-design.md)）。

权威 HTTP/WS：同级仓 `../qdb/docs/manual/`。
