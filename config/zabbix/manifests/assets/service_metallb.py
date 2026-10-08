"""Expected MetalLB allocations, native announcements and representative VIP."""
from concurrent.futures import ThreadPoolExecutor
import json


def ready(pod):
    return not pod.get('metadata', {}).get('deletionTimestamp') and any(
        c.get('type') == 'Ready' and c.get('status') == 'True'
        for c in pod.get('status', {}).get('conditions', []))


def run(ctx, config):
    records = []
    expected = config['services']
    paths = ['/apis/metallb.io/v1beta1/namespaces/metallb-system/servicel2statuses',
             '/api/v1/pods'] + [f"/api/v1/namespaces/{s['namespace']}/services/{s['name']}" for s in expected]
    try:
        # All API calls use the foundation client's 15s timeout concurrently;
        # avoid accumulating ten sequential timeout windows within a 30s run.
        if ctx.remaining() < 16:
            raise TimeoutError()
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(ctx.kube.get, paths))
        announcements, pods = results[0]['items'], results[1]['items']
        live_speakers = {p['metadata']['uid']: p['spec'].get('nodeName') for p in pods
                         if p['metadata']['namespace'] == 'metallb-system' and ready(p)}
        for target, service in zip(expected, results[2:]):
            ns, name = target['namespace'], target['name']
            spec = service['spec']
            allocated = spec.get('type') == 'LoadBalancer' and target['ip'] in [
                i.get('ip') for i in service.get('status', {}).get('loadBalancer', {}).get('ingress', [])]
            nodes = set()
            lagging_status = False
            for announcement in announcements:
                status = announcement.get('status', {})
                if status.get('serviceNamespace') != ns or status.get('serviceName') != name:
                    continue
                node = announcement.get('metadata', {}).get('labels', {}).get('metallb.io/node')
                # v0.15.3 CreateOrPatch updates native metadata while status
                # can lag after failover. Require the label's live owner node.
                if node and any(live_speakers.get(o.get('uid')) == node
                                for o in announcement.get('metadata', {}).get('ownerReferences', [])
                                if o.get('kind') == 'Pod'):
                    nodes.add(node)
                    lagging_status |= status.get('node') != node
            local = True
            if spec.get('externalTrafficPolicy') == 'Local':
                selector = spec.get('selector', {})
                backend_nodes = {p['spec'].get('nodeName') for p in pods
                                 if p['metadata']['namespace'] == ns and selector and ready(p)
                                 and all(p['metadata'].get('labels', {}).get(k) == v for k, v in selector.items())}
                local = bool(nodes & backend_nodes)
            bad = not allocated or not nodes or not local
            detail = ('expected allocation missing' if not allocated else
                      'no live native L2 announcement' if not nodes else
                      'Local announcement lacks ready local backend' if not local else
                      'expected allocation and live L2 announcement present')
            if not bad and lagging_status:
                detail += '; status node lags native metadata'
            records.append(ctx.check(f'MetalLB VIP {ns}/{name}', bad, detail))
    except Exception:
        records.append(ctx.check('MetalLB allocation and announcement inventory', True,
                                 'native inventory unavailable or malformed'))
    try:
        response = ctx.http(config['probe_url'], timeout=min(5, ctx.remaining()), max_bytes=16384)
        body = json.loads(response.body)
        good = (response.status == 200 and isinstance(body, dict)
                and isinstance(body.get('Version'), str) and bool(body['Version'])
                and isinstance(body.get('Id'), str) and bool(body['Id']))
        records.append(ctx.check('MetalLB representative VIP semantic connection', not good,
                                 'public Emby server-info contract valid' if good else
                                 'VIP response failed server-info contract'))
    except Exception:
        records.append(ctx.check('MetalLB representative VIP semantic connection', True,
                                 'VIP semantic request unavailable'))
    return records
