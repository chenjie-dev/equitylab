# DoD：<标题>

- 日期：YYYY-MM-DD
- 级别：hotfix | feature | epic
- 关联 PRD / commit / 话题：
- 作者角色：

## 已做 / 未做 / 已知风险 / 复验命令

- 已做：
- 未做（须诚实）：
- 已知风险：
- 复验命令：

```bash
# 粘贴本轮实际跑过的命令
```

## 验收对照

| 验收标准 | 结果 pass/fail | 证据（命令或测试名） |
|---|---|---|

## 冒烟（非仅 health）

| 命令 | 期望 | 实际 |
|---|---|---|

## 文档

| 变更类型 | 已更新路径 | 跳过理由 |
|---|---|---|
| api / containers / qdb / .env.example | | |

## 数据面（若涉及行情）

| 检查 | pass/fail | 证据 |
|---|---|---|
| collector 已 rebuild/recreate | | |
| 写路径有数据（snapshots/docs） | | |
| 读路径 API 非空/非错 | | |
| UI 关键路径 | | |
| 展示集 ⊆ 采集或已标明「仅目录」 | | |
| 无 BINANCE/ONDO 混入 cn-equity | | |
| 环境非 skip/关 quotes 完成态 | | |

## 运行态

- [ ] 改动服务已 `--build` / recreate 后再验  
- [ ] 未把宿主机未重建改动当成线上绿  

## 结论

- DoD：pass | fail  
- 可否进入 Review / Deploy：是 / 否  
- 阻断原因（若 fail）：
