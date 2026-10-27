# DoD：冷库动量因子 IC 真算

- 日期：2026-10-27
- 级别：feature
- 关联：plan 冷库因子IC真算
- 作者角色：Backend / Research

## 已做 / 未做 / 已知风险 / 复验命令

- 已做：`app/factors/momentum_ic.py` Spearman 时序 IC；`POST /factors/ic` 接 `market.bar_daily`（经 `fetch_bars`）；`demo=false` + `source`/`assumptions`；编排工具与 plan 传 `universe`；单测 5 绿；`scripts/smoke-factor-ic.sh`；api/README 更新；research/orchestrator rebuild
- 未做：截面/多因子/alphalens；实验产物落盘；RAG 真检索
- 已知风险：冷库无目标票日线 → 422；非 A / 空冷回落路径 `mode=ts_ic_fallback_bars`；单调合成序列 IC 偏高属预期
- 复验命令：

```bash
cd apps/research && python3 -m pytest tests/test_momentum_ic.py -q
docker compose up -d --build research orchestrator
bash scripts/smoke-factor-ic.sh
curl -sf -X POST http://127.0.0.1:3000/api/research/factors/ic \
  -H 'content-type: application/json' \
  -d '{"factor":"momentum","windowYears":3,"universe":"600519"}'
```

## 验收对照

| 标准 | 结果 | 证据 |
|---|---|---|
| 不再伪随机 IC | pass | 引擎 + 冷库 closes |
| `demo=false` 有数时 | pass | 冒烟断言 |
| 样本不足不编数 | pass | ValueError → 422 |
| 单测 | pass | 5 passed |
| api 文档 | pass | 非「占位」 |

## 结论

- DoD：pass
- 可否进入 Review：是
