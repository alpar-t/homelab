import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('metallb', ROOT / 'config/zabbix/manifests/assets/service_metallb.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class Tests(unittest.TestCase):
    def setUp(self):
        self.config = {'services': [{'namespace':'media','name':'emby','ip':'192.168.1.204'}], 'probe_url':'http://example'}
        self.pods = [{'metadata':{'namespace':'metallb-system','uid':'speaker'}, 'spec':{'nodeName':'buksi'}, 'status':{'conditions':[{'type':'Ready','status':'True'}]}}, {'metadata':{'namespace':'media','uid':'backend','labels':{'app':'emby'}}, 'spec':{'nodeName':'buksi'}, 'status':{'conditions':[{'type':'Ready','status':'True'}]}}]
        self.announcement = {'metadata':{'labels':{'metallb.io/node':'buksi'},'ownerReferences':[{'kind':'Pod','uid':'speaker'}]}, 'status':{'node':'buksi','serviceNamespace':'media','serviceName':'emby'}}
        self.service = {'spec':{'type':'LoadBalancer','externalTrafficPolicy':'Local','selector':{'app':'emby'}}, 'status':{'loadBalancer':{'ingress':[{'ip':'192.168.1.204'}]}}}
        self.response = SimpleNamespace(status=200, body=b'{"Id":"fixed","Version":"4.9","LocalAddress":"http://host"}')
        def get(path):
            path = path.split('?')[0]
            if path.endswith('servicel2statuses'): return {'items':[self.announcement]}
            if path.endswith('/pods'): return {'items':self.pods}
            return self.service
        self.ctx = SimpleNamespace(kube=SimpleNamespace(get=get), remaining=lambda:30, http=lambda *a,**kw:self.response, check=lambda n,b,d,severity=3:dict(name=n,status=int(b),detail=d,severity=severity))
    def run_check(self): return module.run(self.ctx,self.config)
    def test_twelve_api_reads_have_three_workers_and_join_before_return(self):
        import threading
        import time
        original = self.ctx.kube.get
        lock = threading.Lock()
        active = peak = 0
        calls, workers = [], set()
        self.config['services'] *= 10
        def get(path):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                calls.append(path)
                workers.add(threading.current_thread())
            try:
                time.sleep(.002)
                return original(path)
            finally:
                with lock: active -= 1
        self.ctx.kube.get = get
        self.run_check()
        self.assertEqual(len(calls), 12)
        self.assertLessEqual(peak, 3)
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertTrue(any(path.endswith('?limit=100') for path in calls))
        self.assertTrue(any(path.endswith('?limit=500') for path in calls))

    def test_incomplete_list_never_claims_complete_inventory(self):
        original = self.ctx.kube.get
        def get(path):
            result = original(path)
            if path.startswith('/api/v1/pods'):
                return {**result, 'metadata': {'continue': 'more'}}
            return result
        self.ctx.kube.get = get
        self.assertEqual(self.run_check()[0]['status'], 1)

    def test_healthy(self): self.assertEqual([r['status'] for r in self.run_check()], [0,0])
    def test_lagging_status_after_failover(self):
        self.announcement['status']['node'] = 'pamacs'
        rows = self.run_check()
        self.assertEqual(rows[0]['status'], 0)
        self.assertIn('lags', rows[0]['detail'])
    def test_wrong_allocation(self):
        self.service['status']['loadBalancer']['ingress']=[]
        self.assertEqual(self.run_check()[0]['status'],1)
    def test_stale_speaker_owner(self):
        self.announcement['metadata']['ownerReferences'][0]['uid']='old'
        self.assertEqual(self.run_check()[0]['status'],1)
    def test_local_policy_wrong_node(self):
        self.pods[1]['spec']['nodeName']='pufi'
        self.assertEqual(self.run_check()[0]['status'],1)
        self.service['spec']['externalTrafficPolicy']='Cluster'
        self.assertEqual(self.run_check()[0]['status'],0)
    def test_unauthorized_malformed_and_timeout(self):
        for response in [SimpleNamespace(status=401,body=b'{}'), SimpleNamespace(status=200,body=b'<html>'),SimpleNamespace(status=200,body=b'{}')]:
            self.response=response
            self.assertEqual(self.run_check()[1]['status'],1)
        def fail(*a,**kw): raise TimeoutError('private information')
        self.ctx.http=fail
        self.ctx.kube.get=fail
        rows=self.run_check()
        self.assertTrue(all(r['status']==1 for r in rows))
        self.assertNotIn('private information',str(rows))
    def test_restored_connection(self):
        healthy = self.response
        self.response = SimpleNamespace(status=503, body=b'{}')
        self.assertEqual(self.run_check()[1]['status'], 1)
        self.response = healthy
        self.assertEqual(self.run_check()[1]['status'], 0)
    def test_insufficient_deadline(self):
        self.ctx.remaining=lambda:2
        self.assertEqual(self.run_check()[0]['status'],1)
    def test_unconfigured_pending_service_ignored(self):
        self.assertEqual(len(self.run_check()),2)
        self.assertEqual(self.run_check()[0]['status'],0)

if __name__ == '__main__': unittest.main()
