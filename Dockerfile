FROM python:3.13-slim AS builder

LABEL org.opencontainers.image.authors="Jonny Le <jonny.le@computacenter.com>" \
      org.opencontainers.image.source="https://github.com/CC-Digital-Innovation/reconcile-snow-prtg"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

COPY . .

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd -r -u 10001 appuser

COPY --from=builder /install /usr/local
COPY --from=builder /app /app

USER appuser

EXPOSE 80

CMD [ "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80" ]
