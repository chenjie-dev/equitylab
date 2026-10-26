-- EquityLab market schema（聚源语义对齐）
-- 已有卷手工执行；新卷由 init.sql 引入等价定义。
-- 权威说明：docs/2026-10-26-market-postgres-schema.md

BEGIN;

CREATE SCHEMA IF NOT EXISTS market;

-- —— 数据源（供应商登记；非业务资源名）——
CREATE TABLE IF NOT EXISTS market.data_source (
    code        VARCHAR(32) PRIMARY KEY,
    name        VARCHAR(128) NOT NULL,
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE market.data_source IS '行情采集源登记；聚源无直接对应，本项目扩展';
COMMENT ON COLUMN market.data_source.code IS '如 sina / binance / ondo / manual';

INSERT INTO market.data_source (code, name, notes) VALUES
    ('sina', '新浪财经', '中国 A 股公开行情回源之一'),
    ('binance', 'Binance', '现货 / 代币化美股上游'),
    ('ondo', 'Ondo / Binance RWA', '代币化美股'),
    ('manual', '手工导入', '运维或迁移导入'),
    ('qdb', 'qdb 引擎', '从引擎导出或对账用')
ON CONFLICT (code) DO NOTHING;

-- —— 交易所 ——
CREATE TABLE IF NOT EXISTS market.exchange (
    code        VARCHAR(16) PRIMARY KEY,
    name        VARCHAR(64) NOT NULL,
    tz          VARCHAR(64) NOT NULL DEFAULT 'UTC',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE market.exchange IS '交易所；对齐聚源 SecuMarket 维度';
COMMENT ON COLUMN market.exchange.code IS 'SSE / SZSE / BSE / BINANCE / ONDO';

INSERT INTO market.exchange (code, name, tz) VALUES
    ('SSE', '上海证券交易所', 'Asia/Shanghai'),
    ('SZSE', '深圳证券交易所', 'Asia/Shanghai'),
    ('BSE', '北京证券交易所', 'Asia/Shanghai'),
    ('BINANCE', 'Binance Spot', 'UTC'),
    ('ONDO', 'Ondo Tokenized Stocks', 'UTC')
ON CONFLICT (code) DO NOTHING;

-- —— 证券主数据（SecuMain）——
CREATE TABLE IF NOT EXISTS market.security (
    inner_code      BIGSERIAL PRIMARY KEY,
    exchange_code   VARCHAR(16) NOT NULL REFERENCES market.exchange (code),
    secu_code       VARCHAR(32) NOT NULL,
    secu_category   VARCHAR(32) NOT NULL DEFAULT 'stock',
    listed_status   VARCHAR(16) NOT NULL DEFAULT 'listed',
    name            VARCHAR(128) NOT NULL DEFAULT '',
    name_en         VARCHAR(128) NOT NULL DEFAULT '',
    list_date       DATE,
    delist_date     DATE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (exchange_code, secu_code)
);
COMMENT ON TABLE market.security IS '证券主数据；对齐聚源 SecuMain';
COMMENT ON COLUMN market.security.inner_code IS '代理主键；对齐 InnerCode';
COMMENT ON COLUMN market.security.secu_code IS '证券代码；A 股多为 6 位；对齐 SecuCode';
COMMENT ON COLUMN market.security.secu_category IS 'stock / etf / index / other；对齐 SecuCategory 语义';
COMMENT ON COLUMN market.security.listed_status IS 'listed / suspended / delisted';

CREATE INDEX IF NOT EXISTS idx_market_security_secu_code
    ON market.security (secu_code);

CREATE TABLE IF NOT EXISTS market.security_name_hist (
    id              BIGSERIAL PRIMARY KEY,
    inner_code      BIGINT NOT NULL REFERENCES market.security (inner_code) ON DELETE CASCADE,
    effective_from  DATE NOT NULL,
    name            VARCHAR(128) NOT NULL,
    UNIQUE (inner_code, effective_from)
);
COMMENT ON TABLE market.security_name_hist IS '证券曾用名';

-- —— 日线（QT_DailyQuote）——
CREATE TABLE IF NOT EXISTS market.bar_daily (
    inner_code      BIGINT NOT NULL REFERENCES market.security (inner_code),
    trading_day     DATE NOT NULL,
    prev_close      NUMERIC(16, 4),
    open            NUMERIC(16, 4),
    high            NUMERIC(16, 4),
    low             NUMERIC(16, 4),
    close           NUMERIC(16, 4),
    volume          BIGINT,
    amount          NUMERIC(20, 2),
    source_code     VARCHAR(32) REFERENCES market.data_source (code),
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (inner_code, trading_day)
);
COMMENT ON TABLE market.bar_daily IS '日 K；对齐聚源 QT_DailyQuote；价格为交易所原始价';
COMMENT ON COLUMN market.bar_daily.trading_day IS '交易所日历日；对齐 TradingDay';
COMMENT ON COLUMN market.bar_daily.volume IS '成交量（股）';
COMMENT ON COLUMN market.bar_daily.amount IS '成交额（元）';

CREATE INDEX IF NOT EXISTS idx_market_bar_daily_day
    ON market.bar_daily (trading_day DESC);

-- —— 分钟线 ——
CREATE TABLE IF NOT EXISTS market.bar_minute (
    inner_code      BIGINT NOT NULL REFERENCES market.security (inner_code),
    period          VARCHAR(8) NOT NULL,
    bar_time        TIMESTAMPTZ NOT NULL,
    trading_day     DATE NOT NULL,
    open            NUMERIC(16, 4),
    high            NUMERIC(16, 4),
    low             NUMERIC(16, 4),
    close           NUMERIC(16, 4),
    volume          BIGINT,
    amount          NUMERIC(20, 2),
    source_code     VARCHAR(32) REFERENCES market.data_source (code),
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (inner_code, period, bar_time),
    CONSTRAINT bar_minute_period_chk CHECK (period IN ('1m', '5m', '15m', '60m'))
);
COMMENT ON TABLE market.bar_minute IS '分钟 K；bar_time 为 UTC；首版未分区，后续可按月 RANGE';
COMMENT ON COLUMN market.bar_minute.trading_day IS '冗余交易所日历日，便于按日切片';

CREATE INDEX IF NOT EXISTS idx_market_bar_minute_lookup
    ON market.bar_minute (inner_code, period, bar_time DESC);

-- —— 复权因子（QT_AdjustingFactor）——
CREATE TABLE IF NOT EXISTS market.adjust_factor (
    inner_code          BIGINT NOT NULL REFERENCES market.security (inner_code),
    ex_date             DATE NOT NULL,
    forward_factor      NUMERIC(20, 10) NOT NULL DEFAULT 1,
    backward_factor     NUMERIC(20, 10) NOT NULL DEFAULT 1,
    source_code         VARCHAR(32) REFERENCES market.data_source (code),
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (inner_code, ex_date)
);
COMMENT ON TABLE market.adjust_factor IS '复权因子；对齐 QT_AdjustingFactor；不存复权价行';
COMMENT ON COLUMN market.adjust_factor.forward_factor IS '前复权累乘因子（读路径约定见设计文）';
COMMENT ON COLUMN market.adjust_factor.backward_factor IS '后复权累乘因子';

-- —— 交易日历（QT_TradingDayNew）——
CREATE TABLE IF NOT EXISTS market.trading_calendar (
    exchange_code       VARCHAR(16) NOT NULL REFERENCES market.exchange (code),
    calendar_date       DATE NOT NULL,
    is_trading_day      BOOLEAN NOT NULL DEFAULT FALSE,
    prev_trading_day    DATE,
    next_trading_day    DATE,
    PRIMARY KEY (exchange_code, calendar_date)
);
COMMENT ON TABLE market.trading_calendar IS '交易日历；对齐 QT_TradingDayNew；按交易所';

CREATE INDEX IF NOT EXISTS idx_market_calendar_trading
    ON market.trading_calendar (exchange_code, calendar_date)
    WHERE is_trading_day;

-- —— 停牌（QT_Suspend）——
CREATE TABLE IF NOT EXISTS market.suspend (
    id              BIGSERIAL PRIMARY KEY,
    inner_code      BIGINT NOT NULL REFERENCES market.security (inner_code),
    suspend_from    DATE NOT NULL,
    suspend_to      DATE,
    reason          VARCHAR(256) NOT NULL DEFAULT '',
    source_code     VARCHAR(32) REFERENCES market.data_source (code),
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (inner_code, suspend_from)
);
COMMENT ON TABLE market.suspend IS '停牌区间；对齐 QT_Suspend';

CREATE INDEX IF NOT EXISTS idx_market_suspend_inner
    ON market.suspend (inner_code, suspend_from);

-- —— 采集水位 ——
CREATE TABLE IF NOT EXISTS market.ingest_watermark (
    source_code     VARCHAR(32) NOT NULL REFERENCES market.data_source (code),
    dataset         VARCHAR(64) NOT NULL,
    scope_key       VARCHAR(64) NOT NULL DEFAULT '',
    watermark_ts    TIMESTAMPTZ,
    watermark_day   DATE,
    detail          JSONB,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_code, dataset, scope_key)
);
COMMENT ON TABLE market.ingest_watermark IS '采集断点；dataset 如 bar_daily / bar_minute / calendar';

-- 废弃顶层 public.klines（若存在则仅加注释，不强制 DROP）
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'klines'
    ) THEN
        EXECUTE $c$
            COMMENT ON TABLE public.klines IS
            'DEPRECATED：请改用 market.bar_daily / market.bar_minute；见 docs/2026-10-26-market-postgres-schema.md'
        $c$;
    END IF;
END $$;

COMMIT;

-- 可选：迁移旧 public.klines 后删除
-- DROP TABLE IF EXISTS public.klines;
