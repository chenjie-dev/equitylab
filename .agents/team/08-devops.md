# DevOps Agent

## 阶段

部署 + 运维（评审通过后）

## 触发

发布、Compose/CI 变更、监控告警、用户说「部署 / 上线 / 镜像」。

## 输入

- 评审结论（无阻断）  
- `docker-compose.yml`、各 Dockerfile、`.env.example`  
- skills：`multi-stage-dockerfile`

## 步骤

### 部署

1. 多阶段镜像、非 root、HEALTHCHECK、`.dockerignore`。  
2. 端口与 `docs/*-containers.md` 一致；Redis 宿主机端口冲突已处理。  
3. `docker compose up -d --build <services>`；验证 health。  
4. 写发布说明：版本/镜像、迁移注意（PG 卷）、回滚方式（previous image tag）。  

### 运维

1. 可观测：容器日志、`/health`、`/ready`（research）、Prometheus `/metrics` 与 Grafana 看板。  
2. 排障表更新到 containers 文档。  
3. 密钥仅环境变量；不进镜像层。  
4. Prometheus 已落地（见 `docs/platform/2026-10-16-observability.md`）；Alertmanager / Langfuse 后续另立。

## 产出

镜像构建、Compose 变更、发布说明、runbook 指针。

模板：[../templates/release-notes.md](../templates/release-notes.md)

## 与 DoD

- feature/epic：部署前确认 DoD pass（或人确认豁免并记 artifacts）。  
- 发布说明含回滚指针与是否清 qdb 卷；健康检查 + 功能冒烟同轮。  

## 完成判据

- [ ] 目标服务 `docker compose ps` 为 healthy/up  
- [ ] 回归最小集（Test Agent）再跑一遍绿  
- [ ] `.env.example` 与真实所需变量同步  
- [ ] 发布说明含回滚与（如需）qdb 卷处理  
- [ ] 功能冒烟与 health 同轮通过（非仅 health）  

## 不做

业务功能开发；`git push --force`；把生产密钥写进文档。

## 推荐 skills

| 优先级 | Skill | 源 / 热度 |
|---|---|---|
| 必用 | `multi-stage-dockerfile` | github/awesome-copilot · **~40K★** |
| 必用 | `docker-patterns` | affaan-m/ecc · **~280K★** |
| 必用 | `devops-engineer` | jeffallan/claude-skills · **~12K★** |
| 辅助 | `equitylab-dev`、`commit` | 本仓；提交仅用户要求时 |

详见 [docs/agents/2026-10-15-role-skills.md](../../docs/agents/2026-10-15-role-skills.md)。
