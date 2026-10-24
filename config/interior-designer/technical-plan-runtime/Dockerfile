FROM docker.io/library/python:3.13.17-alpine@sha256:fa0bb0d0cd7c7d6cef30a69094d32ac2b71c7304c87c6107fec100e1ee4eda02

LABEL org.opencontainers.image.source="https://github.com/alpar-t/homelab" \
      org.opencontainers.image.description="Minimal runtime for Baloo technical plan scripts"

# The plan API and renderer use PEP 723 script dependencies from Baloo's
# git-synced source. Open WebUI 0.11.4+ does not retain uv in its runtime.
COPY --from=ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff /uv /uvx /usr/local/bin/

ENV UV_CACHE_DIR=/opt/uv-cache \
    UV_NO_MANAGED_PYTHON=true \
    UV_PYTHON=/usr/local/bin/python \
    UV_LINK_MODE=copy

COPY api-deps.py renderer-deps.py /opt/technical-plan-deps/

RUN apk add --no-cache cairo fontconfig font-dejavu \
    && python -c 'import ctypes; ctypes.CDLL("libcairo.so.2")' \
    && uv --version \
    && uv run --script /opt/technical-plan-deps/api-deps.py \
    && uv run --script /opt/technical-plan-deps/renderer-deps.py \
    && UV_OFFLINE=true uv run --script /opt/technical-plan-deps/api-deps.py \
    && UV_OFFLINE=true uv run --script /opt/technical-plan-deps/renderer-deps.py \
    && chown -R 1000:1000 /opt/uv-cache

ENV HOME=/work \
    UV_OFFLINE=true

USER 1000:1000
