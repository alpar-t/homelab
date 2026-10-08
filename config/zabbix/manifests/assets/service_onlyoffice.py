"""Read-only editor discovery and OpenCloud collaboration contracts."""
import json
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit


def run(ctx, config):
    def get(url, limit=262144):
        return ctx.http(url, timeout=min(5, ctx.remaining()), max_bytes=limit)

    checks = []
    try:
        response = get(config['editor'] + '/healthcheck', 1024)
        healthy = response.status == 200 and response.body.strip() == b'true'
        checks.append(ctx.check('Document server dependencies', not healthy,
                                'Native dependency health is true' if healthy else 'Native dependency health failed'))
    except Exception:
        checks.append(ctx.check('Document server dependencies', True, 'Dependency health request unavailable'))
    try:
        response = get(config['editor'] + '/hosting/discovery')
        if response.status != 200 or b'<!DOCTYPE' in response.body.upper() or b'<!ENTITY' in response.body.upper():
            raise ValueError()
        root = ET.fromstring(response.body)
        actions = root.findall('./net-zone/app/action')
        supported = set()
        for action in actions:
            target = urlsplit(action.get('urlsrc', ''))
            if (action.get('name') == 'edit' and target.scheme in ('http', 'https')
                    and target.hostname in config['editor_hosts']
                    and target.path.startswith('/hosting/wopi/')):
                supported.add(action.get('ext'))
        if root.tag != 'wopi-discovery' or not set(config['extensions']) <= supported:
            raise ValueError()
        response = get(config['editor'] + '/hosting/capabilities', 16384)
        capabilities = json.loads(response.body)
        if (response.status != 200 or not isinstance(capabilities, dict)
                or not isinstance(capabilities.get('productVersion'), str)
                or not capabilities['productVersion'].strip()
                or not isinstance(capabilities.get('hasMobileSupport'), bool)
                or not isinstance(capabilities.get('convert-to'), dict)
                or capabilities['convert-to'].get('available') is not True
                or capabilities['convert-to'].get('endpoint') != '/lool/convert-to'):
            raise ValueError()
        checks.append(ctx.check('Editor WOPI capabilities', False, 'Office edit actions and conversion capability advertised'))
    except Exception:
        checks.append(ctx.check('Editor WOPI capabilities', True, 'Editor discovery or capabilities unavailable or invalid'))
    try:
        response = get(config['registry'] + '/app/list')
        registry = json.loads(response.body)
        if response.status != 200 or not isinstance(registry, dict) or not isinstance(registry.get('mime-types'), list):
            raise ValueError()
        registered = set()
        for entry in registry['mime-types']:
            if not isinstance(entry, dict) or not isinstance(entry.get('app_providers'), list):
                raise ValueError()
            if any(isinstance(p, dict) and p.get('product_name') == 'OnlyOffice'
                   and p.get('address') == 'eu.opencloud.api.collaboration'
                   for p in entry['app_providers']):
                registered.add(entry.get('ext'))
        if not set(config['extensions']) <= registered:
            raise ValueError()
        # Deliberately nonexistent ID and no access token: never touches user files.
        response = get(config['collaboration'] + '/wopi/files/monitoring-nonexistent', 1024)
        if response.status != 401 or response.body.strip() != b'Unauthorized':
            raise ValueError()
        checks.append(ctx.check('OpenCloud collaboration contract', False, 'Office formats registered and WOPI rejects unauthenticated metadata'))
    except Exception:
        checks.append(ctx.check('OpenCloud collaboration contract', True, 'Collaboration registration or WOPI authentication contract failed'))
    return checks
