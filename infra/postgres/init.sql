-- EquityLab MVP schema bootstrap
--
-- 仅在 Postgres 数据卷首次初始化时由 docker-entrypoint-initdb.d 执行。
-- 已有卷时修改本文件不会自动重跑，需手工执行 migrations/ 或重建 volume。
--
-- 行情历史表见同目录挂载的 02_market_schema.sql（market schema）。
-- 命名约定：snake_case、显式主键、查询路径二级索引、COMMENT。

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

COMMENT ON TABLE audit_events IS '审计日志；detail 存 JSON 载荷';
COMMENT ON TABLE chat_sessions IS '聊天会话元数据';
COMMENT ON COLUMN audit_events.detail IS '结构化审计载荷（JSONB，便于按 key 查询）';

-- public.klines 已废弃：历史 OHLCV 见 market.bar_daily / market.bar_minute
-- （docs/2026-10-26-market-postgres-schema.md）
