# syntax=docker/dockerfile:1@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e
# Candidate-only PG16 overlay: fixed Trixie Perl and hashed Python wheels.
ARG POSTGRES_BASE
FROM ${POSTGRES_BASE}

LABEL org.opencontainers.image.source="https://github.com/alpar-t/homelab" \
      org.opencontainers.image.description="CloudNativePG PG16 with patched Perl, certifi, and PyJWT"

USER root
RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends --only-upgrade \
      perl-base=5.40.1-6+deb13u1 \
      perl=5.40.1-6+deb13u1 \
      libperl5.40=5.40.1-6+deb13u1 \
      perl-modules-5.40=5.40.1-6+deb13u1; \
    dpkg-query -W -f='${binary:Package}=${Version}\n' \
      perl-base perl libperl5.40 perl-modules-5.40; \
    rm -rf /var/lib/apt/lists/*

COPY requirements-overlay.txt /tmp/requirements-overlay.txt
RUN python3 -m pip install --disable-pip-version-check --no-cache-dir \
      --no-deps --only-binary=:all: --require-hashes \
      -r /tmp/requirements-overlay.txt \
    && python3 -m pip check \
    && python3 - <<'PY'
from importlib.metadata import version
from pathlib import Path
import subprocess

import boto3
import certifi
import jwt
from botocore.httpsession import get_cert_path

assert version('certifi') == '2026.10.23'
assert version('PyJWT') == '2.15.1'
assert get_cert_path(True) == certifi.where()
assert 'emSign ECC Root CA - G3' not in Path(certifi.where()).read_text()
token = jwt.encode({'sub': 'synthetic-probe'}, 'synthetic-build-key', algorithm='HS256')
assert jwt.decode(token, 'synthetic-build-key', algorithms=['HS256'])['sub'] == 'synthetic-probe'
assert boto3.__version__
for command in ('barman-cloud-backup', 'barman-cloud-wal-archive', 'postgres'):
    subprocess.run((command, '--version'), check=True)
subprocess.run(('perl', '-e', 'print "perl smoke ok\\n"'), check=True)
PY

# CloudNativePG upstream runs PostgreSQL as uid 26.
USER 26
