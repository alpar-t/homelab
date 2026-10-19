"""Check that Frigate's active object detectors are GPU clients."""
import json


def run(ctx, config):
    name = 'Frigate object detection on GPU'
    try:
        response = ctx.http(config['stats_url'], timeout=min(5, ctx.remaining()),
                            max_bytes=131072)
        if response.status != 200:
            raise ValueError('stats HTTP status')
        stats = json.loads(response.body)
        detectors = stats.get('detectors')
        usages = stats.get('gpu_usages')
        if (not isinstance(detectors, dict) or not 1 <= len(detectors) <= 16
                or not isinstance(usages, dict) or not 1 <= len(usages) <= 8):
            raise ValueError('detector or GPU inventory unavailable')

        detector_pids = set()
        for detector in detectors.values():
            pid = detector.get('pid') if isinstance(detector, dict) else None
            if type(pid) is not int or pid <= 0:
                raise ValueError('invalid detector process')
            detector_pids.add(str(pid))

        gpu_clients = set()
        for usage in usages.values():
            clients = usage.get('clients') if isinstance(usage, dict) else None
            if not isinstance(clients, dict) or len(clients) > 1024:
                raise ValueError('GPU client inventory unavailable')
            gpu_clients.update(clients)

        missing = len(detector_pids - gpu_clients)
        return [ctx.check('Frigate detector telemetry', False, 'detector and GPU stats available'),
                ctx.check(name, bool(missing),
                          f'detectors={len(detector_pids)}; GPU clients={len(detector_pids) - missing}; '
                          f'detectors absent from GPU={missing}', severity=4)]
    except Exception:
        # API failures are a monitoring problem, not evidence of CPU inference.
        return [ctx.check('Frigate detector telemetry', True,
                          'detector or GPU stats unavailable'),
                ctx.check(name, False, 'detector mode cannot be observed',
                          observation='unknown')]
