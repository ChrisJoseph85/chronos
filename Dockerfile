# syntax=docker/dockerfile:1
# Chronos backend image. Build host here has no Docker daemon (see
# docs/docker.md) — this file is verified structurally by tests/phase_6.

FROM python:3.14.7-slim-bookworm AS builder
WORKDIR /app
COPY pyproject.toml ./
COPY chronos ./chronos
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.14.7-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/install/bin:$PATH \
    PYTHONPATH=/install/lib/python3.14/site-packages
WORKDIR /app
COPY --from=builder /install /install
RUN useradd -u 10001 -m chronos && mkdir -p /data && chown chronos:chronos /data
USER chronos
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health')"
ENTRYPOINT ["chronos"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080", "--db", "/data/chronos.db"]
