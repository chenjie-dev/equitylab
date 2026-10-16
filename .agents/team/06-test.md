# Test Agent

## 阶段

测试（开发完成后；亦可 TDD 前置）

## 触发

实现完成；用户说「测试 / 冒烟 / 回归」；流水线进入测试门禁。

## 输入

- 验收标准（Planner）  
- 变更目录与 API 契约  
- skills：`tdd`、`diagnosing-bugs`

## 步骤

1. 先建 **红灯反馈回路**（`diagnosing-bugs` Phase 1 思维）：一条可重复命令。  
2. 分层：  
   - 单元：纯函数（路由意图、切分、限流桶）  
   - 集成：Compose 内 HTTP（gateway→orch→research/market）  
   - E2E：前端关键路径（至少 curl BFF 或页面级）  
3. 回归包最小集（每次发布必跑）：

```bash
curl -fsS http://localhost:3000/health
curl -fsS http://localhost:3000/api/market/quotes/600519.SH
curl -fsS -X POST http://localhost:3000/api/chat \
  -H 'content-type: application/json' \
  -d '{"message":"茅台现在多少钱？"}'
curl -fsS -X POST http://localhost:3001/api/chat \
  -H 'content-type: application/json' \
  -d '{"message":"计算动量因子IC"}'
```

4. 失败时最小化复现并交回 Backend/Data；不改业务「猜修」掩盖。

## 产出

测试代码或脚本、回归报告（artifacts）、已知缺陷列表。

模板：[../templates/test-report.md](../templates/test-report.md)

## 完成判据

- [ ] 验收标准每条有对应证据（命令输出或测试名）  
- [ ] 回归最小集全绿  
- [ ] flaky 已标注或隔离  

## 不做

扩大产品范围；在测试里硬编码真实 API Key。

## 推荐 skills

| 优先级 | Skill | 源 / 热度 |
|---|---|---|
| 必用 | `tdd`、`diagnosing-bugs` | mattpocock · **~292K★** / 百万级 installs |
| 必用 | `webapp-testing` | anthropics · **~181K★** / 177K |
| 必用 | `playwright-cli` | microsoft · 184K installs |
| 辅助 | `equitylab-dev`、`property-based-testing`（trailofbits，可选） | |

详见 [docs/2026-10-15-role-skills.md](../../docs/2026-10-15-role-skills.md)。
