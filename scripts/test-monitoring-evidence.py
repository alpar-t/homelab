#!/usr/bin/env python3
"""Offline canary regression for inherited snapshot evidence. Standard library only."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'config/zabbix/manifests/assets'))
spec = importlib.util.spec_from_file_location('evidence_collector', ROOT / 'config/zabbix/manifests/assets/collector.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
CANARY = 'PRIVATE-BEARER-SECRET-canary'
NOW = 1780000000


class SnapshotEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.data = {name: [] for name in collector.PATHS}
        self.policy = {'nodes': [], 'deployments': [], 'databases': [], 'probes': []}
    def checks(self):
        records = collector.evaluate(self.data, self.policy, NOW)
        self.assertNotIn(CANARY, json.dumps(records))
        return {record['name']:record for record in records}
    def test_pod_termination_and_waiting_payloads_do_not_enter_snapshot(self):
        pod = {'metadata':{'name':'app-1','namespace':'test','creationTimestamp':'2020-01-01T00:00:00Z'},
               'status':{'conditions':[{'type':'Ready','status':'False'}], 'containerStatuses':[
                   {'state':{'waiting':{'reason':'CrashLoopBackOff','message':CANARY}},'restartCount':2},
                   {'state':{'terminated':{'reason':'OOMKilled','exitCode':137,'message':'DSN='+CANARY}},'restartCount':1},
                   {'state':{'terminated':{'reason':CANARY,'exitCode':CANARY}},'restartCount':CANARY}]}}
        self.data['pods']=[pod]
        failed=self.checks()['Pod test/app-1']
        self.assertEqual(failed['status'],1)
        self.assertIn('CrashLoopBackOff',failed['detail']);self.assertIn('OOMKilled',failed['detail'])
        self.assertIn('exit_codes=137',failed['detail']);self.assertIn('restarts=3',failed['detail'])
        pod['status']['conditions'][0]['status']='True'
        recovered=self.checks()['Pod test/app-1']
        self.assertEqual(recovered['status'],0);self.assertEqual(failed['id'],recovered['id'])
    def test_cnpg_condition_payloads_are_redacted_without_changing_verdicts(self):
        self.policy['databases']=[['db','pg']]
        cluster={'metadata':{'name':'pg','namespace':'db'},'spec':{'instances':2},
                 'status':{'readyInstances':2,'conditions':[{'type':'Ready','status':'True'},
                     {'type':'ContinuousArchiving','status':'False','reason':CANARY,'message':CANARY},
                     {'type':'LastBackupSucceeded','status':'True','reason':CANARY,'message':CANARY}]}}
        self.data['clusters']=[cluster];checks=self.checks()
        self.assertEqual(checks['CNPG ContinuousArchiving db/pg']['status'],1)
        self.assertEqual(checks['CNPG LastBackupSucceeded db/pg']['status'],0)
        self.assertIn('status=False',checks['CNPG ContinuousArchiving db/pg']['detail'])
        cluster['status']['conditions'][1]['status']=CANARY
        self.assertIn('missing or invalid',self.checks()['CNPG ContinuousArchiving db/pg']['detail'])
    def test_storage_event_payload_is_private_and_quarantine_failure_stays_visible(self):
        self.policy['nodes']=['pufi']
        pod={'metadata':{'name':'health-1','uid':'health-uid','namespace':'node-config','creationTimestamp':'2020-01-01T00:00:00Z',
                         'labels':{'app.kubernetes.io/name':'node-storage-health'}}, 'spec':{'nodeName':'pufi'},
             'status':{'conditions':[{'type':'Ready','status':'False'}]}}
        self.data['pods']=[pod]
        self.data['events']=[{'involvedObject':{'uid':'health-uid'},'reason':'Unhealthy','message':'latched disk failure: '+CANARY,
                             'metadata':{'creationTimestamp':'2020-01-01T00:00:00Z'}}]
        check=self.checks()['Physical storage pufi'];self.assertEqual(check['status'],1)
        self.assertIn('Unhealthy storage readiness event',check['detail'])
        pod['status']['conditions'][0]['status']='True'
        self.assertEqual(self.checks()['Physical storage pufi']['status'],0)
    def test_longhorn_remote_conditions_do_not_enter_snapshot(self):
        target={'metadata':{'name':'default'},'status':{'available':False,'conditions':[
            {'type':'Unavailable','message':'URL?access_token='+CANARY,'reason':CANARY}]}}
        self.data['backup_targets']=[target]
        check=self.checks()['Longhorn backup target default'];self.assertEqual(check['status'],1)
        self.assertIn('unavailable',check['detail'])
        target['status']['available']=True
        self.assertEqual(self.checks()['Longhorn backup target default']['status'],0)


if __name__ == '__main__':
    unittest.main()
