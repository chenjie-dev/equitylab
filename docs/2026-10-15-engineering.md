# 工程约定：文档与代码注释

本文约定 EquityLab 仓库内**文档**与**代码注释**的写法，保证跨语言（Rust / TypeScript / Python）可读一致。

## 1. 文档分层

| 层级 | 位置 | 写什么 |
|---|---|---|
| 快速开始 | `README.md` | 架构一句话、启动、端口、文档索引 |
| 文档索引 | `docs/YYYY-MM-DD-文档索引.md` | 指向各带日期正文 |
| 领域架构 | `docs/YYYY-MM-DD-architecture.md` | 链路、Agent、RAG、模型路由、关键约束 |
| 技术 SSOT | `docs/YYYY-MM-DD-tech-stack.md` | 版本与明确不做的事 |
| 运行时 | `docs/YYYY-MM-DD-containers.md` | Compose、端口、环境变量、排障 |
| 接口契约 | `docs/YYYY-MM-DD-api.md` | 对外/对内 HTTP API |
| 历史 | `docs/YYYY-MM-DD-migration.md` | 去 Java 改造记录 |
| 本文件 | `docs/YYYY-MM-DD-engineering.md` | 注释与贡献约定 |
| Agent 硬约定 | `AGENTS.md` | 每次会话生效的跨工具规则 |
| 领域术语 | `CONTEXT.md` | 术语边界（无实现） |
| Agent Skills | `.agents/skills/` | 可调用工作流（见该目录 README） |
| Agent 团队 / 流水线 | `.agents/team/` + `docs/*-agent-pipeline.md` | 规划→…→运维门禁与角色卡 |
| 流水线交接物 | `.agents/artifacts/` | PRD / 评审 / 发布说明等 |

原则：**行为变更同步改文档**；版本升级同步改带日期的 tech-stack 文档（或新建带**创建日**前缀的修订稿并更新索引）。  
`docs/` 下 `.md` / `.html` 文件名必须带 `YYYY-MM-DD-` 前缀（见 `AGENTS.md`）。  
写「给 agent 看的文档」时遵循 skill `writing-for-agents`。

## 2. 注释写什么、不写什么

**要写**

- 模块职责与边界（`//!` / 文件头 / 包 docstring）
- 非显然的不变量、安全/成本约束（私有研报不外泄、工具轮次上限、缓存 TTL）
- 公共 API 的参数含义、错误语义、后续 TODO 落点
- 「为什么这样路由 / 为什么 stub」等决策

**不要写**

- 复述下一行代码字面意思（如「把 x 赋给 y」）
- 过期的假 TODO；真实待办写清前置条件
- 大段粘贴立项原文进源码（放 docs）

## 3. 各语言格式

### Rust

-  crate / 文件：`//!` 模块文档  
- 公开类型、trait、函数：`///`  
- 复杂分支：短行内 `//`  
- 公开项尽量可被 `cargo doc` 生成

### TypeScript

- 文件头块注释说明服务职责  
- 导出函数 / 工具注册：JSDoc（`@param` / `@returns` 在非显然时使用）  
- Zod schema 旁注明业务含义

### Python

- 模块 docstring（第一行摘要 + 空行 + 细节）  
- 公共路由与领域函数：Google 风格或简短说明 + Args/Returns（复杂时）  
- Pydantic 模型用 `Field(description=...)` 补契约

### SQL

- 文件头说明阶段与用途  
- 表级别注释写清主键语义与业务用途

## 4. 语言选择

- **仓库文档**：中文为主（与立项/协作一致）  
- **代码注释**：中文说明业务与约束；专有名词（Agent、RAG、Provider）可保留英文  
- **日志 / 指标名**：英文短标识，便于观测栈检索

## 5. MVP 与后续实现的标注

对占位实现统一标注，例如：

- Rust：`/// TODO(mvp): …`  
- TS/Python：注释或 docstring 中写 `MVP stub` / `后续：…`

避免读者把 deterministic stub 当成生产计算结果。
