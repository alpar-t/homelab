"""Exercise the deployed log follower across OTMonitor's midnight rotation."""
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import tempfile
import textwrap
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT = ROOT / 'config/otmonitor/manifests/deployment.yaml'


class LogTailerTest(unittest.TestCase):
    def test_new_daily_file_is_followed_without_replaying_old_logs(self):
        source = DEPLOYMENT.read_text()
        match = re.search(r'          args:\n            - \|\n(?P<script>.*?)          volumeMounts:',
                          source[source.index('name: log-tailer'):], re.S)
        self.assertIsNotNone(match)
        with tempfile.TemporaryDirectory() as directory:
            logs = Path(directory) / 'logs'
            logs.mkdir()
            yesterday = logs / 'otlog-20261010.txt'
            yesterday.write_text('historical frame\n')
            script = textwrap.dedent(match.group('script')).replace('/config/logs', str(logs))
            process = subprocess.Popen(['/bin/sh', '-c', script], stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, start_new_session=True)
            try:
                time.sleep(0.5)
                with yesterday.open('a') as stream:
                    stream.write('current frame\n')
                output = self._read_until(process.stdout, b'current frame\n')
                self.assertNotIn(b'historical frame', output)

                today = logs / 'otlog-20261011.txt'
                today.write_text('first new-day frame\n')
                output = self._read_until(process.stdout, b'first new-day frame\n', timeout=9)
                self.assertIn(b'first new-day frame\n', output)
            finally:
                os.killpg(process.pid, signal.SIGTERM)
                process.communicate(timeout=3)

    @staticmethod
    def _read_until(stream, marker, timeout=5):
        output = b''
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready, _, _ = select.select([stream], [], [], max(0, deadline - time.monotonic()))
            if not ready:
                continue
            part = os.read(stream.fileno(), 65536)
            if not part:
                break
            output += part
            if marker in output:
                return output
        raise AssertionError(f'log follower did not emit {marker!r}; output={output!r}')


if __name__ == '__main__':
    unittest.main()
