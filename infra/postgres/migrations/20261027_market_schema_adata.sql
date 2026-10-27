-- EquityLab market schema：adata 完整冷域扩展
--
-- 依赖：20261026_market_schema.sql（market schema 基线已存在）
-- 权威说明：docs/market/2026-10-27-market-schema-adata完整域.md
-- 边界：docs/market/2026-10-26-行情模块边界.md §3.4
--
-- 热冷：本文件只建冷表。实时报价/五档/分笔/当日分时 → qdb，不在此建权威表。
-- 价格：bar_* 仍为交易所未复权原始价；复权走 adjust_factor / dividend。
-- 写者：仅采集族（collector / history-ingest / 后续 adata job）；读经 /cn-equity。
-- 产品名：cn-equity；adata/eastmoney/ths 仅为 data_source 或 plate.vendor。
--
-- 已有卷：psql -f 本文件。新卷：compose 挂载 docker-entrypoint-initdb.d/03_*.sql。

BEGIN;

-- —— 数据源登记（供应商码，非 API 资源名）——
INSERT INTO market.data_source (code, name, notes) VALUES
    ('adata', 'adata SDK', '多源融合 A 股库；https://github.com/1nchaos/adata；实现可经 SDK，溯源仍可写 eastmoney/ths'),
    ('eastmoney', '东方财富', '概念/资金流/财务/舆情等公开溯源'),
    ('ths', '同花顺', '概念/指数编码/热度等公开溯源')
ON CONFLICT (code) DO NOTHING;

-- —— 伪交易所：厂商概念码与真交易所（SSE/SZSE/BSE）隔离 ——
INSERT INTO market.exchange (code, name, tz) VALUES
    ('THS', '同花顺概念/板块（逻辑盘）', 'Asia/Shanghai'),
    ('EAST', '东方财富概念/板块（逻辑盘）', 'Asia/Shanghai')
ON CONFLICT (code) DO NOTHING;

COMMENT ON COLUMN market.exchange.code IS
    'SSE/SZSE/BSE=真交易所；THS/EAST=厂商概念逻辑盘；BINANCE/ONDO=加密侧';

-- —— security 扩展：类别约束 + 厂商重编码 ——
ALTER TABLE market.security
    ADD COLUMN IF NOT EXISTS vendor_code VARCHAR(64) NOT NULL DEFAULT '';

COMMENT ON COLUMN market.security.vendor_code IS
    '厂商侧重编码（如同花顺对指数的重编码）；无则空串；不替代 secu_code';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'security_secu_category_chk'
          AND conrelid = 'market.security'::regclass
    ) THEN
        ALTER TABLE market.security
            ADD CONSTRAINT security_secu_category_chk
            CHECK (secu_category IN (
                'stock', 'index', 'concept', 'etf', 'convertible', 'other'
            ));
    END IF;
END $$;

COMMENT ON COLUMN market.security.secu_category IS
    'stock=A股；index=指数；concept=概念（常挂 THS/EAST）；etf；convertible=可转债；other；对齐 SecuCategory';

-- ============================================================================
-- 股本（聚源 LC_ShareStru；adata get_stock_shares）
-- ============================================================================
CREATE TABLE IF NOT EXISTS market.share_capital (
    inner_code          BIGINT NOT NULL REFERENCES market.security (inner_code),
    change_date         DATE NOT NULL,
    total_shares        NUMERIC(20, 4),
    float_shares        NUMERIC(20, 4),
    float_shares_a      NUMERIC(20, 4),
    change_reason       VARCHAR(256) NOT NULL DEFAULT '',
    source_code         VARCHAR(32) REFERENCES market.data_source (code),
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (inner_code, change_date)
);
COMMENT ON TABLE market.share_capital IS
    '股本结构变动；对齐聚源 LC_ShareStru；单位一律为股；adata stock.info.get_stock_shares';
COMMENT ON COLUMN market.share_capital.inner_code IS '→ security.inner_code';
COMMENT ON COLUMN market.share_capital.change_date IS '股本变动生效日（交易所日历日）';
COMMENT ON COLUMN market.share_capital.total_shares IS '总股本（股）';
COMMENT ON COLUMN market.share_capital.float_shares IS '流通股本合计（股）';
COMMENT ON COLUMN market.share_capital.float_shares_a IS 'A 股流通股本（股）；可空';
COMMENT ON COLUMN market.share_capital.change_reason IS '变动原因原文或归一标签';
COMMENT ON COLUMN market.share_capital.source_code IS '写入时的 data_source（adata/eastmoney/…）';
COMMENT ON COLUMN market.share_capital.ingested_at IS '本行入库时间（UTC）';

CREATE INDEX IF NOT EXISTS idx_market_share_capital_day
    ON market.share_capital (change_date DESC);

-- ============================================================================
-- 申万行业码表 + 证券归属（聚源 LC_ExgIndustry；adata get_industry_sw）
-- ============================================================================
CREATE TABLE IF NOT EXISTS market.industry_sw (
    industry_code       VARCHAR(32) PRIMARY KEY,
    name                VARCHAR(128) NOT NULL,
    level               SMALLINT NOT NULL,
    parent_code         VARCHAR(32) REFERENCES market.industry_sw (industry_code),
    source_code         VARCHAR(32) REFERENCES market.data_source (code),
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT industry_sw_level_chk CHECK (level IN (1, 2, 3))
);
COMMENT ON TABLE market.industry_sw IS
    '申万行业码表；对齐 LC_ExgIndustry 维度；level=1/2/3';
COMMENT ON COLUMN market.industry_sw.industry_code IS '申万行业代码（字符串，保留官方格式）';
COMMENT ON COLUMN market.industry_sw.name IS '行业名称';
COMMENT ON COLUMN market.industry_sw.level IS '1=一级 2=二级 3=三级';
COMMENT ON COLUMN market.industry_sw.parent_code IS '上级行业；一级为空';
COMMENT ON COLUMN market.industry_sw.source_code IS 'data_source';
COMMENT ON COLUMN market.industry_sw.ingested_at IS '入库时间（UTC）';

CREATE TABLE IF NOT EXISTS market.security_industry (
    inner_code          BIGINT NOT NULL REFERENCES market.security (inner_code),
    industry_code       VARCHAR(32) NOT NULL REFERENCES market.industry_sw (industry_code),
    effective_from      DATE NOT NULL,
    effective_to        DATE,
    source_code         VARCHAR(32) REFERENCES market.data_source (code),
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (inner_code, industry_code, effective_from)
);
COMMENT ON TABLE market.security_industry IS
    '证券↔申万行业；可保留历史区间；当前有效行 effective_to IS NULL';
COMMENT ON COLUMN market.security_industry.inner_code IS '→ security';
COMMENT ON COLUMN market.security_industry.industry_code IS '→ industry_sw';
COMMENT ON COLUMN market.security_industry.effective_from IS '归属起始日';
COMMENT ON COLUMN market.security_industry.effective_to IS '归属结束日；空=仍有效';
COMMENT ON COLUMN market.security_industry.source_code IS 'data_source';
COMMENT ON COLUMN market.security_industry.ingested_at IS '入库时间（UTC）';

CREATE INDEX IF NOT EXISTS idx_market_security_industry_code
    ON market.security_industry (industry_code);

-- ============================================================================
-- 厂商板块/概念（与官方指数成分表 index_member 分离）
-- adata: all_concept_code_* / concept_constituent_* / get_plate_east
-- ============================================================================
CREATE TABLE IF NOT EXISTS market.plate (
    vendor              VARCHAR(16) NOT NULL,
    plate_code          VARCHAR(64) NOT NULL,
    name                VARCHAR(128) NOT NULL DEFAULT '',
    plate_kind          VARCHAR(16) NOT NULL DEFAULT 'concept',
    inner_code          BIGINT REFERENCES market.security (inner_code),
    source_code         VARCHAR(32) REFERENCES market.data_source (code),
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (vendor, plate_code),
    CONSTRAINT plate_vendor_chk CHECK (vendor IN ('ths', 'east')),
    CONSTRAINT plate_kind_chk CHECK (plate_kind IN ('concept', 'industry', 'region', 'other'))
);
COMMENT ON TABLE market.plate IS
    '厂商概念/板块目录；vendor 隔离同名码；可选 inner_code 链到 category=concept 的 security 以便写 bar_daily';
COMMENT ON COLUMN market.plate.vendor IS 'ths=同花顺；east=东方财富';
COMMENT ON COLUMN market.plate.plate_code IS '厂商板块代码（如东财 BK****、同花顺概念码）';
COMMENT ON COLUMN market.plate.name IS '板块名称';
COMMENT ON COLUMN market.plate.plate_kind IS 'concept|industry|region|other';
COMMENT ON COLUMN market.plate.inner_code IS
    '可选 → security（exchange=THS|EAST, secu_category=concept）；板块行情日线挂此键';
COMMENT ON COLUMN market.plate.source_code IS 'data_source';
COMMENT ON COLUMN market.plate.ingested_at IS '首次入库时间（UTC）';
COMMENT ON COLUMN market.plate.updated_at IS '目录行最后更新时间（UTC）';

CREATE TABLE IF NOT EXISTS market.plate_member (
    vendor              VARCHAR(16) NOT NULL,
    plate_code          VARCHAR(64) NOT NULL,
    inner_code          BIGINT NOT NULL REFERENCES market.security (inner_code),
    effective_from      DATE NOT NULL,
    effective_to        DATE,
    source_code         VARCHAR(32) REFERENCES market.data_source (code),
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (vendor, plate_code, inner_code, effective_from),
    CONSTRAINT plate_member_fk_plate
        FOREIGN KEY (vendor, plate_code) REFERENCES market.plate (vendor, plate_code)
);
COMMENT ON TABLE market.plate_member IS
    '板块成分股；可保留调入调出历史（effective_to）';
COMMENT ON COLUMN market.plate_member.vendor IS '与 plate.vendor 一致';
COMMENT ON COLUMN market.plate_member.plate_code IS '与 plate.plate_code 一致';
COMMENT ON COLUMN market.plate_member.inner_code IS '成分证券 → security（多为 stock）';
COMMENT ON COLUMN market.plate_member.effective_from IS '调入日';
COMMENT ON COLUMN market.plate_member.effective_to IS '调出日；空=仍在成分内';
COMMENT ON COLUMN market.plate_member.source_code IS 'data_source';
COMMENT ON COLUMN market.plate_member.ingested_at IS '入库时间（UTC）';

CREATE INDEX IF NOT EXISTS idx_market_plate_member_sec
    ON market.plate_member (inner_code, vendor);

-- ============================================================================
-- 官方/权威指数成分（聚源 LC_IndexComponent；adata index_constituent）
-- ============================================================================
CREATE TABLE IF NOT EXISTS market.index_member (
    index_inner_code    BIGINT NOT NULL REFERENCES market.security (inner_code),
    member_inner_code   BIGINT NOT NULL REFERENCES market.security (inner_code),
    effective_from      DATE NOT NULL,
    effective_to        DATE,
    weight              NUMERIC(12, 8),
    source_code         VARCHAR(32) REFERENCES market.data_source (code),
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (index_inner_code, member_inner_code, effective_from)
);
COMMENT ON TABLE market.index_member IS
    '指数成分；对齐 LC_IndexComponent；与 plate_member（厂商概念）分离；weight 可空（adata 常无）';
COMMENT ON COLUMN market.index_member.index_inner_code IS '指数 → security（secu_category=index）';
COMMENT ON COLUMN market.index_member.member_inner_code IS '成分股 → security';
COMMENT ON COLUMN market.index_member.effective_from IS '调入日';
COMMENT ON COLUMN market.index_member.effective_to IS '调出日；空=仍在指数内';
COMMENT ON COLUMN market.index_member.weight IS '权重（0–1 或百分数，采集侧约定）；adata 常空';
COMMENT ON COLUMN market.index_member.source_code IS 'data_source';
COMMENT ON COLUMN market.index_member.ingested_at IS '入库时间（UTC）';

CREATE INDEX IF NOT EXISTS idx_market_index_member_member
    ON market.index_member (member_inner_code);

-- ============================================================================
-- 分红送转（可推算 adjust_factor；adata get_dividend）
-- ============================================================================
CREATE TABLE IF NOT EXISTS market.dividend (
    id                  BIGSERIAL PRIMARY KEY,
    inner_code          BIGINT NOT NULL REFERENCES market.security (inner_code),
    announce_date       DATE,
    ex_date             DATE NOT NULL,
    record_date         DATE,
    pay_date            DATE,
    cash_per_share      NUMERIC(16, 6),
    stock_per_share     NUMERIC(16, 6),
    transfer_per_share  NUMERIC(16, 6),
    remark              VARCHAR(512) NOT NULL DEFAULT '',
    source_code         VARCHAR(32) REFERENCES market.data_source (code),
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (inner_code, ex_date, announce_date)
);
COMMENT ON TABLE market.dividend IS
    '分红送转事件；写入后可由作业推算/更新 adjust_factor；勿把复权 OHLC 当原始价入库';
COMMENT ON COLUMN market.dividend.id IS '代理主键';
COMMENT ON COLUMN market.dividend.inner_code IS '→ security';
COMMENT ON COLUMN market.dividend.announce_date IS '预案/公告日；可空（唯一约束中 NULL 互不等价）';
COMMENT ON COLUMN market.dividend.ex_date IS '除权除息日（必填）';
COMMENT ON COLUMN market.dividend.record_date IS '股权登记日';
COMMENT ON COLUMN market.dividend.pay_date IS '派息日';
COMMENT ON COLUMN market.dividend.cash_per_share IS '每股派息（税前，元）';
COMMENT ON COLUMN market.dividend.stock_per_share IS '每股送股（股）';
COMMENT ON COLUMN market.dividend.transfer_per_share IS '每股公积金转增（股）';
COMMENT ON COLUMN market.dividend.remark IS '备注/原文摘要';
COMMENT ON COLUMN market.dividend.source_code IS 'data_source';
COMMENT ON COLUMN market.dividend.ingested_at IS '入库时间（UTC）';

CREATE INDEX IF NOT EXISTS idx_market_dividend_ex
    ON market.dividend (ex_date DESC);

-- ============================================================================
-- 个股日度资金流（adata get_capital_flow；分时资金流不进本表）
-- ============================================================================
CREATE TABLE IF NOT EXISTS market.capital_flow_daily (
    inner_code              BIGINT NOT NULL REFERENCES market.security (inner_code),
    trading_day             DATE NOT NULL,
    main_net                NUMERIC(20, 2),
    super_large_net         NUMERIC(20, 2),
    large_net               NUMERIC(20, 2),
    medium_net              NUMERIC(20, 2),
    small_net               NUMERIC(20, 2),
    source_code             VARCHAR(32) REFERENCES market.data_source (code),
    ingested_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (inner_code, trading_day)
);
COMMENT ON TABLE market.capital_flow_daily IS
    '个股日度资金净流入（元）；adata stock.market.get_capital_flow；当日分时 → qdb';
COMMENT ON COLUMN market.capital_flow_daily.inner_code IS '→ security';
COMMENT ON COLUMN market.capital_flow_daily.trading_day IS '交易日';
COMMENT ON COLUMN market.capital_flow_daily.main_net IS '主力净流入（元）';
COMMENT ON COLUMN market.capital_flow_daily.super_large_net IS '超大单净流入（元）';
COMMENT ON COLUMN market.capital_flow_daily.large_net IS '大单净流入（元）';
COMMENT ON COLUMN market.capital_flow_daily.medium_net IS '中单净流入（元）';
COMMENT ON COLUMN market.capital_flow_daily.small_net IS '小单净流入（元）';
COMMENT ON COLUMN market.capital_flow_daily.source_code IS 'data_source';
COMMENT ON COLUMN market.capital_flow_daily.ingested_at IS '入库时间（UTC）';

CREATE INDEX IF NOT EXISTS idx_market_capital_flow_day
    ON market.capital_flow_daily (trading_day DESC);

-- ============================================================================
-- 板块日度资金流（adata all_capital_flow_east 等）
-- ============================================================================
CREATE TABLE IF NOT EXISTS market.capital_flow_plate_daily (
    vendor                  VARCHAR(16) NOT NULL,
    plate_code              VARCHAR(64) NOT NULL,
    trading_day             DATE NOT NULL,
    main_net                NUMERIC(20, 2),
    super_large_net         NUMERIC(20, 2),
    large_net               NUMERIC(20, 2),
    medium_net              NUMERIC(20, 2),
    small_net               NUMERIC(20, 2),
    source_code             VARCHAR(32) REFERENCES market.data_source (code),
    ingested_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (vendor, plate_code, trading_day),
    CONSTRAINT capital_flow_plate_fk
        FOREIGN KEY (vendor, plate_code) REFERENCES market.plate (vendor, plate_code)
);
COMMENT ON TABLE market.capital_flow_plate_daily IS
    '概念/板块日度资金净流入（元）；须先有 plate 行';
COMMENT ON COLUMN market.capital_flow_plate_daily.vendor IS 'ths|east';
COMMENT ON COLUMN market.capital_flow_plate_daily.plate_code IS '→ plate';
COMMENT ON COLUMN market.capital_flow_plate_daily.trading_day IS '交易日';
COMMENT ON COLUMN market.capital_flow_plate_daily.main_net IS '主力净流入（元）';
COMMENT ON COLUMN market.capital_flow_plate_daily.super_large_net IS '超大单净流入（元）';
COMMENT ON COLUMN market.capital_flow_plate_daily.large_net IS '大单净流入（元）';
COMMENT ON COLUMN market.capital_flow_plate_daily.medium_net IS '中单净流入（元）';
COMMENT ON COLUMN market.capital_flow_plate_daily.small_net IS '小单净流入（元）';
COMMENT ON COLUMN market.capital_flow_plate_daily.source_code IS 'data_source';
COMMENT ON COLUMN market.capital_flow_plate_daily.ingested_at IS '入库时间（UTC）';

-- ============================================================================
-- 核心财务指标（筛选；非三大报明细；adata get_core_index）
-- ============================================================================
CREATE TABLE IF NOT EXISTS market.finance_core (
    inner_code          BIGINT NOT NULL REFERENCES market.security (inner_code),
    report_date         DATE NOT NULL,
    indicator_code      VARCHAR(64) NOT NULL,
    indicator_name      VARCHAR(128) NOT NULL DEFAULT '',
    value               NUMERIC(24, 8),
    unit                VARCHAR(32) NOT NULL DEFAULT '',
    source_code         VARCHAR(32) REFERENCES market.data_source (code),
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (inner_code, report_date, indicator_code)
);
COMMENT ON TABLE market.finance_core IS
    '核心财务指标长表（股票池筛选）；不做资产负债表/利润表/现金流表明细行';
COMMENT ON COLUMN market.finance_core.inner_code IS '→ security';
COMMENT ON COLUMN market.finance_core.report_date IS '报告期截止日';
COMMENT ON COLUMN market.finance_core.indicator_code IS '指标码（采集侧与 adata 列名映射，稳定英文/拼音码）';
COMMENT ON COLUMN market.finance_core.indicator_name IS '指标中文名（展示用，可随源更新）';
COMMENT ON COLUMN market.finance_core.value IS '指标数值';
COMMENT ON COLUMN market.finance_core.unit IS '单位（元、%、倍等）；可空串';
COMMENT ON COLUMN market.finance_core.source_code IS 'data_source';
COMMENT ON COLUMN market.finance_core.ingested_at IS '入库时间（UTC）';

CREATE INDEX IF NOT EXISTS idx_market_finance_core_report
    ON market.finance_core (report_date DESC);

-- ============================================================================
-- 限售解禁（adata stock_lifting_last_month）
-- ============================================================================
CREATE TABLE IF NOT EXISTS market.lifting (
    id                  BIGSERIAL PRIMARY KEY,
    inner_code          BIGINT NOT NULL REFERENCES market.security (inner_code),
    lift_date           DATE NOT NULL,
    shares              NUMERIC(20, 4),
    ratio               NUMERIC(12, 8),
    holder_type         VARCHAR(128) NOT NULL DEFAULT '',
    remark              VARCHAR(512) NOT NULL DEFAULT '',
    source_code         VARCHAR(32) REFERENCES market.data_source (code),
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (inner_code, lift_date, holder_type, shares)
);
COMMENT ON TABLE market.lifting IS
    '限售股解禁日程；舆情/事件冷表；adata sentiment.stock_lifting_last_month';
COMMENT ON COLUMN market.lifting.id IS '代理主键';
COMMENT ON COLUMN market.lifting.inner_code IS '→ security';
COMMENT ON COLUMN market.lifting.lift_date IS '解禁日';
COMMENT ON COLUMN market.lifting.shares IS '解禁数量（股）';
COMMENT ON COLUMN market.lifting.ratio IS '占总股本或流通比（采集侧约定；可空）';
COMMENT ON COLUMN market.lifting.holder_type IS '股东类型/来源标签';
COMMENT ON COLUMN market.lifting.remark IS '备注';
COMMENT ON COLUMN market.lifting.source_code IS 'data_source';
COMMENT ON COLUMN market.lifting.ingested_at IS '入库时间（UTC）';

CREATE INDEX IF NOT EXISTS idx_market_lifting_date
    ON market.lifting (lift_date DESC);

-- ============================================================================
-- 两融余额（adata securities_margin）
-- ============================================================================
CREATE TABLE IF NOT EXISTS market.margin_balance (
    trading_day         DATE NOT NULL,
    market_scope        VARCHAR(32) NOT NULL DEFAULT 'CN',
    financing_balance   NUMERIC(24, 2),
    securities_balance  NUMERIC(24, 2),
    margin_balance      NUMERIC(24, 2),
    source_code         VARCHAR(32) REFERENCES market.data_source (code),
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (trading_day, market_scope)
);
COMMENT ON TABLE market.margin_balance IS
    '融资融券余额日度；全市场或分市场；adata sentiment.securities_margin';
COMMENT ON COLUMN market.margin_balance.trading_day IS '交易日';
COMMENT ON COLUMN market.margin_balance.market_scope IS 'CN=全市场；或 SSE/SZSE 等';
COMMENT ON COLUMN market.margin_balance.financing_balance IS '融资余额（元）';
COMMENT ON COLUMN market.margin_balance.securities_balance IS '融券余额（元）';
COMMENT ON COLUMN market.margin_balance.margin_balance IS '两融余额合计（元）；可与上两列冗余校验';
COMMENT ON COLUMN market.margin_balance.source_code IS 'data_source';
COMMENT ON COLUMN market.margin_balance.ingested_at IS '入库时间（UTC）';

-- ============================================================================
-- 北向资金日度（adata north_flow；分时 → qdb）
-- ============================================================================
CREATE TABLE IF NOT EXISTS market.north_flow_daily (
    trading_day         DATE PRIMARY KEY,
    net_flow            NUMERIC(24, 2),
    buy_amount          NUMERIC(24, 2),
    sell_amount         NUMERIC(24, 2),
    sh_net              NUMERIC(24, 2),
    sz_net              NUMERIC(24, 2),
    source_code         VARCHAR(32) REFERENCES market.data_source (code),
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE market.north_flow_daily IS
    '沪深港通北向资金日度；分时 north_flow_min 不进本表';
COMMENT ON COLUMN market.north_flow_daily.trading_day IS '交易日';
COMMENT ON COLUMN market.north_flow_daily.net_flow IS '北向净流入（元）';
COMMENT ON COLUMN market.north_flow_daily.buy_amount IS '买入成交额（元）';
COMMENT ON COLUMN market.north_flow_daily.sell_amount IS '卖出成交额（元）';
COMMENT ON COLUMN market.north_flow_daily.sh_net IS '沪股通净流入（元）';
COMMENT ON COLUMN market.north_flow_daily.sz_net IS '深股通净流入（元）';
COMMENT ON COLUMN market.north_flow_daily.source_code IS 'data_source';
COMMENT ON COLUMN market.north_flow_daily.ingested_at IS '入库时间（UTC）';

-- ============================================================================
-- 龙虎榜（adata list_a_list_daily / get_a_list_info）
-- ============================================================================
CREATE TABLE IF NOT EXISTS market.lhb_list (
    id                  BIGSERIAL PRIMARY KEY,
    trading_day         DATE NOT NULL,
    inner_code          BIGINT NOT NULL REFERENCES market.security (inner_code),
    list_reason         VARCHAR(256) NOT NULL DEFAULT '',
    close               NUMERIC(16, 4),
    change_pct          NUMERIC(12, 6),
    amount              NUMERIC(20, 2),
    net_buy             NUMERIC(20, 2),
    source_code         VARCHAR(32) REFERENCES market.data_source (code),
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (trading_day, inner_code, list_reason)
);
COMMENT ON TABLE market.lhb_list IS
    '龙虎榜上榜日列表；明细见 lhb_detail';
COMMENT ON COLUMN market.lhb_list.id IS '代理主键；lhb_detail.lhb_list_id 外键';
COMMENT ON COLUMN market.lhb_list.trading_day IS '上榜交易日';
COMMENT ON COLUMN market.lhb_list.inner_code IS '→ security';
COMMENT ON COLUMN market.lhb_list.list_reason IS '上榜原因（异动类型原文）';
COMMENT ON COLUMN market.lhb_list.close IS '收盘价（元，原始价）';
COMMENT ON COLUMN market.lhb_list.change_pct IS '涨跌幅（小数或百分数，采集侧约定并在文档固定）';
COMMENT ON COLUMN market.lhb_list.amount IS '成交额（元）';
COMMENT ON COLUMN market.lhb_list.net_buy IS '净买入（元）';
COMMENT ON COLUMN market.lhb_list.source_code IS 'data_source';
COMMENT ON COLUMN market.lhb_list.ingested_at IS '入库时间（UTC）';

CREATE INDEX IF NOT EXISTS idx_market_lhb_list_day
    ON market.lhb_list (trading_day DESC);

CREATE TABLE IF NOT EXISTS market.lhb_detail (
    id                  BIGSERIAL PRIMARY KEY,
    lhb_list_id         BIGINT NOT NULL REFERENCES market.lhb_list (id) ON DELETE CASCADE,
    seat_name           VARCHAR(256) NOT NULL DEFAULT '',
    side                VARCHAR(8) NOT NULL DEFAULT '',
    buy_amount          NUMERIC(20, 2),
    sell_amount         NUMERIC(20, 2),
    net_amount          NUMERIC(20, 2),
    source_code         VARCHAR(32) REFERENCES market.data_source (code),
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT lhb_detail_side_chk CHECK (side IN ('buy', 'sell', 'unknown', ''))
);
COMMENT ON TABLE market.lhb_detail IS
    '龙虎榜营业部/席位买卖明细；删除 list 行时级联删除';
COMMENT ON COLUMN market.lhb_detail.id IS '代理主键';
COMMENT ON COLUMN market.lhb_detail.lhb_list_id IS '→ lhb_list.id';
COMMENT ON COLUMN market.lhb_detail.seat_name IS '营业部或席位名称';
COMMENT ON COLUMN market.lhb_detail.side IS 'buy|sell|unknown|空串';
COMMENT ON COLUMN market.lhb_detail.buy_amount IS '买入额（元）';
COMMENT ON COLUMN market.lhb_detail.sell_amount IS '卖出额（元）';
COMMENT ON COLUMN market.lhb_detail.net_amount IS '净额（元）';
COMMENT ON COLUMN market.lhb_detail.source_code IS 'data_source';
COMMENT ON COLUMN market.lhb_detail.ingested_at IS '入库时间（UTC）';

CREATE INDEX IF NOT EXISTS idx_market_lhb_detail_list
    ON market.lhb_detail (lhb_list_id);

-- ============================================================================
-- 热度/人气日终榜（adata hot_* / pop_rank_*；非实时推送）
-- ============================================================================
CREATE TABLE IF NOT EXISTS market.hot_rank_daily (
    trading_day         DATE NOT NULL,
    vendor              VARCHAR(16) NOT NULL,
    rank_type           VARCHAR(32) NOT NULL,
    rank_no             INTEGER NOT NULL,
    inner_code          BIGINT REFERENCES market.security (inner_code),
    plate_vendor        VARCHAR(16),
    plate_code          VARCHAR(64),
    name                VARCHAR(128) NOT NULL DEFAULT '',
    score               NUMERIC(20, 6),
    source_code         VARCHAR(32) REFERENCES market.data_source (code),
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (trading_day, vendor, rank_type, rank_no),
    CONSTRAINT hot_rank_vendor_chk CHECK (vendor IN ('ths', 'east', 'adata'))
);
COMMENT ON TABLE market.hot_rank_daily IS
    '热度日终快照；个股填 inner_code，热门概念可填 plate_vendor+plate_code；日内实时榜不进本表';
COMMENT ON COLUMN market.hot_rank_daily.trading_day IS '快照交易日（或自然日，采集侧与水位约定）';
COMMENT ON COLUMN market.hot_rank_daily.vendor IS 'ths|east|adata';
COMMENT ON COLUMN market.hot_rank_daily.rank_type IS
    '榜单类型，如 pop100 / hot_stock / hot_concept（采集侧枚举写入水位）';
COMMENT ON COLUMN market.hot_rank_daily.rank_no IS '名次（从 1 起）';
COMMENT ON COLUMN market.hot_rank_daily.inner_code IS '个股 → security；概念榜可空';
COMMENT ON COLUMN market.hot_rank_daily.plate_vendor IS '概念榜 → plate.vendor';
COMMENT ON COLUMN market.hot_rank_daily.plate_code IS '概念榜 → plate.plate_code';
COMMENT ON COLUMN market.hot_rank_daily.name IS '展示名（股票或概念简称）';
COMMENT ON COLUMN market.hot_rank_daily.score IS '热度分/人气值；语义随 vendor';
COMMENT ON COLUMN market.hot_rank_daily.source_code IS 'data_source';
COMMENT ON COLUMN market.hot_rank_daily.ingested_at IS '入库时间（UTC）';

CREATE INDEX IF NOT EXISTS idx_market_hot_rank_sec
    ON market.hot_rank_daily (inner_code, trading_day DESC)
    WHERE inner_code IS NOT NULL;

COMMIT;
