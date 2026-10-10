"""Observe external mail arrival timestamps; never retain message metadata."""
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

QUEUE = re.compile(r'^\S+ INFO Queued message for delivery \(queue\.queue-message\) ')
INGEST = re.compile(r'^\S+ INFO [^=(\r\n]{1,80}\(message-ingest\.(?:ham|spam)\) ')
QUEUE_ID = re.compile(r'\bqueueId = (\d+)')
LOOPBACK = re.compile(r'\bremoteIp = (?:::1|127\.0\.0\.1|::ffff:127\.0\.0\.1)(?:,|\s|$)')


class MailActivity:
    def __init__(self, state_path=None):
        self.path = Path(state_path) if state_path else None
        self.seeded = False
        self.state = {'version': 1, 'arrivals': {}, 'pending': {}, 'last_arrival': None,
                      'observed_since': None, 'last_poll': 0, 'last_full_scan': 0}
        if self.path and self.path.exists():
            if self.path.stat().st_size > 2097152:
                raise ValueError('Mail arrival state exceeds its bounded capacity')
            value = json.loads(self.path.read_text())
            if value.get('version') != 1:
                raise ValueError('Unknown mail arrival state format')
            for field in ('arrivals', 'pending'):
                if not isinstance(value.get(field), dict) or any(
                    not re.fullmatch(r'[a-f0-9]{20}', key) or not isinstance(stamp, (int, float))
                    or not math.isfinite(stamp) for key, stamp in value[field].items()):
                    raise ValueError('Invalid mail arrival state')
            self.state = value

    def query_options(self, now, policy):
        history = policy['baseline_days'] * 86400
        full = not self.seeded or now - self.state.get('last_full_scan', 0) >= 21600
        since = history if full else min(history, max(600, math.ceil(now - self.state['last_poll']) + 120))
        return {'since_seconds': since, 'limit_bytes': 2097152 if full else 262144,
                'tail_lines': None, 'timestamps': True}, full

    def observe(self, texts, now, policy, full=False):
        """Match loopback fetchmail submissions to successful local ingestion."""
        state = json.loads(json.dumps(self.state))
        cutoff = now - policy['baseline_days'] * 86400
        state['arrivals'] = {key: stamp for key, stamp in state['arrivals'].items() if stamp >= cutoff}
        state['pending'] = {key: stamp for key, stamp in state['pending'].items() if stamp >= cutoff}
        records, earliest = [], now
        for text in texts:
            for line in text.splitlines():
                outer, _, body = line.partition(' ')
                # Only structured logger event prefixes qualify, not text in
                # senders, subjects, or Message-IDs later in a log record.
                if not (QUEUE.match(body) or INGEST.match(body)):
                    try:
                        earliest = min(earliest, dt.datetime.fromisoformat(outer.replace('Z', '+00:00')).timestamp())
                    except ValueError:
                        pass
                    continue
                stamp = dt.datetime.fromisoformat(outer.replace('Z', '+00:00')).timestamp()
                if stamp > now + 60:
                    raise ValueError('Mail event timestamp is in the future')
                earliest = min(earliest, stamp)
                match = QUEUE_ID.search(body)
                if not match:
                    raise ValueError('Mail event has no queue identifier')
                key = hashlib.sha256(match[1].encode()).hexdigest()[:20]
                if QUEUE.match(body):
                    # Other household SMTP clients connect from pod/LAN IPs.
                    if LOOPBACK.search(body) and re.search(r'\blocalPort = 25(?:,|\s|$)', body):
                        state['pending'][key] = stamp
                else:
                    records.append((key, stamp))
        # Queue and ingestion records can interleave between recipients/pods.
        for key, stamp in records:
            if key in state['pending'] or key in state['arrivals']:
                if stamp >= cutoff:
                    state['arrivals'][key] = min(stamp, state['arrivals'].get(key, stamp))
                state['last_arrival'] = max(stamp, state['last_arrival'] or stamp)
        state['observed_since'] = min(earliest, state['observed_since'] or earliest)
        state['last_poll'] = now
        if full:
            state['last_full_scan'] = now
        if len(state['arrivals']) > 10000 or len(state['pending']) > 10000:
            raise ValueError('Mail arrival history exceeds its bounded capacity')
        # A gap that already crossed the alert deadline is not a normal-rate
        # training example after recovery.
        ignored = set(state.get('ignored_gap_ends', []))
        previous = self.state['last_arrival']
        previous_threshold = self.state.get('threshold', policy['initial_silence_hours'] * 3600)
        ordered = sorted((stamp, key) for key, stamp in state['arrivals'].items())
        for (start, _), (end, key) in zip(ordered, ordered[1:]):
            if previous is not None and end > previous and end - start > previous_threshold:
                ignored.add(key)
        state['ignored_gap_ends'] = sorted(ignored.intersection(state['arrivals']))
        self._calibrate(state, policy)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            with temporary.open('w') as file:
                os.chmod(temporary, 0o600)
                json.dump(state, file, separators=(',', ':'))
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        self.state, self.seeded = state, True
        return self.summary(now, policy)

    @staticmethod
    def _calibrate(state, policy):
        signature = json.dumps(policy, sort_keys=True)
        # An ongoing silence never trains its own threshold or changes it as
        # older samples expire. Recalibrate only on an actual new arrival or
        # an explicitly changed policy.
        if (state.get('calibrated_for') == state['last_arrival']
                and state.get('policy') == signature and 'threshold' in state):
            return
        stamps = sorted((stamp, key) for key, stamp in state['arrivals'].items())
        ignored = set(state.get('ignored_gap_ends', []))
        gaps = sorted(b - a for (a, _), (b, key) in zip(stamps, stamps[1:]) if b > a and key not in ignored)
        threshold = policy['initial_silence_hours'] * 3600
        p90 = gaps[math.ceil(.9 * len(gaps)) - 1] if gaps else None
        if len(gaps) >= policy['minimum_gap_samples']:
            threshold = math.ceil(p90 * policy['gap_multiplier'] / 3600) * 3600
            threshold = max(policy['minimum_silence_hours'] * 3600,
                            min(policy['maximum_silence_hours'] * 3600, threshold))
        state.update(threshold=threshold, calibrated_for=state['last_arrival'],
                     policy=signature, gap_samples=len(gaps), p90_gap=p90)

    def summary(self, now, policy):
        zone = ZoneInfo(policy['timezone'])
        today = dt.datetime.fromtimestamp(now, zone).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        stamps = sorted(self.state['arrivals'].values())
        last = self.state['last_arrival']
        reference = last if last is not None else self.state['observed_since']
        silence = max(0, now - reference) if reference is not None else 0
        threshold = self.state.get('threshold', policy['initial_silence_hours'] * 3600)
        count_today = sum(stamp >= today for stamp in stamps)
        last_text = dt.datetime.fromtimestamp(last, zone).strftime('%Y-%m-%d %H:%M %Z') if last else 'none in retained history'
        threshold_source = ('fixed silence threshold by policy' if
                            policy['initial_silence_hours'] == policy['minimum_silence_hours'] == policy['maximum_silence_hours']
                            else f'threshold learned from {self.state.get("gap_samples", 0)} completed gap samples')
        detail = (f'{silence / 3600:.1f}h since last external arrival; alert after {threshold / 3600:g}h; '
                  f'last arrival {last_text}; {count_today} arrivals today; '
                  f'{len(stamps)} arrivals in the rolling {policy["baseline_days"]}-day history; '
                  f'{threshold_source}')
        return {'bad': silence > threshold, 'detail': detail, 'silence_seconds': round(silence),
                'threshold_seconds': threshold, 'arrivals_today': count_today,
                'last_arrival': last, 'gap_samples': self.state.get('gap_samples', 0)}
