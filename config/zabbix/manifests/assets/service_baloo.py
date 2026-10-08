"""Read-only Kubernetes MCP negotiation/catalog and fixed Service metadata check."""
import json


PROTOCOL = '2024-11-05'


def rpc(ctx, url, payload, session=None):
    headers = {'Content-Type': 'application/json',
               'Accept': 'application/json, text/event-stream',
               'MCP-Protocol-Version': PROTOCOL}
    if session:
        headers['Mcp-Session-Id'] = session
    return ctx.http(url, method='POST', headers=headers,
                    data=json.dumps(payload).encode(), timeout=5, max_bytes=262144)


def result(response, request_id):
    if response.status != 200:
        raise ValueError('MCP HTTP failure')
    content_type = next((v for k, v in response.headers.items()
                         if k.lower() == 'content-type'), '').split(';')[0].strip()
    if content_type == 'application/json':
        messages = [json.loads(response.body)]
    elif content_type == 'text/event-stream':
        messages = []
        for event in response.body.decode().replace('\r\n', '\n').split('\n\n'):
            data = '\n'.join(line[5:].lstrip(' ') for line in event.split('\n')
                             if line.startswith('data:'))
            if data:
                messages.append(json.loads(data))
    else:
        raise ValueError('MCP content type invalid')
    matches = [message for message in messages if isinstance(message, dict)
               and message.get('id') == request_id]
    if len(matches) != 1:
        raise ValueError('MCP reply missing or ambiguous')
    message = matches[0]
    if message.get('jsonrpc') != '2.0' or 'error' in message or not isinstance(message.get('result'), dict):
        raise ValueError('MCP result invalid')
    return message['result']


def run(ctx, config):
    session = None
    good = False
    detail = 'MCP negotiation or catalog unavailable; inspect adapter locally'
    try:
        response = rpc(ctx, config['url'], {
            'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                'protocolVersion': PROTOCOL, 'capabilities': {},
                'clientInfo': {'name': 'zabbix-functional-monitor', 'version': '1'}}})
        session = next((v for k, v in response.headers.items() if k.lower() == 'mcp-session-id'), None)
        if session and (len(session) > 256 or '\r' in session or '\n' in session):
            session = None
            raise ValueError('invalid session header')
        initialized = result(response, 1)
        if (initialized.get('protocolVersion') != PROTOCOL
                or not isinstance(initialized.get('capabilities'), dict)
                or not isinstance(initialized['capabilities'].get('tools'), dict)
                or not isinstance(initialized.get('serverInfo'), dict)
                or initialized['serverInfo'].get('name') != 'kubernetes'):
            raise ValueError('MCP initialization contract invalid')
        notification = rpc(ctx, config['url'], {
            'jsonrpc': '2.0', 'method': 'notifications/initialized'}, session)
        if notification.status not in (200, 202, 204):
            raise ValueError('initialization notification refused')
        catalog = result(rpc(ctx, config['url'], {
            'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}}, session), 2)
        tools = catalog.get('tools')
        if not isinstance(tools, list) or not tools or len(tools) > 256:
            raise ValueError('MCP tools missing')
        names = set()
        for tool in tools:
            if (not isinstance(tool, dict) or not isinstance(tool.get('name'), str)
                    or not tool['name'] or tool['name'] in names
                    or not isinstance(tool.get('inputSchema'), dict)
                    or tool['inputSchema'].get('type') != 'object'):
                raise ValueError('MCP tool schema invalid')
            names.add(tool['name'])
        if not set(config['required_tools']).issubset(names):
            raise ValueError('required MCP tools missing')
        service_result = result(rpc(ctx, config['url'], {
            'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {
                'name': 'kubectl_get', 'arguments': {
                    'resourceType': 'services', 'name': 'kubernetes',
                    'namespace': 'default', 'output': 'json'}}}, session), 3)
        content = service_result.get('content')
        if (service_result.get('isError') or not isinstance(content, list)
                or len(content) != 1 or not isinstance(content[0], dict)
                or content[0].get('type') != 'text'):
            raise ValueError('MCP read failed')
        service = json.loads(content[0].get('text', ''))
        if (not isinstance(service, dict) or service.get('apiVersion') != 'v1'
                or service.get('kind') != 'Service'
                or not isinstance(service.get('metadata'), dict)
                or service['metadata'].get('name') != 'kubernetes'
                or service['metadata'].get('namespace') != 'default'
                or not isinstance(service.get('spec'), dict)
                or not isinstance(service['spec'].get('ports'), list)
                or not any(isinstance(port, dict) and port.get('port') == 443
                           for port in service['spec']['ports'])):
            raise ValueError('fixed Kubernetes Service read invalid')
        good = True
        detail = f'MCP negotiated; {len(tools)} valid tools; fixed Kubernetes Service metadata read succeeded'
    except Exception:
        # Never expose remote errors, schemas, session IDs, URLs or exception text.
        pass
    finally:
        if session:
            try:
                cleanup = ctx.http(config['url'], method='DELETE', headers={
                    'Mcp-Session-Id': session, 'MCP-Protocol-Version': PROTOCOL},
                    timeout=3, max_bytes=4096)
                if cleanup.status not in (200, 202, 204, 405):
                    raise ValueError('session termination refused')
            except Exception:
                good = False
                detail = 'MCP session cleanup unavailable; inspect adapter locally'
    return [ctx.check('Baloo Kubernetes MCP read', not good, detail)]
