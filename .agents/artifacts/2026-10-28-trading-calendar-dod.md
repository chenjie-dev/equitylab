# DoD：交易日历落 PG（今年权威 + 明年占位）

- 日期：2026-10-28
- 级别：feature
- 关联：行情冷库 `market.trading_calendar`
- 作者角色：Backend

## 已做 / 未做 / 已知风险 / 复验命令

- 已做：权威源 `pmc`；adata 写今年+明年；collector **消费日历**（`session_calendar` + `volume_anchor.is_trading_day`；休市不写 A 股 trades、拉长 poll）
- 未做：前端休市徽标（P1）；PMC 2027 完整度依赖上游发版
- 已知风险：库不可用时回落工作日启发式；库内 `BSE`=孟买勿混用
- 复验命令：见下

```bash
docker compose up -d --build adata-ingest
docker compose exec -T adata-ingest python -c "from main import sync_calendar; print(sync_calendar())"
docker compose exec -T postgres psql -U equitylab -d equitylab -c "
SELECT exchange_code,
  count(*) FILTER (WHERE calendar_date BETWEEN '2026-01-01' AND '2026-12-31' AND is_trading_day) AS y2026_td
FROM market.trading_calendar GROUP BY 1;
SELECT calendar_date, is_trading_day FROM market.trading_calendar
WHERE exchange_code='SSE' AND calendar_date IN ('2026-01-01','2026-10-01','2026-10-08');
"
```

## 验收对照

| 验收标准 | 结果 | 证据 |
|---|---|---|
| 2026 权威日历在 PG（含休市） | pass | 三所 `y2026_td=242`；元旦/国庆 `f`，10-08 `t`；watermark `pmc` |
| 明年继续写 | pass | 2027 全表 365 行、SSE 日历 trading=246 replace |
| seed 不覆盖权威节假日 | pass | sync 后再 seed，仍 242 |
| collector 消费日历门禁 | pass | 日志 `session_calendar loaded` + `session_day=True`；休市 `non_trading` 单测 |

## 冒烟

| 命令 | 期望 | 实际 |
|---|---|---|
| adata `sync_calendar` | 2026×3=1095，2027 empty+seed | total 1095 |
| akshare `sync_calendar` | 只写 2026（+空 2027），仍 242 | trading=242，不抬升 |
| collector 含 insert-only seed | `weekdays_insert` | assert 通过 |

## 文档

| 变更类型 | 已更新路径 |
|---|---|
| schema / akshare / .env.example | `docs/market/2026-10-26-market-postgres-schema.md`、`docs/market/2026-10-27-akshare-ingest.md`、`.env.example` |

## 数据面

| 检查 | 结果 |
|---|---|
| collector / adata / akshare 已 rebuild | pass |
| `trading_calendar` 非空且节假日正确 | pass |

## 结论

- DoD：pass
- 可否进入 Review：是
