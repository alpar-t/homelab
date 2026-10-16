"""Read-only Immich metadata and Redis dependency checks; never fetch assets."""
import json
import socket


def _json(ctx, url, headers=None):
    response = ctx.http(url, headers=headers, timeout=min(5, ctx.remaining()), max_bytes=16384)
    if response.status != 200:
        raise ValueError("API unavailable")
    value = json.loads(response.body)
    if not isinstance(value, dict):
        raise ValueError("API schema")
    return value


def _redis(ctx, config):
    timeout = min(4, ctx.remaining())
    if timeout <= 0:
        raise TimeoutError()
    with socket.create_connection((config['redis_host'], config['redis_port']), timeout=timeout) as conn:
        conn.settimeout(min(4, ctx.remaining()))
        conn.sendall(b"*2\r\n$4\r\nINFO\r\n$11\r\npersistence\r\n")
        data = bytearray()
        expected = None
        while expected is None or len(data) < expected:
            if ctx.remaining() <= 0:
                raise TimeoutError()
            conn.settimeout(min(4, ctx.remaining()))
            part = conn.recv(min(4096, 16385 - len(data)))
            if not part or len(data) + len(part) > 16384:
                raise ValueError("Redis response")
            data.extend(part)
            if expected is None and b"\r\n" in data:
                head, _ = bytes(data).split(b"\r\n", 1)
                if not head.startswith(b"$"):
                    raise ValueError("Redis protocol")
                size = int(head[1:])
                if not 0 <= size <= 16000:
                    raise ValueError("Redis size")
                expected = len(head) + 2 + size + 2
        raw = bytes(data)
        head, body = raw.split(b"\r\n", 1)
        if len(raw) != expected or not body.endswith(b"\r\n"):
            raise ValueError("Redis framing")
        fields = dict(line.split(":", 1) for line in body[:-2].decode('ascii').splitlines()
                      if line and not line.startswith('#'))
        if fields.get('loading') != '0':
            raise ValueError("Redis loading")
        if fields.get('rdb_last_bgsave_status') != 'ok' or fields.get('aof_last_write_status') != 'ok':
            raise ValueError("Redis persistence")


def run(ctx, config):
    rows = []
    base = config['server_url'].rstrip('/')
    try:
        version = _json(ctx, base + '/api/server/version')
        settings = _json(ctx, base + '/api/server/config')
        if not all(type(version.get(key)) is int and version[key] >= 0 for key in ('major', 'minor', 'patch')):
            raise ValueError("version schema")
        if settings.get('isInitialized') is not True or settings.get('isOnboarded') is not True:
            raise ValueError("initialization")
        if settings.get('maintenanceMode') is not False:
            raise ValueError("maintenance")
        rows.append(ctx.check('Immich public API configuration', False, 'version/config schemas valid; initialized and available'))
    except Exception:
        rows.append(ctx.check('Immich public API configuration', True, 'API unavailable, malformed, uninitialized or in maintenance'))
    try:
        token = ctx.secret(config['credential_key'])
    except Exception:
        token = None
    try:
        if token is None:
            raise ValueError('monitor credential unavailable')
        stats = _json(ctx, base + '/api/assets/statistics', {'x-api-key': token})
        if not all(type(stats.get(key)) is int and stats[key] >= 0 for key in ('images', 'videos', 'total')):
            raise ValueError("statistics schema")
        if stats['total'] != stats['images'] + stats['videos']:
            raise ValueError("statistics inconsistent")
        rows.append(ctx.check('Immich authenticated asset statistics', False, 'scoped read-only database statistics valid; empty library allowed'))
    except Exception:
        if token is None:
            rows.append(dict(ctx.check('Immich authenticated asset statistics', True, 'coverage deferred: dedicated read-only credential unavailable', 1), observation='deferred', notification='dashboard'))
        else:
            rows.append(ctx.check('Immich authenticated asset statistics', True, 'asset statistics rejected, unavailable or malformed'))
    try:
        _redis(ctx, config)
        rows.append(ctx.check('Immich Redis dependency', False, 'Redis INFO valid; loading complete and persistence status healthy'))
    except Exception:
        rows.append(ctx.check('Immich Redis dependency', True, 'Redis unavailable, malformed, loading or reporting persistence failure'))
    return rows
