FROM docker.io/library/python:3.13.17-alpine@sha256:fa0bb0d0cd7c7d6cef30a69094d32ac2b71c7304c87c6107fec100e1ee4eda02

LABEL org.opencontainers.image.source="https://github.com/alpar-t/homelab" \
      org.opencontainers.image.description="Minimal runtime for Baloo technical plan scripts"

# The plan API and renderer use PEP 723 script dependencies from Baloo's
# git-synced source. Open WebUI 0.11.4+ does not retain uv in its runtime.
COPY --from=ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff /uv /uvx /usr/local/bin/

RUN apk add --no-cache cairo fontconfig font-dejavu \
    && python -c 'import ctypes; ctypes.CDLL("libcairo.so.2")' \
    && uv --version \
    && UV_CACHE_DIR=/tmp/uv-smoke uv run --no-project \
      --with 'cairosvg>=2.8,<3' --with 'pypdf>=6,<7' \
      python -c 'import cairosvg; from pypdf import PdfReader; import io; svg = b"<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"10\" height=\"10\"><circle cx=\"5\" cy=\"5\" r=\"2\"/></svg>"; pdf = cairosvg.svg2pdf(bytestring=svg); png = cairosvg.svg2png(bytestring=svg); assert len(PdfReader(io.BytesIO(pdf)).pages) == 1 and png.startswith(b"\x89PNG")' \
    && rm -rf /tmp/uv-smoke

ENV HOME=/work \
    UV_NO_MANAGED_PYTHON=true \
    UV_PYTHON=/usr/local/bin/python \
    UV_LINK_MODE=copy

USER 1000:1000
