# syntax=docker/dockerfile:1.7
# Build context: ./backend
# ---- build stage: install dependencies into a venv -----------------------------------------------------------
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt requirements-ml.txt requirements-otel.txt ./
ARG INSTALL_ML=false
ARG INSTALL_OTEL=false
RUN pip install -r requirements.txt \
 && if [ "$INSTALL_ML" = "true" ]; then pip install -r requirements-ml.txt; fi \
 && if [ "$INSTALL_OTEL" = "true" ]; then pip install -r requirements-otel.txt; fi

# ---- runtime stage: small, non-root, no build tools ------------------------------------------------------------
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/opt/venv/bin:$PATH"
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home /app --shell /usr/sbin/nologin app \
 && mkdir -p /app /data && chown app:app /app /data
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY --chown=app:app app ./app
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app scripts ./scripts
COPY --chown=app:app docker-entrypoint.sh /entrypoint.sh
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=25s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status==200 else 1)"
ENTRYPOINT ["/entrypoint.sh"]
# uvicorn trusts X-Forwarded-* only from FORWARDED_ALLOW_IPS (default 127.0.0.1); set it to your proxy's address range.
CMD ["uvicorn", "app.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
