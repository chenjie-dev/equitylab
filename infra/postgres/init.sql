-- EquityLab MVP schema bootstrap
--
-- 仅在 Postgres 数据卷首次初始化时由 docker-entrypoint-initdb.d 执行。
-- 已有卷时修改本文件不会自动重跑，需手工迁移或重建 volume。
--
-- 命名与索引约定参考 supabase-postgres-best-practices：
--   snake_case、显式主键、查询路径上的二级索引、表/列 COMMENT。

CREATE TABLE IF NOT EXISTS klines (
    symbol   VARCHAR(20)  NOT NULL,
    period   VARCHAR(10)  NOT NULL,
    datetime VARCHAR(32)  NOT NULL,
    open     NUMERIC(12, 4),
    high     NUMERIC(12, 4),
    low      NUMERIC(12, 4),
    close    NUMERIC(12, 4),
    volume   BIGINT,
    amount   NUMERIC(18, 2),
    PRIMARY KEY (symbol, period, datetime)
);

CREATE INDEX IF NOT EXISTS idx_klines_symbol_period
    ON klines (symbol, period);

CREATE TABLE IF NOT EXISTS audit_events (
    id         BIGSERIAL PRIMARY KEY,
    tenant_id  VARCHAR(64),
    user_id    VARCHAR(64),
    action     VARCHAR(128) NOT NULL,
    detail     JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_events_created_at
    ON audit_events (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_events_tenant_created
    ON audit_events (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id         UUID PRIMARY KEY,
    user_id    VARCHAR(64),
    title      VARCHAR(256),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_created
    ON chat_sessions (user_id, created_at DESC);

COMMENT ON TABLE klines IS '历史 OHLCV；主键 (symbol, period, datetime)';
COMMENT ON TABLE audit_events IS '审计日志；detail 存 JSON 载荷';
COMMENT ON TABLE chat_sessions IS '聊天会话元数据';
COMMENT ON COLUMN audit_events.detail IS '结构化审计载荷（JSONB，便于按 key 查询）';
