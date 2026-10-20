# build context = 仓库根
FROM rust:1-bookworm AS build
WORKDIR /build
COPY packages/qdb-rs ./packages/qdb-rs
COPY services/market-data/Cargo.toml ./services/market-data/Cargo.toml
WORKDIR /build/services/market-data
RUN mkdir src && echo 'fn main(){}' > src/main.rs \
    && cargo build --release \
    && rm -rf src
COPY services/market-data/src ./src
RUN touch src/main.rs && cargo build --release \
    && strip /build/services/market-data/target/release/equitylab-market-data

FROM debian:bookworm-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser
WORKDIR /app
COPY --from=build /build/services/market-data/target/release/equitylab-market-data /app/equitylab-market-data
USER appuser
EXPOSE 3002
ENV PORT=3002
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=10 \
  CMD curl -fsS http://127.0.0.1:3002/health || exit 1
CMD ["/app/equitylab-market-data"]
