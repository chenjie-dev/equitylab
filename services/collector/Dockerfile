FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser
# build context = 仓库根
COPY packages/qdb-py /tmp/qdb-py
COPY services/collector/requirements.txt .
RUN pip install --no-cache-dir /tmp/qdb-py \
    && pip install --no-cache-dir -r requirements.txt \
    && rm -rf /tmp/qdb-py
COPY services/collector/main.py services/collector/markets.py services/collector/binance_ws.py services/collector/retention.py services/collector/write_gate.py services/collector/ashare_universe.py services/collector/pg_market.py ./
USER appuser
ENV PYTHONUNBUFFERED=1
CMD ["python", "main.py"]
