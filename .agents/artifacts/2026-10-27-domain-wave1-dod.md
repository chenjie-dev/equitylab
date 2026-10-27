# DoD：Wave1 职责对齐（ashare 清除 + 文档）

- 日期：2026-10-27
- 级别：hotfix
- 关联：领域缺口与职责计划 Wave 1

## 已做 / 未做 / 已知风险 / 复验命令

- 已做：删除 `apps/research/app/ashare`、`apps/frontend/app/api/ashare`；CONTEXT 采集族含 adata-ingest；边界图与 §3.2c「不做读 UI」已改；前端 hint 去掉产品化 adata-ingest；测试断言包目录不存在。
- 未做：Wave 2–4（另条）。
- 已知风险：无。
- 复验命令：见同轮 smoke。

## 验收对照

| 验收标准 | 结果 | 证据 |
|---|---|---|
| 无 ashare 包/BFF | pass | 目录已删 |
| CONTEXT/边界同步 | pass | 采集族 + 架构图 + 默认不做 |
| cn-equity 仍通 | pass | 冒烟 |
