# DoD：领域职责 Wave1–4

- 日期：2026-10-27
- 级别：feature
- 关联：领域缺口与职责计划

## 已做 / 未做 / 已知风险 / 复验命令

- 已做：
  - Wave1：删除 ashare 包/BFF；CONTEXT 采集族含 adata-ingest；边界图与「不做读 UI」同步；前端 hint 去产品化源名。
  - Wave2：东财 F10 EM2016 行业回落；北向水位注明 net_max/deal_only；STOCK_LIMIT 默认 80。
  - Wave3：`lhb-days` / `lhb/{id}/detail`；行情台概念列表+成分；热榜 Tab 北向/龙虎榜/席位。
  - Wave4：`get_cn_equity_quote` 工具；回测 A 股日线优先 `market.bar_daily`（source 标明）。
- 未做：申万官方码全量（仍为 EM 伪码回落）；北向近端 NET 字段东财侧缺失无法伪造；概念日线采集；RAG/因子仍为 demo stub。
- 已知风险：行业码 `EM:*` 非申万官方；股票池 80 仍非全市场；前端概念列表仅 east vendor 前 80。
- 复验命令：

```bash
test ! -d apps/research/app/ashare && test ! -d apps/frontend/app/api/ashare
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:3000/api/cn-equity/codes?limit=3
curl -s http://localhost:3000/api/cn-equity/sentiment/summary | python3 -c 'import sys,json;print(json.load(sys.stdin).get("note"))'
curl -s http://localhost:3000/api/cn-equity/lhb-days?limit=3
curl -s -X POST http://localhost:3000/api/backtests/run -H 'content-type: application/json' \
  -d '{"strategy":"dual_ma","fast":5,"slow":20,"universe":"600519.SH","period":"1d","count":80}'
docker compose exec -T orchestrator wget -qO- http://127.0.0.1:8001/tools
```

## 验收对照

| 验收标准 | 结果 | 证据 |
|---|---|---|
| 无 ashare | pass | 404 `/api/ashare`；目录 gone |
| 行业回落 | pass | 容器内 600519 → EM:1/2/3 |
| 北向诚实覆盖说明 | pass | note 含覆盖至 2024-08-16 |
| 龙虎榜+明细 | pass | days + detail count=3 |
| 回测冷库 | pass | source=postgres:market.bar_daily |
| cn-equity 工具 | pass | tools 含 get_cn_equity_quote |

## 结论

- DoD：pass（本计划范围）
- 可否进入 Review：是
