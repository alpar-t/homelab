# syntax=docker/dockerfile:1
# Build the signed 1.0.54 release with the PureDB and TLS capabilities used
# by the existing FTP sidecar. The release tag was verified to point at this
# commit; fail if the remote tag is changed.
FROM docker.io/library/alpine:3.23@sha256:ff7f0c727dd796aa36787bfcd9a64bf35a6ce72a73451b3359fde849b6703d63 AS build

ARG PURE_FTPD_COMMIT=3fe02789c4f0e5756f3f612e32edee9aa5d49455
RUN apk add --no-cache \
      autoconf automake build-base ca-certificates git libcap-dev \
      libtool libsodium-dev openssl-dev pkgconf
RUN git clone --branch 1.0.54 --depth 1 \
      https://github.com/jedisct1/pure-ftpd.git /src \
    && test "$(git -C /src rev-parse HEAD)" = "$PURE_FTPD_COMMIT" \
    && cd /src \
    && ./autogen.sh \
    && ./configure --prefix=/usr --with-puredb --with-tls --with-altlog \
      --without-pam --without-inetd \
    && make -j2 \
    && make DESTDIR=/out install-strip

FROM docker.io/library/alpine:3.23@sha256:ff7f0c727dd796aa36787bfcd9a64bf35a6ce72a73451b3359fde849b6703d63 AS runtime

LABEL org.opencontainers.image.source="https://github.com/jedisct1/pure-ftpd" \
      org.opencontainers.image.version="1.0.54" \
      org.opencontainers.image.revision="3fe02789c4f0e5756f3f612e32edee9aa5d49455"
RUN apk add --no-cache ca-certificates libcap libcrypto3 libsodium libssl3 \
    && addgroup -S _pure-ftpd \
    && adduser -S -D -H -h /var/empty -s /sbin/nologin \
      -G _pure-ftpd _pure-ftpd \
    && addgroup -g 1000 ftpgroup \
    && adduser -D -H -u 1000 -G ftpgroup -s /sbin/nologin ftpuser

COPY --from=build /out/usr/sbin/pure-ftpd /usr/sbin/pure-ftpd
COPY --from=build /out/usr/bin/pure-pw /usr/bin/pure-pw
COPY --from=build /src/COPYING /licenses/pure-ftpd-COPYING
COPY start-ftp.sh /usr/local/bin/start-ftp.sh

RUN set -eux; \
    chmod +x /usr/local/bin/start-ftp.sh; \
    ldd /usr/sbin/pure-ftpd; \
    ldd /usr/bin/pure-pw; \
    for package in perl mariadb-connector-c; do \
         ! apk info -e "$package" >/dev/null 2>&1 || exit 1; \
       done

EXPOSE 21 30000-30009
ENTRYPOINT ["/usr/local/bin/start-ftp.sh"]

# CI builds this target before publishing runtime. Python is only in this
# disposable test stage; it exercises login, passive transfer and on-disk data.
FROM runtime AS smoke
RUN apk add --no-cache python3
RUN set -eu; \
    busybox syslogd -O /tmp/syslog; \
    FTP_USER_NAME=scanner FTP_USER_PASS=smoke-only FTP_USER_HOME=/scanner \
    FTP_USER_UID=1000 FTP_USER_GID=1000 FTP_PASSIVE_PORTS=30000:30009 \
    PUBLICHOST=127.0.0.1 ADDED_FLAGS='-d -d' \
    /usr/local/bin/start-ftp.sh > /tmp/ftp.log 2>&1 & \
    server_pid=$!; \
    trap 'status=$?; if [ "$status" -ne 0 ]; then cat /tmp/ftp.log /tmp/syslog; if kill -0 "$server_pid" 2>/dev/null; then echo "FTP start still running"; else wait "$server_pid" || echo "FTP start exited with $?" ; fi; fi; kill "$server_pid" 2>/dev/null || true' EXIT; \
    python3 - <<'PY'
import ftplib
import io
import pathlib
import time

for attempt in range(300):
    try:
        ftp = ftplib.FTP()
        ftp.connect('127.0.0.1', 21, timeout=5)
        ftp.login('scanner', 'smoke-only')
        break
    except (OSError, ftplib.Error) as exc:
        if attempt == 299:
            raise RuntimeError('Pure-FTPd never accepted pure-pw login') from exc
        time.sleep(0.1)
payload = b'paperless-ftp-runtime-smoke\n'
ftp.storbinary('STOR smoke.txt', io.BytesIO(payload))
ftp.quit()
assert pathlib.Path('/scanner/smoke.txt').read_bytes() == payload
PY
