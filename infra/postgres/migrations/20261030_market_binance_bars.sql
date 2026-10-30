-- EquityLab：币安现货热冷分离 — 扩 bar_minute 周期、放宽精度、登记 crypto
-- 产品面仍为 /markets + market-data；本迁移只改冷库。
-- 已有卷须手工：psql "$DATABASE_URL" -f infra/postgres/migrations/20261030_market_binance_bars.sql

-- secu_category 增加 crypto
ALTER TABLE market.security DROP CONSTRAINT IF EXISTS security_secu_category_chk;
ALTER TABLE market.security
    ADD CONSTRAINT security_secu_category_chk
    CHECK (secu_category IN (
        'stock', 'index', 'concept', 'etf', 'convertible', 'crypto', 'other'
    ));
COMMENT ON COLUMN market.security.secu_category IS
    'stock=A股；index；concept；etf；convertible；crypto=加密现货；other';

-- 精度：兼容加密小数成交量与多位报价（A 股整数仍可写入）
ALTER TABLE market.bar_daily
    ALTER COLUMN prev_close TYPE NUMERIC(24, 8),
    ALTER COLUMN open TYPE NUMERIC(24, 8),
    ALTER COLUMN high TYPE NUMERIC(24, 8),
    ALTER COLUMN low TYPE NUMERIC(24, 8),
    ALTER COLUMN close TYPE NUMERIC(24, 8),
    ALTER COLUMN volume TYPE NUMERIC(24, 8),
    ALTER COLUMN amount TYPE NUMERIC(28, 8);

ALTER TABLE market.bar_minute
    ALTER COLUMN open TYPE NUMERIC(24, 8),
    ALTER COLUMN high TYPE NUMERIC(24, 8),
    ALTER COLUMN low TYPE NUMERIC(24, 8),
    ALTER COLUMN close TYPE NUMERIC(24, 8),
    ALTER COLUMN volume TYPE NUMERIC(24, 8),
    ALTER COLUMN amount TYPE NUMERIC(28, 8);

-- 币安全周期（1d 走 bar_daily；60m 读写映射为 1h）
ALTER TABLE market.bar_minute DROP CONSTRAINT IF EXISTS bar_minute_period_chk;
ALTER TABLE market.bar_minute
    ADD CONSTRAINT bar_minute_period_chk CHECK (period IN (
        '1m', '3m', '5m', '15m', '30m',
        '1h', '60m', '2h', '4h', '6h', '12h',
        '3d', '1w', '1M'
    ));
COMMENT ON COLUMN market.bar_minute.period IS
    'A股：1m/5m/15m/60m；币安另含 3m/30m/1h/2h/4h/6h/12h/3d/1w/1M；1h≡60m';

INSERT INTO market.data_source (code, name, notes) VALUES
    ('binance', 'Binance', '现货公开 REST/WS；冷棒写 market.bar_*')
ON CONFLICT (code) DO UPDATE
    SET notes = EXCLUDED.notes;
