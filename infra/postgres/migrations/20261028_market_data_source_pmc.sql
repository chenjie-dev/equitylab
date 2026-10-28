-- EquityLab：登记 data_source=pmc（pandas_market_calendars → trading_calendar）
-- 产品路由仍用 cn-equity；本码仅出现在 data_source / watermark。

INSERT INTO market.data_source (code, name, notes) VALUES
    (
        'pmc',
        'pandas_market_calendars',
        'A 股交易日历权威（SSE 日历名写 SSE/SZSE/BSE）；https://github.com/rsheftel/pandas_market_calendars'
    )
ON CONFLICT (code) DO NOTHING;

COMMENT ON TABLE market.data_source IS
    '行情采集源登记；含 sina/adata/akshare/pmc/manual 等，非产品 API 名';
