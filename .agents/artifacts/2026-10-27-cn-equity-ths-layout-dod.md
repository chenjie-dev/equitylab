# DoD：cn-equity 同花顺布局接 adata 冷数据

- 日期：2026-10-27
- 级别：feature
- 关联：adata-ingest P0 → UI
- 作者角色：Frontend + Backend

## 已做 / 未做 / 已知风险 / 复验命令

- 已做：顶栏六指数；资产类 Tab（沪深A股/指数/ETF/可转债）；`codes?category=` / `index-strip` / 报价与 K 线带交易所；指数报价优先 `bar_daily`
- 未做：指数分时/五档；网关反代页面路径（仍走 `:3001`）；可转债交易所校正
- 已知风险：000001 个股与指数并存，须带 `exchange`/`category`；部分指数 name 空
- 复验：

```bash
curl -s 'http://localhost:3000/api/research/cn-equity/index-strip' | head -c 400
curl -s 'http://localhost:3000/api/research/cn-equity/codes?category=index&limit=8'
open 'http://localhost:3001/markets/cn'
```
