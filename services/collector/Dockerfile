FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py markets.py ./
USER appuser
ENV PYTHONUNBUFFERED=1
CMD ["python", "main.py"]
