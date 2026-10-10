"""Small anonymous search and read-only MCP capability checks."""
import json
from urllib.parse import urlencode, urlsplit


def rpc_body(response, request_id):
    if response.status != 200:
        raise ValueError('MCP HTTP response')
    body = response.body.decode('utf-8')
    if body.lstrip().startswith('{'):
        messages = [json.loads(body)]
    else:
        messages = [json.loads(line[5:].strip()) for line in body.splitlines()
                    if line.startswith('data:')]
    for message in messages:
        if isinstance(message, dict) and message.get('id') == request_id and message.get('jsonrpc') == '2.0' and 'error' not in message:
            result = message.get('result')
            if isinstance(result, dict):
                return result
    raise ValueError('MCP result missing')


def run(ctx, config):
    checks = []
    try:
        query = config['query']
        response = ctx.http(config['search_url'] + '?' + urlencode({'q': query, 'format': 'json', 'categories': 'general'}),
                            timeout=min(12, ctx.remaining()), max_bytes=262144)
        data = json.loads(response.body)
        if response.status != 200 or not isinstance(data, dict) or data.get('query') != query or not isinstance(data.get('results'), list):
            raise ValueError('invalid search response')
        usable = sum(isinstance(row, dict) and isinstance(row.get('title'), str) and bool(row['title'].strip())
                     and isinstance(row.get('url'), str) and urlsplit(row['url']).scheme in ('http', 'https')
                     and bool(urlsplit(row['url']).hostname) for row in data['results'])
        checks.append(ctx.check('SearXNG query execution', not usable,
                                'usable search links=' + str(usable)))
    except Exception:
        checks.append(ctx.check('SearXNG query execution', True, 'search unavailable or invalid response'))

    headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
    session = None
    def post(payload):
        return ctx.http(config['mcp_url'], method='POST', headers=headers,
                        data=json.dumps(payload).encode(), timeout=min(4, ctx.remaining()), max_bytes=131072)
    try:
        response = post({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2024-11-05', 'capabilities': {},
            'clientInfo': {'name': 'zabbix-functional-monitor', 'version': '1'}}})
        info = rpc_body(response, 1)
        session = next((value for key, value in response.headers.items() if key.lower() == 'mcp-session-id'), None)
        if session:
            headers['Mcp-Session-Id'] = session
        if not isinstance(info.get('protocolVersion'), str) or not isinstance(info.get('capabilities'), dict) or 'tools' not in info['capabilities']:
            raise ValueError('MCP capabilities')
        headers['MCP-Protocol-Version'] = info['protocolVersion']
        notification = post({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        if notification.status not in (200, 202, 204):
            raise ValueError('MCP initialization')
        tools = rpc_body(post({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}}), 2).get('tools')
        valid = isinstance(tools, list) and any(isinstance(tool, dict) and tool.get('name') == 'searxng_web_search'
                    and isinstance(tool.get('inputSchema'), dict) and tool['inputSchema'].get('type') == 'object' for tool in tools)
        checks.append(ctx.check('SearXNG MCP search catalog', not valid, 'search tool schema available' if valid else 'search tool schema missing'))
    except Exception:
        checks.append(ctx.check('SearXNG MCP search catalog', True, 'MCP initialization or catalog unavailable'))
    finally:
        if session and ctx.remaining() > 0:
            try:
                ctx.http(config['mcp_url'], method='DELETE', headers=headers,
                         timeout=min(2, ctx.remaining()), max_bytes=4096)
            except Exception:
                pass
    return checks
