# DoD：cn-equity 冷域读面 + 行情台右侧 Tab

- 日期：2026-10-27
- 级别：feature
- 关联：adata P1–P3 写入后的读路径暴露（fundamentals / plates / sentiment / lhb）
- 作者角色：Backend + Frontend

## 已做 / 未做 / 已知风险 / 复验命令

- 已做：research 冷读 API；BFF 透传；行情台右侧「五档|资金|财务|热榜」；`api.md` / `cn-equity.md` 同步；research+frontend rebuild 冒烟。
- 未做：板块/龙虎榜独立页面；北向 NET 近端空值补齐（ingest 侧已知）；财务全量科目 UI。
- 已知风险：热榜/资金依赖 adata-ingest 日终；`lhb` 按日查询，无数据日返回空列表属正常；右侧资金/财务仅 `asset=stock`。
- 复验命令：

```bash
docker compose up -d --build research frontend
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:3000/health
curl -s 'http://localhost:3000/api/cn-equity/fundamentals/600519?flow_limit=3' | python3 -c 'import sys,json;d=json.load(sys.stdin);assert d.get("source")=="postgres:market" and d.get("capital_flow")'
curl -s 'http://localhost:3000/api/cn-equity/sentiment/summary' | python3 -c 'import sys,json;d=json.load(sys.stdin);assert len(d.get("hot_stock")or[])>0'
curl -s 'http://localhost:3000/api/cn-equity/plates?vendor=east&limit=2' | python3 -c 'import sys,json;d=json.load(sys.stdin);assert d.get("count",0)>0'
```

## 验收对照

| 验收标准 | 结果 | 证据 |
|---|---|---|
| 个股 fundamentals 非空（资金或财务至少一侧有数） | pass | BFF 600519 flow=3 share=True fin=28 |
| sentiment 热榜可读 | pass | hot=20 margin=5 |
| plates / plate-flow 可读 | pass | plates count=2；plate-flow day=2026-10-27 count=3 |
| UI 右侧 Tab 接入 BFF | pass | `/markets/cn` 拉 fundamentals + sentiment |
| 读路径零上游 | pass | 仅读 `market` / 既有 qdb 五档 |

## 冒烟（非仅 health）

| 命令 | 期望 | 实际 |
|---|---|---|
| `GET /api/cn-equity/fundamentals/600519` | 200 + capital_flow | 200 source=postgres:market flow=3 |
| `GET /api/cn-equity/sentiment/summary` | 200 + hot_stock | 200 hot=20 |
| `GET /api/cn-equity/plates?vendor=east&limit=2` | 200 + data | 200 count=2 |
| `GET /api/cn-equity/plate-flow` | 200 | 200 day=2026-10-27 |
| frontend health | 200 | 200 |

## 文档

| 变更类型 | 已更新路径 | 跳过理由 |
|---|---|---|
| api | `docs/platform/2026-10-15-api.md` | |
| cn-equity | `docs/market/2026-10-26-cn-equity.md` | |
| containers / .env | — | 无端口/env 变更 |

## 数据面

| 检查 | 结果 | 证据 |
|---|---|---|
| 读路径 API 非空 | pass | fundamentals / sentiment / plates |
| UI 绑定路径 | pass | 右侧 Tab → BFF |
| 无 BINANCE 混入 | pass | 冷读仅 A 股 market |
| collector rebuild | n/a | 本轮只读 research/frontend |

## 运行态

- [x] research / frontend `--build` recreate 后再验
- [x] 未把宿主机未重建改动当成线上绿

## 结论

- DoD：pass
- 可否进入 Review / Deploy：是
- 阻断原因：—
