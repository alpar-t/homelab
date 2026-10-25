"""Behavioral checks for short-lived Pod image discovery and restart recovery."""
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[2] / 'config/zabbix/manifests/assets/security_scanner.py'
SPEC = importlib.util.spec_from_file_location('security_scanner', SOURCE)
scanner_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scanner_module)

DEPLOY_IMAGE = 'docker.io/example/service@sha256:' + 'a' * 64
JOB_IMAGE = 'docker.io/example/runner@sha256:' + 'b' * 64


def pod(name, uid, phase, image, owner=None, finished=None):
    state = {'running': {'startedAt': '2027-01-01T00:00:00Z'}}
    if finished is not None:
        state = {'terminated': {'finishedAt': datetime.fromtimestamp(
            finished, tz=timezone.utc).isoformat().replace('+00:00', 'Z')}}
    metadata = {'name': name, 'namespace': 'testing', 'uid': uid,
                'resourceVersion': str(int(uid[-1], 16) + 10)}
    if owner:
        metadata['ownerReferences'] = [{'kind': owner[0], 'name': owner[1],
                                        'uid': owner[2] if len(owner) > 2 else owner[1],
                                        'controller': True}]
    return {'metadata': metadata, 'status': {'phase': phase,
            'containerStatuses': [{'name': 'main', 'imageID': image, 'state': state}]}}


class FakeKubernetes:
    def __init__(self, pods):
        self.pods = pods

    def inventory(self):
        return self.pods, {}, {}, {}, '10'


class PodWatchTest(unittest.TestCase):
    def setUp(self):
        self.clock = 1_800_000_000.0
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state_path = Path(self.directory.name) / 'state.json'
        self.deployment = pod('service', 'pod-a', 'Running', DEPLOY_IMAGE,
                              ('ReplicaSet', 'service-rs'))
        self.kube = FakeKubernetes([self.deployment])
        self.scanned = []
        self.scanner = scanner_module.Scanner(
            kube=self.kube, scan=lambda ref: self.scanned.append(ref) or [],
            state_path=self.state_path, now=lambda: self.clock)
        self.scanner.refresh_inventory()

    def test_short_job_between_lists_is_scanned_and_retained_then_expires(self):
        job = pod('short-job', 'pod-b', 'Running', JOB_IMAGE, ('Job', 'short-job'))
        self.scanner.apply_watch_event({'type': 'ADDED', 'object': job})
        job['status']['phase'] = 'Succeeded'
        job['status']['containerStatuses'][0]['state'] = {
            'terminated': {'finishedAt': datetime.fromtimestamp(
                self.clock + 10, tz=timezone.utc).isoformat().replace('+00:00', 'Z')}}
        job['metadata']['resourceVersion'] = '12'
        self.clock += 10
        self.scanner.apply_watch_event({'type': 'MODIFIED', 'object': job})
        job['metadata']['resourceVersion'] = '13'
        self.scanner.apply_watch_event({'type': 'DELETED', 'object': job})

        snapshot = self.scanner.snapshot()
        self.assertNotIn(JOB_IMAGE, snapshot['images'])
        self.assertEqual(snapshot['recent_images'][JOB_IMAGE]['testing/Job/short-job/main'],
                         self.clock)
        while self.scanner.scan_due():
            pass
        self.assertIn(JOB_IMAGE, self.scanned)

        self.clock += scanner_module.RECENT_EXPOSURE_SECONDS - 1
        self.scanner.refresh_inventory()
        self.assertIn(JOB_IMAGE, self.scanner.snapshot()['recent_images'])
        self.clock += 2
        self.scanner.refresh_inventory()
        self.assertNotIn(JOB_IMAGE, self.scanner.snapshot()['recent_images'])
        self.assertNotIn(JOB_IMAGE, self.scanner.snapshot()['reports'])
        self.assertNotIn(JOB_IMAGE, self.scanner.snapshot()['first_seen'])

    def test_deployment_image_deleted_before_next_list_is_still_scanned(self):
        rolling = pod('rollout', 'pod-d', 'Running', JOB_IMAGE,
                      ('ReplicaSet', 'rollout-rs', 'rs-old'))
        self.scanner.apply_watch_event({'type': 'ADDED', 'object': rolling})
        old_fingerprint = self.scanner.snapshot()['consumer_fingerprints'][JOB_IMAGE][
            'testing/ReplicaSet/rollout-rs/main']
        rolling['metadata']['resourceVersion'] = '22'
        self.scanner.apply_watch_event({'type': 'DELETED', 'object': rolling})
        snapshot = self.scanner.snapshot()
        self.assertNotIn(JOB_IMAGE, snapshot['images'])
        self.assertIn('testing/ReplicaSet/rollout-rs/main', snapshot['recent_images'][JOB_IMAGE])
        self.assertEqual(snapshot['consumer_fingerprints'][JOB_IMAGE][
            'testing/ReplicaSet/rollout-rs/main'], old_fingerprint)
        while self.scanner.scan_due():
            pass
        self.assertIn(JOB_IMAGE, self.scanned)

    def test_recent_job_survives_restart_without_pod_in_api(self):
        job = pod('job', 'pod-c', 'Succeeded', JOB_IMAGE, ('Job', 'job'), self.clock - 60)
        self.scanner.apply_watch_event({'type': 'ADDED', 'object': job})
        self.scanner.apply_watch_event({'type': 'DELETED', 'object': job})
        restarted = scanner_module.Scanner(kube=self.kube, scan=lambda ref: [],
                                            state_path=self.state_path, now=lambda: self.clock)
        restarted.refresh_inventory()
        self.assertIn(JOB_IMAGE, restarted.snapshot()['recent_images'])
        self.assertLess(restarted.snapshot()['first_seen'][JOB_IMAGE], self.clock + 1)

    def test_same_digest_template_change_updates_service_fingerprint(self):
        first = pod('first', 'pod-d', 'Running', JOB_IMAGE,
                    ('ReplicaSet', 'service-rs', 'rs-old'))
        self.scanner.apply_watch_event({'type': 'ADDED', 'object': first})
        identity = 'testing/ReplicaSet/service-rs/main'
        old = self.scanner.snapshot()['consumer_fingerprints'][JOB_IMAGE][identity]
        second = pod('second', 'pod-e', 'Running', JOB_IMAGE,
                     ('ReplicaSet', 'service-rs', 'rs-new'))
        self.scanner.apply_watch_event({'type': 'ADDED', 'object': second})
        self.assertNotEqual(self.scanner.snapshot()['consumer_fingerprints'][JOB_IMAGE][identity], old)

    def test_unchanged_cronjob_runs_share_fingerprint_until_generation_changes(self):
        jobs = {
            ('testing', 'nightly-1'): {'metadata': {'ownerReferences': [
                {'kind': 'CronJob', 'name': 'nightly', 'uid': 'cron-uid', 'controller': True}]}},
            ('testing', 'nightly-2'): {'metadata': {'ownerReferences': [
                {'kind': 'CronJob', 'name': 'nightly', 'uid': 'cron-uid', 'controller': True}]}}
        }
        cronjobs = {('testing', 'nightly'): {'metadata': {'generation': 3}}}
        first = pod('run-1', 'pod-d', 'Running', JOB_IMAGE,
                    ('Job', 'nightly-1', 'job-uid-1'))
        second = pod('run-2', 'pod-e', 'Running', JOB_IMAGE,
                     ('Job', 'nightly-2', 'job-uid-2'))
        identity = 'testing/CronJob/nightly/main'
        a = scanner_module.consumer_fingerprints((first,), {}, jobs, cronjobs)[JOB_IMAGE][identity]
        b = scanner_module.consumer_fingerprints((second,), {}, jobs, cronjobs)[JOB_IMAGE][identity]
        self.assertEqual(a, b)
        cronjobs[('testing', 'nightly')]['metadata']['generation'] = 4
        changed = scanner_module.consumer_fingerprints((second,), {}, jobs, cronjobs)[JOB_IMAGE][identity]
        self.assertNotEqual(a, changed)

    def test_expired_watch_version_requires_relist(self):
        with self.assertRaises(scanner_module.WatchExpired):
            self.scanner.apply_watch_event({'type': 'ERROR', 'object': {'code': 410}})
        self.scanner.apply_watch_event({'type': 'BOOKMARK',
                                        'object': {'metadata': {'resourceVersion': '18'}}})
        self.assertEqual(self.scanner.resource_version, '18')

    def test_old_cache_state_is_atomically_seeded_to_replicated_state(self):
        old = Path(self.directory.name) / 'cache-state.json'
        new = Path(self.directory.name) / 'replicated' / 'state.json'
        self.scanner.scan_due()
        old.write_text(json.dumps(self.scanner.state))
        migrated = scanner_module.Scanner(kube=self.kube, scan=lambda ref: [],
                                           state_path=new, now=lambda: self.clock,
                                           legacy_state_path=old)
        self.assertTrue(new.exists())
        self.assertEqual(migrated.snapshot()['reports'], self.scanner.snapshot()['reports'])
        self.assertEqual(migrated.snapshot()['images'], self.scanner.snapshot()['images'])
        old.unlink()
        again = scanner_module.Scanner(kube=self.kube, scan=lambda ref: [],
                                        state_path=new, now=lambda: self.clock,
                                        legacy_state_path=old)
        self.assertEqual(again.snapshot()['images'], self.scanner.snapshot()['images'])


if __name__ == '__main__':
    unittest.main()
