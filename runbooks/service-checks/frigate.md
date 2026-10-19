# Frigate functional monitoring

## Polling and incident confirmation

Poll every 600 seconds (10 minutes); shared failure grace is 900 seconds.
A new problem needs both that elapsed grace and at least two independent failed
executions; at this cadence an ordinary continuous failure normally requires
three runs. Recovery needs two independent healthy executions. The first
candidate failure can remain pending while confirmation accumulates. Cached
minute snapshots do not count as new executions, and failures keep the same
slow cadence. Combined with notification confirmation, a new persistent page
incident normally appears about 32–42 minutes after the outage, before queue
or referenced-workload reboot/rescheduling grace and maintenance delays.
See [the shared framework](../service-functional-checks.md) for unknown/deferred
observations, startup and incident persistence.

Every ten minutes the collector reads `/api/stats` and `/api/config` from the
internal unauthenticated port 5000. No credentials, Kubernetes permissions or
new network rules are needed: Frigate currently has no ingress NetworkPolicy.
Keep this API private. Config responses can contain camera credentials; the
check retains no response and emits only aggregate counts and fixed messages.

The three signals detect stale native stats (120 seconds), enabled cameras with
zero capture/process FPS or missing capture/process/ffmpeg PIDs, and an absent
recording worker while any enabled camera has recording enabled. A 180-second
startup grace permits camera/worker initialization; the shared runner also
requires distinct failed executions plus the configured elapsed grace. Requests have six-second timeouts,
256 KiB limits and a 20-second service deadline.

Runtime camera `enabled` and `record.enabled` settings are authoritative.
Disabled cameras are excluded. Object detection FPS, motion and the age of the
last retained recording are deliberately ignored: detection can be disabled,
and motion-only retention permits indefinitely idle scenes. Empty/all-disabled
camera configurations pass when native telemetry is fresh.

Version 0.17.2's deployed `frigate.stats.emitter.stats_snapshot` supplies these
fields. Its recording maintainer loops every five seconds, but the exposed stats
provide a PID rather than a worker heartbeat. Fresh stats plus a PID prove
worker registration only; they cannot prove an unblocked recording worker,
successful disk writes, retained footage or playable media. Capture rates detect
a stuck capture path even when ffmpeg still has a PID. No snapshots, footage,
recording lists, settings writes or storage probes are requested.

The intentionally quarantined disposable HDD and single-replica media PVC keep
their policy in [the disk runbook](../frigate-disposable-media-disk.md). This
check adds no SMART/backup/replica assertions and does not reinterpret accepted
disk counters. A functional recording/capture failure still needs investigation;
accepting disposable footage does not mean a broken NVR is healthy.

Read-only rollout evidence on 2026-10-08: deployed stats/config schemas matched;
front and gate had roughly 12 FPS, while enabled back had zero capture/process
FPS. The camera check is expected to alert on that existing condition until
the camera is repaired or intentionally disabled. Monitoring does not change it.

Unavailable, invalid or stale telemetry creates one telemetry problem. Camera
capture and recording rows then report unknown observations, retaining any
previously confirmed incident without asserting a new outage or recovery.
Startup grace also reports unknown for those rows; actual fresh post-startup
observations are required to recover. Disabled cameras and idle recording
remain healthy when fresh telemetry proves their configured state.
