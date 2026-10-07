#!/usr/bin/env python3
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'config/zabbix/manifests/assets'))
from mail_activity import MailActivity

POLICY = json.loads((ROOT / 'config/zabbix/manifests/assets/policy.json').read_text())['mail_activity']
NOW = dt.datetime(2026, 10, 7, 9, tzinfo=dt.timezone.utc).timestamp()


def line(stamp, message):
    iso = dt.datetime.fromtimestamp(stamp, dt.timezone.utc).isoformat().replace('+00:00', 'Z')
    return f'{iso} {iso} INFO {message}'


def queue(identifier, stamp, address='::1'):
    return line(stamp, f'Queued message for delivery (queue.queue-message) listenerId = "smtp", localPort = 25, remoteIp = {address}, queueId = {identifier}, from = "sender@example.invalid"')


def ingest(identifier, stamp, kind='ham'):
    title = 'Message ingested' if kind == 'ham' else 'Spam message ingested'
    return line(stamp, f'{title} (message-ingest.{kind}) queueId = {identifier}, accountId = 3, messageId = "private-message@example.invalid"')


def arrivals(stamps):
    return '\n'.join(row for i, stamp in enumerate(stamps, 1) for row in (queue(i, stamp), ingest(i, stamp)))


class MailActivityTests(unittest.TestCase):
    def test_only_successfully_stored_external_messages_count(self):
        rows = [queue(1, NOW-100), ingest(1, NOW-99), queue(2, NOW-80), ingest(2, NOW-79, 'spam'),
                queue(3, NOW-50, '10.42.0.36'), ingest(3, NOW-49), queue(4, NOW-40),
                line(NOW-39, 'Failed ingestion (message-ingest.error) queueId = 4'),
                line(NOW-20, 'Message delivered (delivery.delivered) queueId = 5, hostname = "smtp.migadu.com"'),
                line(NOW-10, 'Client appended message (message-ingest.imap-append) accountId = 3'),
                line(NOW-5, 'Unrelated event (smtp.error) details = "Message ingested (message-ingest.ham) queueId = 4"')]
        watcher = MailActivity()
        result = watcher.observe(['\n'.join(rows)], NOW, POLICY, True)
        self.assertEqual(result['arrivals_today'], 2)
        self.assertEqual(len(watcher.state['arrivals']), 2)
        self.assertEqual(result['last_arrival'], NOW-79)

    def test_duplicate_queries_and_multiple_recipients_do_not_inflate_counts(self):
        text = '\n'.join([queue(1, NOW-100), ingest(1, NOW-99), ingest(1, NOW-98)])
        watcher = MailActivity()
        watcher.observe([text, text], NOW, POLICY)
        watcher.observe([text], NOW+60, POLICY)
        self.assertEqual(len(watcher.state['arrivals']), 1)

    def test_queue_correlation_survives_restart_without_retaining_message_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            first = MailActivity(path)
            first.observe([queue(987654321, NOW-100)], NOW-90, POLICY)
            second = MailActivity(path)
            result = second.observe([ingest(987654321, NOW-80)], NOW, POLICY)
            self.assertEqual(result['arrivals_today'], 1)
            content = path.read_text()
            for private in ('sender@example.invalid', 'private-message', '987654321', 'accountId'):
                self.assertNotIn(private, content)

    def test_sparse_history_uses_initial_24_hour_threshold(self):
        watcher = MailActivity()
        result = watcher.observe([arrivals([NOW-11000, NOW-1000])], NOW, POLICY)
        self.assertEqual(result['threshold_seconds'], 24*3600)
        self.assertFalse(result['bad'])
        self.assertTrue(watcher.summary(NOW+24*3600, POLICY)['bad'])

    def test_adaptation_uses_completed_gaps_and_ignores_current_silence(self):
        watcher = MailActivity()
        result = watcher.observe([arrivals([NOW-i*3600 for i in range(12, -1, -1)])], NOW, POLICY)
        self.assertEqual(result['threshold_seconds'], 6*3600)
        self.assertTrue(watcher.summary(NOW+7*3600, POLICY)['bad'])
        result = watcher.observe([''], NOW+8*86400, POLICY)
        self.assertEqual(result['threshold_seconds'], 6*3600)
        self.assertTrue(result['bad'])

    def test_gap_after_an_alert_does_not_retrain_a_longer_timeout(self):
        watcher = MailActivity()
        watcher.observe([arrivals([NOW-i*3600 for i in range(12, -1, -1)])], NOW, POLICY)
        result = watcher.observe(['\n'.join([queue(999, NOW+20*3600), ingest(999, NOW+20*3600)])], NOW+20*3600, POLICY)
        self.assertEqual(result['threshold_seconds'], 6*3600)
        self.assertFalse(result['bad'])
        self.assertEqual(len(watcher.state['ignored_gap_ends']), 1)

    def test_arrivals_today_use_bucharest_midnight_but_silence_crosses_midnight(self):
        last = dt.datetime(2026, 10, 6, 20, 30, tzinfo=dt.timezone.utc).timestamp()
        now = dt.datetime(2026, 10, 6, 21, 30, tzinfo=dt.timezone.utc).timestamp()
        result = MailActivity().observe([arrivals([last])], now, POLICY)
        self.assertEqual(result['arrivals_today'], 0)
        self.assertEqual(result['silence_seconds'], 3600)

    def test_recovering_a_poll_gap_requests_history_from_before_the_gap(self):
        watcher = MailActivity()
        watcher.observe([arrivals([NOW])], NOW, POLICY, True)
        options, full = watcher.query_options(NOW+3600, POLICY)
        self.assertFalse(full)
        self.assertEqual(options['since_seconds'], 3720)
        self.assertTrue(options['timestamps'])

    def test_future_timestamps_do_not_advance_the_baseline(self):
        watcher = MailActivity()
        with self.assertRaisesRegex(ValueError, 'future'):
            watcher.observe([arrivals([NOW+3600])], NOW, POLICY)
        self.assertIsNone(watcher.state['last_arrival'])


if __name__ == '__main__':
    unittest.main()
