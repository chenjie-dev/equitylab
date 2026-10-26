# qdb 多语言客户端 Implementation Plan

> **For agentic workers:** 按任务勾选推进；规格见 [2026-10-20-qdb-client-design.md](./2026-10-20-qdb-client-design.md)。

**Goal:** 落地 `packages/qdb-{py,ts,rs}` 并迁 collector / research / market-data / frontend。

**Architecture:** 三语言同形 `Client`；Docker build context 提到仓库根以便 `COPY packages/`。

**Tech Stack:** Python requests；TS 原生 fetch + WebSocket + React hook；Rust reqwest。

**Spec:** `docs/market/2026-10-20-qdb-client-design.md`

## Tasks

- [x] T1 `packages/qdb-py` + collector/research 接入 + Dockerfile context
- [x] T2 `packages/qdb-rs` + market-data 接入
- [x] T3 `packages/qdb-ts` + frontend（`Client` + 本地 hook）
- [x] T4 文档索引 / qdb 行情库 / containers 指针；Compose 冒烟
