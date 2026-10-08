"""Anonymous OIDC metadata and representative sign-in flow validation."""
import base64
import json
from urllib.parse import parse_qs, urlsplit


def request(ctx, url):
    return ctx.http(url, timeout=min(5, ctx.remaining()), max_bytes=65536)


def integer(value):
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ValueError()
    raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
    return int.from_bytes(raw, 'big')


def signing_key(key, algorithms):
    if not isinstance(key, dict) or not isinstance(key.get('kid'), str) or not key['kid']:
        return False
    if key.get('use', 'sig') != 'sig' or 'verify' not in key.get('key_ops', ['verify']):
        return False
    # Pocket ID's RSA signing contract; never accept symmetric/private keys.
    if any(field in key for field in ('d', 'p', 'q', 'k')):
        return False
    return (key.get('kty') == 'RSA' and key.get('alg', 'RS256') == 'RS256'
            and 'RS256' in algorithms and integer(key.get('n')).bit_length() >= 2048
            and integer(key.get('e')) >= 3 and integer(key.get('e')) % 2 == 1)


def run(ctx, config):
    records = []
    expected = config["endpoints"]
    try:
        discovery = request(ctx, config['internal_url'] + '/.well-known/openid-configuration')
        metadata = json.loads(discovery.body)
        good = (discovery.status == 200 and isinstance(metadata, dict)
                and metadata.get('issuer') == config['issuer']
                and all(metadata.get(k) == v for k, v in expected.items())
                and 'code' in metadata.get('response_types_supported', [])
                and 'openid' in metadata.get('scopes_supported', []))
        if not good:
            raise ValueError()
        jwks = request(ctx, config['internal_url'] + '/.well-known/jwks.json')
        keys = json.loads(jwks.body)
        good = (jwks.status == 200 and isinstance(keys, dict)
                and isinstance(keys.get('keys'), list) and 0 < len(keys['keys']) <= 32
                and any(signing_key(k, metadata.get('id_token_signing_alg_values_supported', []))
                        for k in keys['keys']))
        records.append(ctx.check('Pocket ID OIDC metadata and signing keys', not good,
                                 'discovery and RSA signing key valid' if good else 'usable signing key unavailable'))
    except Exception:
        records.append(ctx.check('Pocket ID OIDC metadata and signing keys', True,
                                 'OIDC metadata unavailable or invalid'))
    for proxy in config['proxies']:
        good = False
        try:
            response = request(ctx, proxy['url'] + '/oauth2/start')
            location = next((v for k, v in response.headers.items() if k.lower() == 'location'), '')
            target = urlsplit(location)
            query = parse_qs(target.query, keep_blank_values=True, max_num_fields=32)
            endpoint = urlsplit(expected['authorization_endpoint'])
            cookie = next((v for k, v in response.headers.items() if k.lower() == 'set-cookie'), '')
            good = (response.status == 302 and (target.scheme, target.netloc, target.path)
                    == (endpoint.scheme, endpoint.netloc, endpoint.path)
                    and not target.fragment and query.get('client_id') == [proxy['client_id']]
                    and query.get('redirect_uri') == [proxy['callback']]
                    and query.get('response_type') == ['code']
                    and len(query.get('state', [])) == 1 and 16 <= len(query['state'][0]) <= 2048
                    and {'openid', 'groups'}.issubset(set(query.get('scope', [''])[0].split()))
                    and '_csrf=' in cookie and 'httponly' in cookie.lower()
                    and 'secure' in cookie.lower())
        except Exception:
            pass
        records.append(ctx.check('Pocket ID sign-in proxy ' + proxy['name'], not good,
                                 'authorization redirect and CSRF cookie valid' if good else 'authorization bootstrap unavailable or invalid'))
    return records
