---
name: equitylab-dev
description: >-
  Develop or change the EquityLab multi-service Agent platform (Rust gateway/market-data,
  TS orchestrator/frontend, Python research, Compose). Use when editing apps/*, services/*,
  docker-compose, dated docs under docs/ (api/architecture/containers), tools/RAG/quotes,
  or when the user mentions EquityLab MVP、编排层、研究层、行情、网关.
---

> **中文说明**：在 EquityLab 多服务 Agent 平台上做功能/修复时使用。先对齐分层与契约，再改对应服务；stub 须标明；改端口/路由同步文档。

# EquityLab 开发

## 开始前（completion：能指认要改的一层）

1. 读根目录 [`AGENTS.md`](../../../AGENTS.md) 硬性约束与 [`CONTEXT.md`](../../../CONTEXT.md) 术语。  
2. 按改动类型打开指针文档（不要整库盲搜）：  
   - 行为 / Agent / 工具 → `docs/2026-10-15-architecture.md`（或索引中的最新架构文）  
   - HTTP 路径 / 请求体 → `docs/2026-10-15-api.md`  
   - 端口 / Compose / env → `docs/2026-10-15-containers.md`  
   - 行情模块职责 / 热冷 / 命名 → **`docs/2026-10-26-行情模块边界.md`（SSOT）**  
   - 行情 / qdb 协议 → **先**同级 `../qdb/docs/manual/index.md`，再 `docs/2026-10-20-qdb-行情库.md` 与 `docs/2026-10-20-qdb-client-design.md`；业务访问 qdb **只经** `packages/qdb-*`  
   - A 股历史表 → `docs/2026-10-26-market-postgres-schema.md`；产品面 → `docs/2026-10-26-cn-equity.md`  

3. 确认改动落在哪一层，**只改该层及必要契约**：

| 改动意图 | 目录 |
|---|---|
| 对话 UI | `apps/frontend` |
| 意图路由、TOOL_REGISTRY、轮次/超时 | `apps/orchestrator` |
| RAG / 因子 / 回测 | `apps/research` |
| 中国 A 股读面 | `apps/research/app/cn_equity`（`/cn-equity`；历史 `market` + 盘中 qdb） |
| 限流、反代、鉴权 | `services/gateway` |
| 币安/RWA Quote/Bars、`/qdb/ws` | `services/market-data`（只读 qdb；不读 A 股 `market`） |
| 唯一回源 | `services/collector` → qdb（热）+ `market`（冷）；经 `equitylab_qdb` / `pg_market` |
| qdb 客户端 | `packages/qdb-{py,ts,rs}` — 新用法先扩包 |
| 热行情库用法 | **权威**：`../qdb/docs/manual/*`；本仓落点：`docs/2026-10-20-qdb-行情库.md` + client-design |
| 冷行情表 | `infra/postgres/migrations/*market*` + init 挂载（已有卷须手工迁移） |

## 实现规则

- **深模块**：行情只经 `MarketDataProvider`；新数据源加 Provider，不改 handler 业务分支堆叠（见 skill `codebase-design`）。  
- **读路径零上游 + 热冷不串权**：除 `services/collector` 外禁止直查公开上游；盘中走 qdb，A 股历史走 `market`（经 `/cn-equity`）。见 `docs/2026-10-26-行情模块边界.md` 与 `AGENTS.md` §7。缺数据空/503。不要复活上游透传，或把 sina/adata 当成产品模块名。  
- **工具三要素**：`name` + `description` + Zod/schema + `run`；编排层不得绕过注册表直打下游（调试除外）。  
- **Stub 诚实**：演示 IC/回测/RAG 必须带 `demo` / mode=stub 或等价标注；禁止写成已生产可用。  
- **缓存与限流**：报价写缓存默认 TTL 3s；网关限流按 IP 滑动窗口——改默认值时更新 `.env.example` 与 `docs/2026-10-15-containers.md`。  
- **前缀代理**：网关对 `/api/market`、`/api/research` 剥前缀；`/api/chat` 保留完整路径。改路径时两端一起改并更新 `docs/2026-10-15-api.md`。  
- **docs 命名**：`docs/` 下新建文档必须 `YYYY-MM-DD-<标题>.md`（创建日）；见根目录 `AGENTS.md`。  
- **qdb 最新优先**：动 collector / `qdb_read` / ashare 读路径前，对照 `../qdb/docs/manual/server.md` 与 `limits.md`；发现契约变更则改代码并同步本仓 qdb 文档，禁止沿用过时路径。  
- **qdb 只经客户端**：业务层禁止直连 `QDB_URL`；读写一律 `packages/qdb-*`（见 `AGENTS.md` 硬性约束 §8）。  
- **数据面顺序**：collector 写入就绪 → 读 API → UI；展示集 ⊆ 采集或标明「仅目录」。  
- **重建再验**：改镜像内代码后必须 `docker compose up -d --build <service>`，禁止未 recreate 报绿。

## 验证（completion：至少一条相关冒烟变绿）

优先用已运行的 Compose：

```bash
curl -s http://localhost:3000/health
curl -s http://localhost:3000/api/market/quotes/600519.SH
curl -s -X POST http://localhost:3000/api/chat \
  -H 'content-type: application/json' \
  -d '{"message":"<与改动相关的中文问题>"}'
```

行情改动另验 snapshots / ashare quotes（见 `docs/2026-10-26-agent-dod-与数据面门禁.md`）。**仅 health 不够。**

仅改单服务时，可只重建该服务：`docker compose up -d --build <service>`。

## 收尾

- 公共 API / 模块头注释按 `docs/2026-10-15-engineering.md` 补齐。  
- feature/epic：走 skill **equitylab-dod**（或 pipeline 收尾）。  
- 用户要求提交时走 skill `commit`。  
- 大设计分歧先用 `grilling` / `grill-with-docs`，再实现。  
- 简报：`已做 / 未做 / 已知风险 / 复验命令`。
