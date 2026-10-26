# Backend Agent

## 阶段

开发（与 Frontend / Data-RAG 可并行）

## 触发

任务涉及 Gateway / Orchestrator / Market-Data / MCP / PG 脚本（非纯向量）。

## 输入

- API 契约、任务清单  
- `equitylab-dev`、`rust-async-patterns`、`redis-core`、`fastapi`、`langgraph-fundamentals`、`mcp-builder`

## 步骤

1. 确认落点：  
   - 鉴权限流反代 → `services/gateway`  
   - Agent 图/工具 → `apps/orchestrator`  
   - 行情 Provider/缓存 → `services/market-data`  
   - MCP → `apps/mcp-server`  
   - 因子/回测 API → `apps/research`（与 Data-RAG 协作）  
2. 工具必须进 `TOOL_REGISTRY`；行情只经 `MarketDataProvider`。  
3. 编排保持 `route→plan→execute→synthesize` 形态；新增节点写清 state 字段。  
4. Redis key 带 `equitylab:` 前缀；报价 TTL=3s。  
5. 错误消息可行动（对齐 mcp-builder）。  
6. 契约变更同步 `docs/*-api.md`。

## 产出

接口、服务代码、DB 脚本、权限/限流相关变更。

## 完成判据

- [ ] 健康检查仍绿  
- [ ] 相关 curl 冒烟通过（见 `equitylab-dev`）  
- [ ] stub 标 `demo` / mode  

## 不做

前端样式；擅自上实盘交易；把计算塞进编排层用 JS「假装」IC。

## 推荐 skills

| 优先级 | Skill | 源 / 热度 |
|---|---|---|
| 必用 | `equitylab-dev`、`langgraph-fundamentals`、`mcp-builder` | 本仓 / langchain / anthropics **~181K★** |
| 必用 | `fastapi`、`rust-async-patterns`、`rust-best-practices` | fastapi **~103K★**；wshobson **~41K★**；Apollo |
| 必用 | `redis-core`、`supabase-postgres-best-practices` | redis 官方；supabase |
| 辅助 | `multi-stage-dockerfile` | awesome-copilot **~40K★** |

详见 [docs/agents/2026-10-15-role-skills.md](../../docs/agents/2026-10-15-role-skills.md)。
