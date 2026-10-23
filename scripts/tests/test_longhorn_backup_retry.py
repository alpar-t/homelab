import datetime as dt
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest import mock
import urllib.error


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'config/longhorn/backup_retry.py'
spec = importlib.util.spec_from_file_location('backup_retry', SOURCE)
retry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retry)


def iso(seconds):
    return dt.datetime.fromtimestamp(seconds, dt.timezone.utc).isoformat().replace('+00:00', 'Z')


class FakeKubernetes:
    def __init__(self, job, volumes, backups=None, snapshots=None):
        self.data = {
            retry.JOBS: {'items': [job]},
            retry.API + '/volumes': {'items': volumes},
            retry.API + '/backups': {'items': backups or []},
            retry.API + '/snapshots': {'items': snapshots or []},
        }
        self.created = []

    def request(self, path, body=None):
        if body is None:
            return self.data[path]
        self.created.append((path, body))
        return body


def job(name='weekly-backup', start=1000, end=2000):
    return {'metadata': {'name': name + '-run',
                         'ownerReferences': [{'kind': 'CronJob', 'name': name}]},
            'status': {'startTime': iso(start), 'completionTime': iso(end)}}


def volume(name='vol-1', group='default', state='attached', robustness='healthy'):
    return {'metadata': {'name': name,
                         'labels': {'recurring-job-group.longhorn.io/' + group: 'enabled'}},
            'status': {'state': state, 'robustness': robustness}}


def snapshot(name, vol='vol-1', ready=True, created=3100, error=None):
    return {'metadata': {'name': name, 'creationTimestamp': iso(created),
                         'labels': {retry.RETRY_LABEL: 'weekly-backup-run'}},
            'spec': {'volume': vol}, 'status': {'readyToUse': ready, 'error': error}}


def backup(name, state, created=3200, finished=None):
    return {'metadata': {'name': name, 'creationTimestamp': iso(created)},
            'spec': {'snapshotName': name},
            'status': {'state': state, 'backupCreatedAt': iso(finished) if finished else ''}}


class RetryTests(unittest.TestCase):
    def test_kubernetes_api_retries_transient_throttling(self):
        class Token:
            def read_text(self):
                return 'test-token'

        class Opener:
            calls = 0

            def open(self, request, timeout):
                self.calls += 1
                if self.calls == 1:
                    raise urllib.error.HTTPError(request.full_url, 429, 'throttled', {}, None)
                return io.BytesIO(b'{"items": []}')

        client = retry.Kubernetes.__new__(retry.Kubernetes)
        client.token = Token()
        client.opener = Opener()
        client.base = 'https://kubernetes.default.svc'
        with mock.patch.object(retry.time, 'sleep') as sleep:
            self.assertEqual(client.request(retry.API + '/snapshots'), {'items': []})
        self.assertEqual(client.opener.calls, 2)
        sleep.assert_called_once_with(1)

    def test_job_success_does_not_mask_missing_volume_backup(self):
        client = FakeKubernetes(job(), [volume()])
        retry.run(client, now=3000)
        self.assertEqual(len(client.created), 1)
        path, resource = client.created[0]
        self.assertEqual(path, retry.API + '/snapshots')
        self.assertEqual(resource['spec']['volume'], 'vol-1')

    def test_successful_backup_needs_no_retry(self):
        existing = {'metadata': {'name': 'backup-existing'}, 'spec': {},
                    'status': {'volumeName': 'vol-1', 'state': 'Completed',
                               'backupCreatedAt': iso(1800)}}
        client = FakeKubernetes(job(), [volume()], backups=[existing])
        retry.run(client, now=3000)
        self.assertEqual(client.created, [])

    def test_failed_backup_gets_bounded_second_attempt(self):
        name1 = retry.retry_name('weekly-backup-run', 'vol-1', 1)
        name2 = retry.retry_name('weekly-backup-run', 'vol-1', 2)
        first = snapshot(name1)
        failed = backup(name1, 'Error')
        client = FakeKubernetes(job(), [volume()], backups=[failed], snapshots=[first])
        retry.run(client, now=3200 + retry.SECOND_DELAY - 1)
        self.assertEqual(client.created, [])
        retry.run(client, now=3200 + retry.SECOND_DELAY + 1)
        self.assertEqual(client.created[0][1]['metadata']['name'], name2)
        second = snapshot(name2, created=5000)
        second_failed = backup(name2, 'Error', created=5100)
        client = FakeKubernetes(job(), [volume()], backups=[failed, second_failed],
                                snapshots=[first, second])
        retry.run(client, now=6000)
        self.assertEqual(client.created, [])

    def test_waits_for_snapshot_before_creating_backup(self):
        name = retry.retry_name('weekly-backup-run', 'vol-1', 1)
        pending = snapshot(name, ready=False)
        client = FakeKubernetes(job(), [volume()], snapshots=[pending])
        retry.run(client, now=4000)
        self.assertEqual(client.created, [])
        pending['status']['readyToUse'] = True
        retry.run(client, now=4000)
        self.assertEqual(client.created[0][0], retry.API + '/backups')
        self.assertEqual(client.created[0][1]['spec']['snapshotName'], name)

    def test_skips_excluded_and_unhealthy_volumes(self):
        excluded = volume('cache', group='excluded')
        degraded = volume('degraded', robustness='degraded')
        client = FakeKubernetes(job(), [excluded, degraded])
        retry.run(client, now=3000)
        self.assertEqual(client.created, [])

    def test_limits_concurrent_retry_volumes(self):
        client = FakeKubernetes(job(), [volume('a'), volume('b'), volume('c')])
        retry.run(client, now=3000)
        self.assertEqual(len(client.created), 2)
        self.assertEqual({r['spec']['volume'] for _, r in client.created}, {'a', 'b'})

    def test_existing_backup_from_prior_run_prevents_duplicate(self):
        prior = {'metadata': {'name': 'backup-running', 'creationTimestamp': iso(100)},
                 'spec': {}, 'status': {'volumeName': 'vol-1', 'state': 'InProgress'}}
        client = FakeKubernetes(job(), [volume()], backups=[prior])
        retry.run(client, now=3000)
        self.assertEqual(client.created, [])

    def test_retry_window_precedes_freshness_alert(self):
        self.assertLess(retry.RETRY_WINDOW, min(age for _, age in retry.POLICIES.values()))
        client = FakeKubernetes(job(), [volume()])
        retry.run(client, now=2000 + retry.RETRY_WINDOW + 1)
        self.assertEqual(client.created, [])

    def test_generated_configmap_matches_source(self):
        manifest = (ROOT / 'config/longhorn/manifests/backup-retry-configmap.yaml').read_text()
        embedded = '\n'.join(line[4:] if line else '' for line in
                             manifest.split('  backup_retry.py: |\n', 1)[1].splitlines()) + '\n'
        self.assertEqual(embedded, SOURCE.read_text())


if __name__ == '__main__':
    unittest.main()
