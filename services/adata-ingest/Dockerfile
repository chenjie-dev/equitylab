FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser
COPY packages/market-py /tmp/market-py
COPY services/adata-ingest/requirements.txt .
RUN pip install --no-cache-dir /tmp/market-py \
    && pip install --no-cache-dir -r requirements.txt \
    && rm -rf /tmp/market-py
COPY services/adata-ingest/*.py ./
# 测试文件不进运行镜像主路径依赖；若 COPY 带入 test_* 无妨
USER appuser
ENV PYTHONUNBUFFERED=1
CMD ["python", "main.py"]
