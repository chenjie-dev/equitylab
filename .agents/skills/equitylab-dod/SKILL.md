---
name: equitylab-dod
description: >-
  EquityLab Definition of Done and production-iteration gates (change tier, smoke
  evidence, data-plane checks, honest scope). Use before claiming a feature done,
  ending equitylab-pipeline, or when the user says DoD/完成判据/生产级迭代/可否上线.
---

> **中文说明**：功能收尾强制 DoD 自检；对照 AGENTS「生产级迭代」与模板 `.agents/templates/dod.md`。

# EquityLab DoD

## 权威

- [`AGENTS.md`](../../../AGENTS.md)「生产级迭代」  
- 清单模板：[`../../templates/dod.md`](../../templates/dod.md)  
- 细则：[`docs/agents/2026-10-26-agent-dod-与数据面门禁.md`](../../../docs/agents/2026-10-26-agent-dod-与数据面门禁.md)

## 过程（completion：artifacts 有勾选 DoD 或简报含四要素）

1. **定级别**：hotfix | feature | epic（见 AGENTS 分级表）。  
2. **拷贝模板** → `.agents/artifacts/YYYY-MM-DD-<topic>-dod.md`，逐项填。  
3. **跑冒烟**：与本改动相关；行情类禁止只靠 `/health`。  
4. **数据面**（若动 collector / qdb / cn-equity / spot）：按 AGENTS 数据面不变量勾选；改过的服务必须已 rebuild。  
5. **简报**对人输出：`已做 / 未做 / 已知风险 / 复验命令`。  
6. **fail 则不得**声称完成或进入 Deploy。

## 阻断速查

见 AGENTS「评审阻断项」。本 skill 自检时若命中，DoD = fail。
