# syntax=docker/dockerfile:1
# Keep Pure-FTPd 1.0.50's actual server and pure-pw binaries, but leave the
# upstream image's unused Perl, MariaDB, inetd and build packages behind.
FROM docker.io/stilliard/pure-ftpd:trixie-1.0.50@sha256:54eff59f458532899a4f814da339a7c0921ddf0b4d8b3b87318a162cb4232687 AS upstream

FROM docker.io/library/debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad AS runtime

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      ca-certificates libcap2 libcrypt1 libpam0g libsodium23 libssl3t64 \
      zlib1g libzstd1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=upstream /usr/sbin/pure-ftpd /usr/sbin/pure-ftpd
COPY --from=upstream /usr/bin/pure-pw /usr/bin/pure-pw
COPY --from=upstream /usr/share/doc/pure-ftpd/copyright /licenses/pure-ftpd-copyright
COPY start-ftp.sh /usr/local/bin/start-ftp.sh

RUN chmod +x /usr/local/bin/start-ftp.sh \
    && ldd /usr/sbin/pure-ftpd > /tmp/pure-ftpd-ldd \
    && ldd /usr/bin/pure-pw > /tmp/pure-pw-ldd \
    && ! grep -q 'not found' /tmp/pure-ftpd-ldd \
    && ! grep -q 'not found' /tmp/pure-pw-ldd \
    && /usr/sbin/pure-ftpd -h | grep -q 'v1.0.50' \
    && for package in perl-base libmariadb3 mariadb-common; do \
         ! dpkg-query -W "$package" >/dev/null 2>&1 || exit 1; \
       done \
    && rm /tmp/pure-ftpd-ldd /tmp/pure-pw-ldd

EXPOSE 21 30000-30009
ENTRYPOINT ["/usr/local/bin/start-ftp.sh"]

# CI builds this target before publishing runtime. Python is only in this
# disposable test stage; it exercises login, passive transfer and on-disk data.
FROM runtime AS smoke
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*
RUN set -eu; \
    FTP_USER_NAME=scanner FTP_USER_PASS=smoke-only FTP_USER_HOME=/scanner \
    FTP_USER_UID=1000 FTP_USER_GID=1000 FTP_PASSIVE_PORTS=30000:30009 \
    PUBLICHOST=127.0.0.1 ADDED_FLAGS='-d -d' \
    /usr/local/bin/start-ftp.sh > /tmp/ftp.log 2>&1 & \
    server_pid=$!; \
    trap 'kill "$server_pid" 2>/dev/null || true' EXIT; \
    python3 - <<'PY'
import ftplib
import io
import pathlib
import time

for attempt in range(50):
    try:
        ftp = ftplib.FTP()
        ftp.connect('127.0.0.1', 21, timeout=1)
        ftp.login('scanner', 'smoke-only')
        break
    except (OSError, ftplib.Error) as exc:
        if attempt == 49:
            raise RuntimeError('Pure-FTPd never accepted pure-pw login') from exc
        time.sleep(0.1)
payload = b'paperless-ftp-runtime-smoke\n'
ftp.storbinary('STOR smoke.txt', io.BytesIO(payload))
ftp.quit()
assert pathlib.Path('/scanner/smoke.txt').read_bytes() == payload
PY
