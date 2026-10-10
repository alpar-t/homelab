"""Anonymous OAuth bootstrap and the configured IMAP authentication capability."""
from http.cookies import SimpleCookie
import socket
import time
from urllib.parse import urlsplit, parse_qs


def bootstrap(ctx, config):
    response = ctx.http(config['url'], headers={
        'Host': 'webmail.newjoy.ro', 'X-Forwarded-Proto': 'https'},
        timeout=5, max_bytes=32768)
    headers = {k.lower(): v for k, v in response.headers.items()}
    target = urlsplit(headers.get('location', ''))
    params = parse_qs(target.query)
    cookie = SimpleCookie()
    cookie.load(headers.get('set-cookie', ''))
    expected = urlsplit(config['authorize'])
    return (response.status == 302
            and (target.scheme, target.netloc, target.path) ==
            (expected.scheme, expected.netloc, expected.path)
            and params.get('response_type') == ['code']
            and params.get('redirect_uri') == [config['callback']]
            and {'openid', 'email', 'profile'} <= set(' '.join(params.get('scope', [])).split())
            and all(len(params.get(key, [''])[0]) >= 8 for key in ('state', 'nonce', 'client_id'))
            and params.get('code_challenge_method') == ['S256']
            and len(params.get('code_challenge', [''])[0]) == 43
            and 'roundcube_sessid' in cookie and bool(cookie['roundcube_sessid'].value))


def imap_capability(ctx, config):
    deadline = time.monotonic() + min(4, ctx.remaining())
    def timeout():
        remaining = min(ctx.remaining(), deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError()
        return remaining

    with socket.create_connection((config['imap_host'], config['imap_port']), timeout()) as connection:
        buffer = bytearray()
        received = 0
        def line():
            nonlocal received
            while b'\r\n' not in buffer:
                connection.settimeout(timeout())
                part = connection.recv(min(4097 - len(buffer), 16385 - received))
                timeout()  # A peer cannot extend the total budget by trickling bytes.
                if not part:
                    raise ValueError('short protocol line')
                buffer.extend(part)
                received += len(part)
                if len(buffer) > 4096 or received > 16384:
                    raise ValueError('protocol response limit')
            end = buffer.index(b'\r\n')
            result = bytes(buffer[:end]).upper()
            del buffer[:end + 2]
            return result

        if not line().startswith(b'* OK '):
            return False
        connection.settimeout(timeout())
        connection.sendall(b'M1 CAPABILITY\r\n')
        capabilities = set()
        for _ in range(12):
            value = line()
            if value.startswith(b'* CAPABILITY '):
                capabilities.update(value.split()[2:])
            elif value.startswith(b'M1 '):
                return (value.startswith(b'M1 OK ') and b'AUTH=OAUTHBEARER' in capabilities
                        and bool({b'IMAP4REV1', b'IMAP4REV2'} & capabilities))
        return False


def run(ctx, config):
    result = []
    for name, probe, success in (
        ('Roundcube OAuth bootstrap', bootstrap, 'session cookie and authorization-code redirect with PKCE validated'),
        ('Roundcube IMAP OAuth capability', imap_capability, 'configured IMAP backend completed CAPABILITY with OAUTHBEARER')):
        try:
            healthy = probe(ctx, config)
            detail = success if healthy else 'response does not satisfy configured protocol contract'
        except Exception:
            healthy, detail = False, 'probe unavailable or malformed response; no response data retained'
        result.append(ctx.check(name, not healthy, detail))
    return result
