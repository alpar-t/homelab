"""Passive travel ingress contract; never read keys or send unauthenticated UDP."""


def run(ctx, config):
    base = '/api/v1/namespaces/wireguard/services/wireguard-home'
    try:
        service = ctx.kube.get(base)
        if ctx.remaining() < 6:
            raise TimeoutError()
        slices = ctx.kube.get('/apis/discovery.k8s.io/v1/namespaces/wireguard/'
                              'endpointslices?labelSelector=kubernetes.io%2Fservice-name%3Dwireguard-home&limit=100')
        spec = service['spec']
        ports = spec.get('ports', [])
        contract = (spec.get('type') == 'LoadBalancer'
                    and spec.get('externalTrafficPolicy') == 'Local'
                    and spec.get('selector') == {'app': 'wireguard-home'}
                    and len(ports) == 1
                    and ports[0].get('protocol') == 'UDP'
                    and ports[0].get('port') == 41641
                    and ports[0].get('targetPort') == 'wireguard'
                    and any(x.get('ip') == config['vip'] for x in
                            service.get('status', {}).get('loadBalancer', {}).get('ingress', [])))
        endpoints = []
        complete = not slices.get('metadata', {}).get('continue')
        for item in slices['items']:
            valid_port = any(p.get('name') == 'wireguard' and p.get('protocol') == 'UDP'
                             and p.get('port') == 41641 for p in item.get('ports', []))
            for endpoint in item.get('endpoints', []):
                conditions = endpoint.get('conditions', {})
                if conditions.get('ready') is True and not conditions.get('terminating', False):
                    ref = endpoint.get('targetRef', {})
                    endpoints.append(valid_port and bool(endpoint.get('addresses'))
                                     and bool(endpoint.get('nodeName'))
                                     and ref.get('kind') == 'Pod'
                                     and ref.get('namespace') == 'wireguard')
        topology = complete and len(endpoints) == 1 and all(endpoints)
        return [ctx.check('WireGuard travel ingress contract', not contract,
                          'UDP service, Local policy and reserved VIP valid' if contract else
                          'UDP service mapping, Local policy or reserved VIP differs'),
                ctx.check('WireGuard travel endpoint routing', not topology,
                          'one ready UDP endpoint with pod/node routing metadata' if topology else
                          'expected one ready UDP endpoint with correct target port and node')]
    except Exception:
        return [ctx.check('WireGuard travel ingress contract', True,
                          'service or endpoint metadata unavailable or malformed'),
                ctx.check('WireGuard travel endpoint routing', True,
                          'service or endpoint metadata unavailable or malformed')]
