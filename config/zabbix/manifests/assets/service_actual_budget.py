"""Actual 26.8 read-only account/backend and MCP protection contracts."""
import json
import re


def request(ctx, url, **kwargs):
    response = ctx.http(url, timeout=min(5, ctx.remaining()), max_bytes=65536, **kwargs)
    return response.status, json.loads(response.body)


def run(ctx, config):
    rows = []
    base = config['server_url'].rstrip('/')
    try:
        status, info = request(ctx, base + '/info')
        build = info.get('build', {})
        valid = status == 200 and build.get('name') == '@actual-app/sync-server' and isinstance(build.get('version'), str) and re.fullmatch(r'\d+\.\d+\.\d+(?:[-+].+)?', build['version'])
        status, bootstrap = request(ctx, base + '/account/needs-bootstrap')
        data = bootstrap.get('data', {})
        methods = data.get('availableLoginMethods')
        valid = valid and status == 200 and bootstrap.get('status') == 'ok' and data.get('bootstrapped') is True and isinstance(methods, list) and any(isinstance(m, dict) and m.get('method') == 'password' for m in methods)
        rows.append(ctx.check('Actual backend contract', not valid, 'build and bootstrapped password-login contract valid' if valid else 'backend build/bootstrap contract invalid'))
    except Exception:
        rows.append(ctx.check('Actual backend contract', True, 'backend contract unavailable'))
    rows.append(dict(ctx.check('Actual monitor account metadata', True, 'coverage deferred: native BASIC sessions permit writes; no financial credential is mounted', severity=1), observation='deferred', notification='dashboard'))
    try:
        status, result = request(ctx, config['mcp_url'], method='POST', headers={'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}, data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}}).encode())
        valid = status == 401 and result.get('error') == 'Unauthorized: Missing Authorization header'
        rows.append(ctx.check('Actual MCP authentication contract', not valid, 'HTTP transport rejects anonymous catalog request' if valid else 'MCP anonymous rejection contract invalid'))
    except Exception:
        rows.append(ctx.check('Actual MCP authentication contract', True, 'MCP authentication contract unavailable'))
    return rows
