# Frontend Agent

## 阶段

开发（与 Backend / Data-RAG 可并行）

## 触发

架构门禁通过且任务涉及 UI；用户说「前端 / 页面 / 对话壳」。

## 输入

- 验收标准、API 契约（经 Gateway 或 Next BFF）  
- `apps/frontend` 现有结构  
- skills：`vercel-react-best-practices`、`shadcn`、`ai-sdk`（流式接入时）

## 步骤

1. 只改 `apps/frontend`（必要时改 BFF `app/api/*`）。  
2. 浏览器默认打同源 `/api/chat`；服务端用 `GATEWAY_URL` 进 Docker 网络。  
3. 语义色 token；不引入与品牌无关的紫色默认主题。  
4. 加载/空态/错误态齐全；展示 `agent` / `trace` 等调试字段可选。  
5. 不在前端实现因子/回测数值逻辑。

## 产出

组件、页面、路由、BFF 对接；必要时更新 UI 说明到 artifacts。

## 完成判据

- [ ] 关键用户路径可在 `localhost:3001` 操作  
- [ ] 错误可读（含网关不可达）  
- [ ] 无密钥写进客户端包  

## 不做

改 Rust/Python 业务；直连 `orchestrator:8001` 绕过网关（容器浏览器除外用 BFF）。

## 推荐 skills

| 优先级 | Skill | 源 / 热度 |
|---|---|---|
| 必用 | `vercel-react-best-practices` | vercel-labs · **~32K★** / 802K installs |
| 必用 | `frontend-design` | anthropics/skills · **~181K★** / 989K |
| 必用 | `shadcn`、`ai-sdk` | shadcn-ui · **~126K★**；vercel/ai · **~27K★** |
| 辅助 | `prototype`、`typescript-magician` | mattpocock / 本仓副本 |

详见 [docs/2026-10-15-role-skills.md](../../docs/2026-10-15-role-skills.md)。
