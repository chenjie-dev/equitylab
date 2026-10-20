# multi-stage；build context = 仓库根
FROM python:3.12-slim AS build
WORKDIR /app
COPY packages/qdb-py /tmp/qdb-py
COPY apps/research/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install /tmp/qdb-py \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim AS runtime
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser
COPY --from=build /install /usr/local
COPY apps/research/main.py .
COPY apps/research/app ./app
USER appuser
EXPOSE 8002
ENV PORT=8002
ENV PYTHONPATH=/app
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=10 \
  CMD curl -fsS http://127.0.0.1:8002/health || exit 1
CMD ["python", "main.py"]
