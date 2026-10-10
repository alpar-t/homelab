"""Connector connection capacity and one representative public semantic route."""
import ipaddress
import math
import re


def connections(body):
    samples = re.findall(r'^cloudflared_tunnel_ha_connections(?:\{[^\n]*\})?\s+([^\s]+)(?:\s+\d+)?\s*$', body.decode('ascii'), re.M)
    if len(samples) != 1:
        raise ValueError('missing or ambiguous gauge')
    value = float(samples[0])
    if not math.isfinite(value) or value < 0 or not value.is_integer():
        raise ValueError('invalid gauge')
    return value


def run(ctx, config):
    connected, sampled, unavailable = 0, 0, 0
    inventory_failed = False
    try:
        # One five-second Kubernetes GET leaves twelve seconds for the bounded
        # connector/public probes; no pagination or transport retry.
        if ctx.remaining() < 17:
            raise TimeoutError()
        page = ctx.kube.get('/api/v1/namespaces/cloudflared/pods?labelSelector=app%3Dcloudflared&limit=5')
        pods = [p for p in page['items'] if not p.get('metadata', {}).get('deletionTimestamp')]
        if page.get('metadata', {}).get('continue') or len(pods) > 4:
            raise ValueError('inventory exceeds bound')
        for pod in pods:
            sampled += 1
            try:
                address = ipaddress.ip_address(pod['status']['podIP'])
                host = f'[{address}]' if address.version == 6 else str(address)
                response = ctx.http(f'http://{host}:2000/metrics', timeout=min(2, ctx.remaining()), max_bytes=262144)
                if response.status != 200:
                    raise ValueError('metrics unavailable')
                connected += connections(response.body) >= 1
            except Exception:
                unavailable += 1
    except Exception:
        inventory_failed = True
    if inventory_failed:
        # No connector observation was made; shared runner owns telemetry failure.
        raise ValueError('connector inventory unavailable')
    expected = config['expected_replicas']
    result = [ctx.check('Cloudflare tunnel connected replicas', inventory_failed or connected < expected,
                        f'connected={connected}; expected={expected}; sampled={sampled}; unavailable={unavailable}' +
                        ('; inventory unavailable' if inventory_failed else ''),
                        severity=2 if 0 < connected < expected else 3,
                        notification='dashboard' if 0 < connected < expected else 'page')]
    try:
        response = ctx.http(config['public_url'], headers={'User-Agent': 'HomePBP-monitor/1'},
                            timeout=min(4, ctx.remaining()), max_bytes=262144)
        content_type = next((v for k, v in response.headers.items() if k.lower() == 'content-type'), '')
        good = (response.status == 200 and 'text/html' in content_type.lower() and
                all(marker.encode() in response.body for marker in config['markers']))
        detail = 'representative public HTML semantics valid' if good else 'representative public HTML semantics failed'
    except Exception:
        good, detail = False, 'representative public request unavailable'
    result.append(ctx.check('Cloudflare tunnel public route', not good, detail))
    return result
