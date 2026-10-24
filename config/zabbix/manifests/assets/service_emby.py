"""Read-only Emby contracts; never retain media metadata in results."""
import json
import re


def _get(ctx, base, path, headers=None):
    response = ctx.http(base + path, headers=headers, timeout=min(6, ctx.remaining()), max_bytes=65536)
    if response.status != 200:
        raise ValueError("unexpected status")
    value = json.loads(response.body)
    if not isinstance(value, dict):
        raise ValueError("invalid object")
    return value


def run(ctx, config):
    base = config["base_url"].rstrip("/")
    checks = []
    try:
        info = _get(ctx, base, "/System/Info/Public")
        valid = (isinstance(info.get("Version"), str)
                 and re.fullmatch(r"[0-9]+(?:\.[0-9]+){2,3}", info["Version"])
                 and isinstance(info.get("Id"), str) and bool(info["Id"]))
        checks.append(ctx.check("Emby public server contract", not valid,
                                "server-info schema valid" if valid else "server-info schema invalid"))
    except Exception:
        checks.append(ctx.check("Emby public server contract", True, "server-info request unavailable or invalid"))
    try:
        if ctx.remaining() < 5:
            raise TimeoutError()
        page = ctx.kube.get('/api/v1/namespaces/media/pods?labelSelector=app.kubernetes.io%2Fname%3Demby&limit=10')
        if page.get('metadata', {}).get('continue'):
            raise ValueError('incomplete pod inventory')
        pods = [pod for pod in page['items'] if not pod.get('metadata', {}).get('deletionTimestamp')]
        if len(pods) != 1:
            raise ValueError('expected one Emby pod')
        pod = pods[0]
        containers = [c for c in pod.get('spec', {}).get('containers', []) if c.get('name') == 'emby']
        statuses = [s for s in pod.get('status', {}).get('containerStatuses', []) if s.get('name') == 'emby']
        if len(containers) != 1 or len(statuses) != 1:
            raise ValueError('Emby container missing')
        command = containers[0].get('readinessProbe', {}).get('exec', {}).get('command', [])
        probe = ' '.join(command)
        configured = ('/data/movies/media/movies' in probe and 'head -c 4096' in probe)
        readable = (configured and pod.get('status', {}).get('phase') == 'Running'
                    and statuses[0].get('ready') is True and 'running' in statuses[0].get('state', {}))
        detail = ('Emby public API and one movie file are readable' if readable
                  else 'Emby movie-read readiness failed or probe missing')
    except Exception:
        readable, detail = False, 'Emby movie-read readiness unavailable'
    checks.append(ctx.check('Emby movie file readable', not readable, detail, severity=5))
    checks.append(dict(ctx.check("Emby scoped library query", True,
        "coverage deferred: no native session token or household-library access is granted to monitoring",
        severity=1), observation='deferred', notification='dashboard'))
    return checks
