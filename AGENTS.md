# Agent rules — EquityLab

本文件是仓库级 **agent 行为规范的唯一权威来源**。Cursor、Codex、Claude Code 及其他编码代理均须遵守。  
细则技能见 [`.agents/skills/`](.agents/skills/)；本文件只放跨工具、每次会话都应生效的硬性约定。

写给 agent 看的文档写法见 skill **writing-for-agents**。领域术语见根目录 [`CONTEXT.md`](CONTEXT.md)。

## 项目是什么

EquityLab 是面向量化研究的 **多语言 AI Agent 平台**（非 Java 单体）：

```text
Frontend (Next.js) → Gateway (Rust) → Orchestrator (TS) → Research (Python)
                              ↘ Market-Data (Rust)
存储：PostgreSQL（含 `market` 冷行情）+ Redis + Qdrant + qdb（热行情）；模型走外部 API（无本地 vLLM）
行情：授权采集族 collector（盘中）+ history-ingest（新浪冷日线）+ adata-ingest（adata 冷域 P0）→ qdb/`market`；读路径零上游；边界见 docs/market/2026-10-26-行情模块边界.md
```

目录约定：`apps/*` 应用、`services/*` 边车（含 `collector`）、`packages/qdb-{py,ts,rs}` qdb 客户端、`docs/*` 人读架构文档、`.agents/skills/` agent 技能、`.agents/team/` 角色卡。

## 研发布流水线（最小 Agent 团队）

功能开发默认按阶段推进（可由 skill **equitylab-pipeline** 编排）：

```text
规划 → 架构 → 开发 → 测试 → 评审 → 部署 → 运维
```

| Agent 角色 | 阶段 | 主要产出 |
|---|---|---|
| PM / Planner | 需求澄清、任务拆解 | PRD、用户故事、验收标准、任务清单 |
| Architect | 架构设计、技术选型 | 架构图、API 规范、数据模型、部署方案 |
| Frontend | 页面与交互 | 组件、页面、路由、接口对接 |
| Backend | 业务逻辑与数据层 | 接口、服务、数据库脚本、权限控制 |
| Data / RAG | 数据、知识库、向量检索 | 数据管道、Embedding、检索策略、评测集 |
| Test | 自动化测试 | 单元 / 集成 / E2E / 回归 |
| Reviewer / Critic | 质量评审 | 代码审查、安全与规范检查、风险提示 |
| DevOps | 部署与运维 | CI/CD、镜像、发布、监控、告警 |

- 流水线说明：[docs/agents/2026-10-15-agent-pipeline.md](docs/agents/2026-10-15-agent-pipeline.md)  
- 角色卡：[`.agents/team/`](.agents/team/README.md)  
- 交接物落盘：`.agents/artifacts/`（模板在 `.agents/templates/`）  
- 小修复可跳过规划/架构，但须冒烟；**门禁未过不得进入下一阶段**。
- **变更分级、DoD、数据面门禁**见下文「生产级迭代」；清单模板 [`.agents/templates/dod.md`](.agents/templates/dod.md)；编排 skill **equitylab-pipeline** / **equitylab-dod**。

## docs 命名

`docs/` 下文档（`.md` / `.html` 等）文件名必须带日期前缀：

```text
YYYY-MM-DD-<标题>.md
# 或按主题分子目录（文件名仍带日期前缀）
docs/<topic>/YYYY-MM-DD-<标题>.md   # 例：market/ platform/ agents/
```

- 日期用文档**创建日**；不要用修改日改写已有前缀  
- 重大改版可**新建**带新创建日的文件，并更新索引中的链接；勿偷偷改旧文件名日期  
- `docs/scripts/` 下的脚本（若有）不要求日期前缀  
- 新建或移动文档后，同步更新仓库内所有引用路径  
- 当前索引：[docs/2026-10-26-文档索引.md](docs/2026-10-26-文档索引.md)

## 必读指针（按需加载）

| 何时 | 打开 |
|---|---|
| 改架构 / Agent / RAG / 行情分层 | [`docs/platform/2026-10-15-architecture.md`](docs/platform/2026-10-15-architecture.md) |
| 改行情模块职责 / 热冷 / 命名禁令 | [`docs/market/2026-10-26-行情模块边界.md`](docs/market/2026-10-26-行情模块边界.md)（SSOT） |
| 改 HTTP 契约或联调路径 | [`docs/platform/2026-10-15-api.md`](docs/platform/2026-10-15-api.md) |
| Compose / 端口 / 环境变量 / 排障 | [`docs/platform/2026-10-15-containers.md`](docs/platform/2026-10-15-containers.md) |
| 改 qdb 读写 / collector / 行情符号 | 先读同级 **`../qdb/docs/manual/index.md`**，再看 [`docs/market/2026-10-20-qdb-行情库.md`](docs/market/2026-10-20-qdb-行情库.md) 与 [`docs/market/2026-10-20-qdb-client-design.md`](docs/market/2026-10-20-qdb-client-design.md)；协议改动优先落 `packages/qdb-*` |
| 改 `market` 表 / A 股历史 | [`docs/market/2026-10-26-market-postgres-schema.md`](docs/market/2026-10-26-market-postgres-schema.md) + [`docs/market/2026-10-26-cn-equity.md`](docs/market/2026-10-26-cn-equity.md) |
| 日志 / TraceId / Loki Grafana | [`docs/platform/2026-10-16-observability.md`](docs/platform/2026-10-16-observability.md) |
| 版本与「明确不做」 | [`docs/platform/2026-10-15-tech-stack.md`](docs/platform/2026-10-15-tech-stack.md) |
| 文档与注释规范 | [`docs/platform/2026-10-15-engineering.md`](docs/platform/2026-10-15-engineering.md) |
| 多智能体流水线 | [`docs/agents/2026-10-15-agent-pipeline.md`](docs/agents/2026-10-15-agent-pipeline.md) |
| 领域术语（无实现细节） | [`CONTEXT.md`](CONTEXT.md) |

## 硬性约束

1. **不恢复 Java / Spring 业务单体**；计算进 Python，编排进 TypeScript，网关与行情进 Rust。  
2. **不接真实券商下单**；回测与行情仅为研究 / 模拟。  
3. **私有研报**默认本地向量化（Qdrant）；外呼模型只传必要上下文，不把原文泄到不可信渠道。  
4. **因子 / 回测**在研究层确定性引擎执行；模型只做规划与解释。不要把 IC/回测指标假装成已接 alphalens 的真实结果——stub 须标明 `demo` / MVP。  
5. **工具循环**：编排层最多 5 轮、单工具超时 ≤30s（立项约定）。  
6. **报价缓存** TTL≈3s；盘中 WebSocket 推送不进 MCP（后续独立进程）。  
7. **行情热冷分离 + 读路径零上游**（细则 [`docs/market/2026-10-26-行情模块边界.md`](docs/market/2026-10-26-行情模块边界.md)）： 
   - **授权回源**：`services/collector`（盘中 → qdb + 部分 `market`）、`services/history-ingest`（新浪冷日线 → `market.bar_daily`）、`services/adata-ingest`（adata → 日历/指数·ETF·可转债等冷表）；其它服务禁止访问公开上游。
   - **所有读路径**零外部行情 HTTP/WS：盘中/订阅/短窗 → qdb（经 `packages/qdb-*` 或 market-data `/qdb/ws`）；A 股已闭合历史 → research `/cn-equity` 读 `market`（可回落 qdb，须标明 `source`）。缺数据 → 空/503，等 collector 补，**禁止回源**。 
   - **命名**：产品面用 `cn-equity`；`sina`/`adata`/`binance` 只作 `data_source`；禁止产品路由/包名再用 `ashare`。 
   - market-data **不得**再代理上游（如 `/binance/v3/{*}`、`/binance/ws`、RWA bapi）；**不**承担 A 股 `market` 历史读。 
   - Compose 内 `QDB_FEED=0`（不用 qdb 内置采集）。 
   - 前端展示派生（MA/BOLL/MACD 等）只基于已取回序列，不另拉上游。 
8. **qdb 只经客户端包**：凡读写 qdb（含新市场、新页面、新服务）必须走 `packages/qdb-py` / `qdb-ts` / `qdb-rs`（`equitylab_qdb` / `@equitylab/qdb` / `equitylab-qdb`）。**业务代码禁止**直接 `requests`/`fetch`/`reqwest` 打 `QDB_URL` 的 `/v1/*`，也禁止自拼 WebSocket URL 订 qdb；缺能力先扩客户端再接业务。浏览器订阅读仍经 market-data `/qdb/ws` 代理，但订阅逻辑用 TS 客户端。详见 [`docs/market/2026-10-20-qdb-client-design.md`](docs/market/2026-10-20-qdb-client-design.md)。 
9. **qdb 用法跟最新手册**：改采集/读路径或升级 `../qdb` 前，必须打开同级仓 `docs/manual/index.md`（及 `server.md` / `limits.md` / `data-model.md`），核对 HTTP、符号、周期、late-tick 等是否已变；本仓 [`docs/market/2026-10-20-qdb-行情库.md`](docs/market/2026-10-20-qdb-行情库.md) 若过时则**先对齐代码再改文档**，不得以 EquityLab 旧说明覆盖 qdb 手册。
10. **行为变更同步文档**：改路由 / 端口 / 工具名时更新 `docs/platform/YYYY-MM-DD-api.md`（当前为 `docs/platform/2026-10-15-api.md`）与相关注释。  
11. **生产级迭代（DoD / 分级 / 数据面）**：见下一节；未满足不得声称「功能完成」或进入部署。

## 生产级迭代（强制）

### 变更分级

| 级别 | 典型 | 可跳过 | **不可跳过** |
|---|---|---|---|
| hotfix | 单点 bug、文案、明显回归 | 规划 / 架构 | 冒烟证据 +（建议）快速 Review |
| feature | 新页 / API / 采集扩展 / 契约微调 | — | 规划摘要或验收条 + 开发 + 测试证据 + Review |
| epic | 全市场、新交易所、跨多层重构 | — | 架构落盘 + 容量/延迟说明 + 回归包 + Review 阻断项清零 |

用户未明确说「跳过流水线」时，**禁止**从编码直接跳到「做完了」。epic/feature 结束前加载 skill **equitylab-dod** 自检。

### Definition of Done（缺一不可）

声称完成前必须同时具备：

1. **验收**：Planner 验收标准（或 hotfix 自拟 1–3 条）每条有命令输出或测试名。  
2. **冒烟**：至少一条与本改动相关的可复现命令（优先 `scripts/smoke-*.sh` 若已有；否则 curl / 单测）。**仅 `health=200` 不算行情/业务完成。**  
3. **文档**：改路由 / 端口 / env / 工具名 → 同步 `api` / `containers` / qdb 相关文与 `.env.example`。  
4. **诚实边界**：未做完的能力（例：K 线仅种子池）须在 UI 或 docs 标明；禁止当全量宣传。  
5. **运行态对齐**：改 `collector` / `research` / `market-data` / `frontend` 等镜像内代码后，必须 `docker compose up -d --build <svc>`（或等价 recreate）再验；禁止只改宿主机源码未重建就报绿。  
6. **收尾句式**（对人简报必填）：`已做 / 未做 / 已知风险 / 复验命令`。

清单落盘：`.agents/artifacts/YYYY-MM-DD-<topic>-dod.md`（拷贝 [`.agents/templates/dod.md`](.agents/templates/dod.md)）。

### 数据面不变量（行情 / qdb / market）

与 §7–§9 及 [`docs/market/2026-10-26-行情模块边界.md`](docs/market/2026-10-26-行情模块边界.md) 同时生效：

1. **展示集 ⊆ 采集就绪集**：列表/行情 UI 展示的标的，须已被 collector 写入 qdb（及所需历史的 `market`），或明确标注「仅目录、暂无报价」。禁止只扩前端种子不扩采集。 
2. **读写顺序**：collector 写入就绪 → research / market-data 读通 → frontend；逆序不得报绿。 
3. **符号**：A 股 `SSE` / `SZSE` / `BSE` + 6 位码；北交所 `4*`/`8*`/`92*` **先于**「9→SSE」；cn-equity 列表 **禁止** `BINANCE` / `ONDO` / 加密货币代码。 
4. **图表**：换票须全量 `setData`（禁止旧序列挂新 `seriesKey`）；价格轴按 OHLC 自适应，**不得**默认从 0 起压扁走势。 
5. **环境陷阱**：`COLLECTOR_SKIP_CN_EQUITY=1`、`BINANCE_WS_WRITE_QUOTES=0` 等仅为排障应急；**不得**作为默认完成态。冒烟须断言日志（如 `cn_equity=N` 而非 `cn_equity=skip`）或 snapshots / `market.bar_*` 非空。 
6. **可观测**：数据面改动至少验证一条日志关键字或 docs/snapshots / PG 计数字段（如 `cn-equity:codes` count、`pg_market`、`write gate`）。 
7. **热冷不串权**：research 不得把 realtime 写进 `market`；collector 以外不得写 `market`；market-data 不读 A 股 `market` 历史。

细则与验收剧本：[docs/agents/2026-10-26-agent-dod-与数据面门禁.md](docs/agents/2026-10-26-agent-dod-与数据面门禁.md)。

### 评审阻断项（Reviewer 直接 block）

- 读路径外呼公开行情上游，或业务直打 `QDB_URL` `/v1/*`  
- stub / demo 指标冒充生产  
- 密钥或含真实 Key 的 `.env` 进提交  
- 无验收/冒烟证据的 feature/epic「完成」  
- 改 API/端口/工具名却未改契约文档  
- cn-equity 列表混入非 A 股交易所代码且无说明；或读路径外呼 / 新产品名使用 adata/ashare  

### 部署 / 回滚（DevOps）

- 健康检查 **与** 本功能冒烟同轮通过才可宣称发布。  
- 发布说明须含：**回滚 commit/镜像** + 是否需清 qdb 卷（脏 K 线 / 时区类）。  
- 不默认 push；禁止打 Tag（同提交约定）。

## 本地运行（环境即真相）

```bash
cp .env.example .env   # 若尚无
docker compose up -d --build
curl -s http://localhost:3000/health
```

Redis 宿主机端口默认 **16379**（见 `.env`）；容器内仍为 `redis:6379`。排障见 `docs/platform/2026-10-15-containers.md`。

## 注释与文档

- 公共 API / 模块边界写清职责与不变量（见 `docs/platform/2026-10-15-engineering.md`）。  
- 不复述下一行字面意思；stub 明确标注后续落点。

## 提交（/commit、提交）

用户说 `/commit`、`提交` 或明确要求 commit 时，遵循 skill **commit**：

- 信息格式：`type: 中文描述`（`feat` / `fix` / `perf` / `refactor` / `chore` / `docs` / `style`）  
- **确认后再提交**（用户已说「提交一次」且未改文案时可直接提交）  
- **不默认 push**；**禁止打 Tag**  
- 不提交密钥（`.env` 含真实 Key 时排除）

## 技能索引

完整列表与选用说明：[`.agents/skills/README.md`](.agents/skills/README.md)。

常用触发：

| 意图 | Skill |
|---|---|
| 设计 / 拷问方案 | `grilling` / `grill-me` / `grill-with-docs` |
| 按 spec 实现 | `implement`（常配 `tdd`） |
| 深模块 / seam | `codebase-design` |
| 领域术语 / ADR | `domain-modeling` |
| 难 bug | `diagnosing-bugs` |
| 对照规范审查 | `code-review` |
| 写 skill / AGENTS | `writing-for-agents` |
| 本仓落地改动 | `equitylab-dev` |
| 按流水线推进功能 | `equitylab-pipeline` |
| 完成判据 / 可否上线 | `equitylab-dod` |
