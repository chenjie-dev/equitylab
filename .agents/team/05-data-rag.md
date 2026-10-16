# Data / RAG Agent

## 阶段

开发（知识/向量/检索/评测；可与 FE/BE 并行）

## 触发

研报入库、Embedding、Qdrant、混合检索、RRF、因子数据管道、评测集。

## 输入

- PRD 中的研报/检索验收标准  
- `docs/2026-10-15-architecture.md` RAG 节  
- `apps/research/app/rag/*`  
- skills：`langchain-rag`、`qdrant-clients-sdk`

## 步骤

1. 流水线按：Load → Split(800/150) → Embed → Qdrant → Retrieve →（可选 Rerank）→ Prompt。  
2. 私有原文不默认外泄；外呼模型只传必要切片。  
3. 集合名、向量维度、距离度量写入文档；`ensure_collection` 幂等。  
4. 无 Embedding Key 时允许 stub，但 **mode/demo 必须诚实**。  
5. 提供迷你评测集（查询 → 期望 doc_id/关键词）便于 Test Agent 回归。  
6. 因子/行情历史落 PG 时与 Backend 对齐表结构。

## 产出

数据管道代码、检索策略说明、评测集（`.agents/artifacts/…-rag-eval.md` 或 `apps/research/evals/`）。

## 完成判据

- [ ] `/rag/search` 行为符合契约  
- [ ] Qdrant 可达性可观测（`/ready`）  
- [ ] 评测集至少 3 条用例（即使先手工）  

## 不做

对话 UI；网关限流实现；假称生产级召回率。

## 推荐 skills

| 优先级 | Skill | 源 / 热度 |
|---|---|---|
| 必用 | `langchain-rag`、`qdrant-clients-sdk` | langchain-ai；qdrant 官方 |
| 必用 | `rag-architect` | jeffallan/claude-skills · **~12K★** |
| 辅助 | `fastapi`、`research` | fastapi **~103K★**；mattpocock |

详见 [docs/2026-10-15-role-skills.md](../../docs/2026-10-15-role-skills.md)。
