"""Read native NVR telemetry; never request images or recordings."""
import json
import math


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def run(ctx, config):
    names = ['Frigate telemetry', 'Frigate camera capture', 'Frigate recording worker']
    try:
        def get(path):
            response = ctx.http(config['url'] + path, timeout=min(6, ctx.remaining()),
                                max_bytes=262144)
            if response.status != 200:
                raise ValueError('HTTP failure')
            value = json.loads(response.body)
            if not isinstance(value, dict):
                raise ValueError('invalid object')
            return value
        stats, settings = get('/api/stats'), get('/api/config')
        service, cameras = stats['service'], settings['cameras']
        if not isinstance(cameras, dict) or not isinstance(stats['cameras'], dict):
            raise ValueError('invalid cameras')
        updated, uptime = service['last_updated'], service['uptime']
        if not number(updated) or not number(uptime) or uptime < 0:
            raise ValueError('invalid service clock')
        stale = not -60 <= ctx.now - updated <= config.get('max_stats_age', 120)
        grace = uptime < config.get('startup_grace', 180)
        enabled, failed, recording = 0, 0, 0
        for camera, settings_row in cameras.items():
            if type(settings_row.get('enabled')) is not bool:
                raise ValueError('invalid enablement')
            if not settings_row['enabled']:
                continue
            enabled += 1
            record = settings_row['record']['enabled']
            if type(record) is not bool:
                raise ValueError('invalid recording enablement')
            recording += int(record)
            row = stats['cameras'].get(camera, {})
            rates_ok = all(number(row.get(k)) and row[k] > 0
                           for k in ('camera_fps', 'process_fps'))
            pids_ok = all(type(row.get(k)) is int and row[k] > 0
                          for k in ('pid', 'capture_pid', 'ffmpeg_pid'))
            failed += int(not (rates_ok and pids_ok))
        worker = stats.get('processes', {}).get('recording', {}).get('pid')
        worker_ok = type(worker) is int and worker > 0
        return [
            ctx.check(names[0], stale, 'native stats stale' if stale else 'native stats fresh'),
            ctx.check(names[1], stale or (bool(failed) and not grace),
                      f'enabled={enabled}; unhealthy={failed}; startup_grace={grace}'),
            ctx.check(names[2], stale or (recording > 0 and not worker_ok and not grace),
                      f'recording-enabled={recording}; worker_present={worker_ok}; startup_grace={grace}')]
    except Exception:
        return [ctx.check(name, True, 'Frigate API unavailable or invalid telemetry') for name in names]
