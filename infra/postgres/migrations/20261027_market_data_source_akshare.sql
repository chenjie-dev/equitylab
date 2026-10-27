-- EquityLab：仅登记 data_source=akshare（并行冷采集边车）
-- 不改 market 其它表结构；akshare 只是多一个源头，经既有 upsert 写同一套表。
-- 参考：https://github.com/akfamily/akshare
-- 产品路由仍用 cn-equity；本码仅出现在 data_source / watermark / 行级 source_code。

INSERT INTO market.data_source (code, name, notes) VALUES
    (
        'akshare',
        'AKShare',
        '开源财经数据接口库；https://github.com/akfamily/akshare；services/akshare-ingest 写 market'
    )
ON CONFLICT (code) DO NOTHING;

COMMENT ON TABLE market.data_source IS
    '行情供应商登记；sina/adata/akshare/binance/… 不作产品 API 资源名';
