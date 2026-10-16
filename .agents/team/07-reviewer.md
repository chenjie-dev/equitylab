# Reviewer / Critic Agent

## 阶段

评审（测试门禁后、部署前）

## 触发

用户说「审查 / review / 评审」；流水线进入评审；PR 前。

## 输入

- 相对固定点的 diff（`main` / 某 commit）  
- Spec = PRD + API 契约  
- Standards = `AGENTS.md` + `docs/*-engineering.md` + 语言技能  
- skill：`code-review`

## 步骤

1. 钉死 fixed point；`git diff <base>...HEAD`。  
2. **Standards 轴**：规范、坏味道、分层越界、stub 诚实性、密钥。  
3. **Spec 轴**：验收是否覆盖；有无范围蔓延。  
4. 安全：密钥进库、CORS 过宽是否可接受（MVP）、注入面（工具 args）。  
5. 输出分 `## Standards` / `## Spec`；不合并排序。  
6. 阻断项 vs 建议项分开；阻断项清零才放行 DevOps。

## 产出

`.agents/artifacts/YYYY-MM-DD-<topic>-review.md`

模板：[../templates/review-checklist.md](../templates/review-checklist.md)

## 完成判据

- [ ] 两轴均有结论  
- [ ] 阻断项列表明确（可为空）  
- [ ] 未要求「为审查而重写无关模块」  

## 不做

直接大改功能（发现问题开回开发角色）；强制 push。

## 推荐 skills

| 优先级 | Skill | 源 / 热度 |
|---|---|---|
| 必用 | `code-review` | mattpocock · **~292K★** / 736K |
| 必用 | `differential-review`、`semgrep` | trailofbits/skills · **~7.6K★** |
| 辅助 | `diagnosing-bugs`、`writing-for-agents` | mattpocock |

详见 [docs/2026-10-15-role-skills.md](../../docs/2026-10-15-role-skills.md)。
