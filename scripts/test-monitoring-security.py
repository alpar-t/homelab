#!/usr/bin/env python3
"""Offline monitoring boundary regression. Requires kubectl and the existing PyYAML environment.

Usage: python3 scripts/test-monitoring-security.py --root /path/to/integrated/tree --expected-services 49 --self-test --output /tmp/security-result.json
No API requests, secret reads, writes to the checkout, or production probes occur.
The source redaction/cache migration does not purge historical Zabbix database evidence.
"""
import argparse
import ast
import copy
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import tempfile
import urllib.parse
import yaml

APPROVED = {'immich-api-key', 'vikunja_read_token', 'tandoor_read_token', 'stalwart_mail_ca'}
READ_VERBS = {'get', 'list', 'watch'}
FORBIDDEN = {'secrets', 'configmaps', 'pods/exec', 'pods/attach', 'pods/portforward', 'pods/proxy', 'nodes/proxy', 'services/proxy', '*'}
UNSAFE_SERVICES = {'actual_budget','opencloud','homeassistant','sonarr','radarr','prowlarr','pinchtab','product_models','emby','paperless','nodered'}


def require(condition, issue):
    if not condition:
        raise AssertionError(issue)


def render(root):
    # Compose the real collector Kustomization and every source NetworkPolicy.
    # Including policies outside the four original files catches additive grants.
    resources = [str(root / 'config/zabbix/manifests')]
    for path in sorted((root / 'config').glob('*/manifests/*.yaml')):
        if '/config/zabbix/' not in str(path) and 'kind: NetworkPolicy' in path.read_text():
            resources.append(str(path))
    with tempfile.TemporaryDirectory(prefix='monitoring-security-render-') as tmp:
        Path(tmp, 'kustomization.yaml').write_text(yaml.safe_dump({'apiVersion':'kustomize.config.k8s.io/v1beta1','kind':'Kustomization','resources':[os.path.relpath(resource,str(Path(tmp).resolve())) for resource in resources]}))
        data = subprocess.check_output(['kubectl','kustomize','--load-restrictor=LoadRestrictionsNone',str(Path(tmp).resolve())], text=True)
    return [r for r in yaml.safe_load_all(data) if r]


def selector_matches(selector, labels):
    if selector is None:
        return True
    require(not (set(selector) - {'matchLabels','matchExpressions'}), 'unreviewed selector field')
    if any(labels.get(k) != v for k,v in selector.get('matchLabels',{}).items()):
        return False
    for expression in selector.get('matchExpressions',[]):
        key, op, values = expression['key'], expression['operator'], expression.get('values',[])
        if op == 'In' and labels.get(key) not in values: return False
        if op == 'NotIn' and labels.get(key) in values: return False
        if op == 'Exists' and key not in labels: return False
        if op == 'DoesNotExist' and key in labels: return False
        require(op in {'In','NotIn','Exists','DoesNotExist'}, 'unreviewed selector operation')
    return True


def peer_matches(peer, policy_namespace, namespace, labels, address):
    if 'ipBlock' in peer:
        block = peer['ipBlock']
        ip = ipaddress.ip_address(address)
        return ip in ipaddress.ip_network(block['cidr']) and not any(ip in ipaddress.ip_network(n) for n in block.get('except',[]))
    if 'namespaceSelector' in peer:
        if not selector_matches(peer['namespaceSelector'], {'kubernetes.io/metadata.name':namespace}):return False
    elif namespace != policy_namespace:
        return False
    return selector_matches(peer.get('podSelector'),labels)


def permitted(resources, direction, namespace, labels, peer_namespace, peer_labels, port, protocol='TCP', address='192.0.2.1'):
    policies = [r for r in resources if r.get('kind') == 'NetworkPolicy' and r['metadata'].get('namespace','default') == namespace
                and direction in r['spec'].get('policyTypes',['Ingress'] + (['Egress'] if 'egress' in r['spec'] else []))
                and selector_matches(r['spec'].get('podSelector',{}),labels)]
    if not policies:
        return True # Kubernetes default permit when no policy selects the pod/direction.
    for policy in policies:
        for rule in policy['spec'].get(direction.lower(),[]):
            ports = rule.get('ports')
            if ports and not any(p.get('protocol','TCP') == protocol and (p.get('port') is None or
                 isinstance(p['port'],int) and p['port'] <= port <= p.get('endPort',p['port'])) for p in ports):continue
            peers = rule.get('to' if direction == 'Egress' else 'from')
            if not peers or any(peer_matches(p,namespace,peer_namespace,peer_labels,address) for p in peers):return True
    return False


def resource(resources, kind, name, namespace='zabbix'):
    found = [r for r in resources if r.get('kind') == kind and r['metadata']['name'] == name
             and (kind == 'ClusterRole' or r['metadata'].get('namespace','default') == namespace)]
    require(len(found)==1, 'missing/ambiguous '+kind+' '+name)
    return found[0]


def audit(resources, expected_services):
    collector = resource(resources,'Deployment','collector')['spec']['template']['spec']
    projected = [v['secret'] for v in collector['volumes'] if v.get('secret',{}).get('secretName') == 'zabbix-functional-credentials']
    require(len(projected)==1,'functional Secret projection must be unique')
    require(projected[0].get('optional') is True,'missing functional Secret must not prevent startup')
    require({v['key'] for v in projected[0].get('items',[])} == APPROVED,'unsafe/missing credential projection key')
    require(all(v['path']==v['key'] for v in projected[0]['items']),'unexpected credential projection path')
    volume_name = next(v['name'] for v in collector['volumes'] if v.get('secret',{}).get('secretName') == 'zabbix-functional-credentials')
    for container in collector.get('containers',[]) + collector.get('initContainers',[]):
        for mount in container.get('volumeMounts',[]):
            if mount['name']==volume_name:require(mount.get('readOnly') is True,'credential mount must be read-only')
        for entry in container.get('envFrom',[]):
            require(entry.get('secretRef',{}).get('name') != 'zabbix-functional-credentials','envFrom bypasses credential projection')
        for entry in container.get('env',[]):
            require(entry.get('valueFrom',{}).get('secretKeyRef',{}).get('name') != 'zabbix-functional-credentials','env bypasses credential projection')
    zabbix = resource(resources,'Deployment','zabbix')['spec']['template']['spec']
    require(zabbix.get('automountServiceAccountToken') is False,'Zabbix must not receive Kubernetes bearer authority')
    require(not any(v.get('secret',{}).get('secretName')=='zabbix-functional-credentials' for v in zabbix.get('volumes',[])), 'Zabbix must not mount collector application credentials')
    # Resolve all bindings to collector, including added namespace telemetry grants.
    bindings = [r for r in resources if r.get('kind') in ('RoleBinding','ClusterRoleBinding') and any(
        s.get('kind')=='ServiceAccount' and s.get('name')=='collector' and s.get('namespace',r['metadata'].get('namespace'))=='zabbix'
        for s in r.get('subjects',[]))]
    require(bindings,'collector RBAC bindings must be present')
    for binding in bindings:
        reference = binding['roleRef']
        role = resource(resources, reference['kind'], reference['name'], binding['metadata'].get('namespace','default'))
        for rule in role.get('rules',[]):
            require(set(rule.get('verbs',[])) <= READ_VERBS,'collector RBAC includes a mutation verb')
            require(not rule.get('nonResourceURLs'),'collector non-resource RBAC requires separate review')
            for item in rule.get('resources',[]):
                require(item not in FORBIDDEN and not item.endswith('/proxy'),'collector RBAC exposes credentials/command-capable subresource')
                require(item in {'nodes','pods','deployments','daemonsets','volumes','replicas','backups','backuptargets','clusters','scheduledbackups','events','pods/log','applications','services','endpointslices','servicel2statuses','backupstoragelocations','schedules','autoscalingrunnersets','ephemeralrunnersets','ephemeralrunners','autoscalinglisteners'},'unreviewed collector RBAC resource')
                if item=='pods/log':require(binding['metadata'].get('namespace') in {'stalwart-mail','otmonitor'} and set(rule['verbs']) == {'get'},'collector log read grant widened')
    allowed=[('kube-system',{'k8s-app':'kube-dns'},53,'UDP'),('kube-system',{'k8s-app':'kube-dns'},53,'TCP'),('zabbix',{'app':'collector'},8080,'TCP'),('zabbix',{'cnpg.io/cluster':'zabbix-db'},5432,'TCP'),('baloo',{'app.kubernetes.io/name':'openclaw'},18789,'TCP')]
    denied=[('default',{'app':'collector'},8080),('baloo',{'app':'collector'},8080),('zabbix',{'app':'collector'},80),('zabbix',{'cnpg.io/cluster':'other'},5432),('media',{'app.kubernetes.io/name':'arr-stack'},8080),('nodered',{'app':'nodered'},1880),('frigate',{'app':'frigate'},5000),('baloo',{'app.kubernetes.io/name':'openclaw'},18801),('baloo',{'app.kubernetes.io/name':'pinchtab'},9867),('baloo',{'app.kubernetes.io/name':'product-model-renderer'},18811),('default',{},443),('kube-system',{'k8s-app':'kube-dns'},443),('pocket-id',{'app':'pocket-id'},80),('outside',{},443),('outside',{},80)]
    for ns,l,p,proto in allowed:require(permitted(resources,'Egress','zabbix',{'app':'zabbix'},ns,l,p,proto),'required Zabbix egress denied')
    for ns,l,p in denied:require(not permitted(resources,'Egress','zabbix',{'app':'zabbix'},ns,l,p),'unsafe Zabbix egress allowed')
    egress = resource(resources,'NetworkPolicy','zabbix-server-egress')['spec']
    require(egress['podSelector']=={'matchLabels':{'app':'zabbix'}} and len(egress.get('egress',[]))==4,'server policy scope changed')
    expected_rules = [
        {'to':[{'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':'kube-system'}},'podSelector':{'matchLabels':{'k8s-app':'kube-dns'}}}], 'ports':[{'port':53,'protocol':'UDP'},{'port':53,'protocol':'TCP'}]},
        {'to':[{'podSelector':{'matchLabels':{'app':'collector'}}}], 'ports':[{'port':8080,'protocol':'TCP'}]},
        {'to':[{'podSelector':{'matchLabels':{'cnpg.io/cluster':'zabbix-db'}}}], 'ports':[{'port':5432,'protocol':'TCP'}]},
        {'to':[{'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':'baloo'}},'podSelector':{'matchLabels':{'app.kubernetes.io/name':'openclaw'}}}], 'ports':[{'port':18789,'protocol':'TCP'}]},
    ]
    require(egress['egress']==expected_rules, 'server egress destination/port allowlist broadened')
    private=[('pinchtab',9867,'openclaw'),('pinchtab-web',9867,'openclaw'),('product-model-renderer',18811,'product-model-api'),('product-model-api',18810,'openclaw')]
    for target,port,owner in private:
        labels={'app.kubernetes.io/name':target}
        require(not permitted(resources,'Ingress','baloo',labels,'zabbix',{'app':'collector'},port),'collector gained private browser/renderer/worker ingress')
        require(permitted(resources,'Ingress','baloo',labels,'baloo',{'app.kubernetes.io/name':owner},port),'existing trusted application caller blocked')
    cm=resource(resources,'ConfigMap','collector')['data'];configs={name:json.loads(body) for name,body in cm.items() if name.startswith('service_') and name.endswith('.json')}
    require(len(configs)==expected_services,'rendered service count differs from expected integration snapshot')
    for filename,config in configs.items():
        slug=filename[len('service_'):-len('.json')];src=cm.get('service_'+slug+'.py');require(src is not None,'service module missing from rendered ConfigMap')
        tree=ast.parse(src)
        secret_calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='secret']
        if slug in UNSAFE_SERVICES:require(not secret_calls,'unsafe service credential read returned')
        require(slug in {'immich','vikunja','tandoor','stalwart_mail'} or not secret_calls,'unreviewed service credential use')
        for key,value in config.items():
            if key in {'credential_key','token_key','session_secret','user_id_key'}:require(value in APPROVED,'unapproved configured credential')
        def walk(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if key=='ca_key':require(item=='stalwart_mail_ca','unapproved TLS credential key')
                    walk(item)
            elif isinstance(value,list):
                for item in value:walk(item)
            elif isinstance(value,str) and value.startswith(('http://','https://')):
                parsed=urllib.parse.urlsplit(value);require(not parsed.username and not parsed.password,'credential-bearing URL')
                require(not any(k.lower() in {'token','apikey','api_key','password','secret','access_token'} for k,v in urllib.parse.parse_qsl(parsed.query)),'credential-bearing query')
        walk(config)
    return dict(rendered_services=len(configs),collector_readonly_bindings=len(bindings),projected_keys=sorted(APPROVED),egress_allow_cases=len(allowed),egress_deny_cases=len(denied),private_ingress_deny_cases=len(private))


def self_test(resources, expected):
    mutations=[]
    def project(rs):
        d=resource(rs,'Deployment','collector')['spec']['template']['spec'];next(v['secret'] for v in d['volumes'] if v.get('secret',{}).get('secretName')=='zabbix-functional-credentials')['items'].append({'key':'pinchtab_olx_token','path':'pinchtab_olx_token'})
    mutations.append(('write-capable Secret projection',project))
    mutations.append(('RBAC mutation verb',lambda rs:resource(rs,'ClusterRole','zabbix-collector-readonly')['rules'][0]['verbs'].append('patch')))
    mutations.append(('Secret API read',lambda rs:resource(rs,'ClusterRole','zabbix-collector-readonly')['rules'].append({'apiGroups':[''],'resources':['secrets'],'verbs':['get']})))
    mutations.append(('pod exec API read',lambda rs:resource(rs,'ClusterRole','zabbix-collector-readonly')['rules'].append({'apiGroups':[''],'resources':['pods/exec'],'verbs':['get']})))
    mutations.append(('server broad egress',lambda rs:resource(rs,'NetworkPolicy','zabbix-server-egress')['spec']['egress'].append({})))
    def add_grant(rs):rs.append({'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':'bad-extra-grant','namespace':'baloo'},'spec':{'podSelector':{'matchLabels':{'app.kubernetes.io/name':'product-model-renderer'}},'policyTypes':['Ingress'],'ingress':[{'from':[{'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':'zabbix'}}}],'ports':[{'port':18811,'protocol':'TCP'}]}]}})
    mutations.append(('additive renderer ingress',add_grant))
    for name,mutate in mutations:
        altered=copy.deepcopy(resources);mutate(altered)
        try:audit(altered,expected)
        except AssertionError:continue
        raise AssertionError('regression did not detect '+name)
    return len(mutations)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--expected-services',type=int);p.add_argument('--self-test',action='store_true');p.add_argument('--output',type=Path);a=p.parse_args()
    root=a.root.resolve()
    if a.expected_services is None:
        generators=yaml.safe_load((root/'config/zabbix/manifests/kustomization.yaml').read_text()).get('configMapGenerator',[])
        a.expected_services=sum(Path(f).name.startswith('service_') and f.endswith('.json') for g in generators if g['name']=='collector' for f in g.get('files',[]))
    resources=render(root);result=audit(resources,a.expected_services)
    if a.self_test:result['negative_mutation_tests']=self_test(resources,a.expected_services)
    result['mode']='combined-all49' if a.expected_services==49 else 'foundation-or-partial-service';result['root']=str(a.root.resolve())
    if a.output:a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
