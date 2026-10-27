FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser
COPY packages/market-py /tmp/market-py
COPY services/akshare-ingest/requirements.txt .
RUN pip install --no-cache-dir /tmp/market-py \
    && pip install --no-cache-dir -r requirements.txt \
    && rm -rf /tmp/market-py
COPY services/akshare-ingest/*.py ./
USER appuser
ENV PYTHONUNBUFFERED=1
CMD ["python", "main.py"]
