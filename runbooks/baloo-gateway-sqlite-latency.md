# Baloo Gateway SQLite startup latency

On 2026-09-29, an interactive New Joy organizer request in `baloo.newjoy.ro`
ended with an incomplete HTTP transfer after Kubernetes restarted the OpenClaw
Gateway. The old Gateway's liveness probe launched a Node process to request
`/healthz`; three probe failures during a busy turn caused the restart. The
container exited 137 after kubelet termination. Its cgroup recorded no OOM
events, and CPU throttling was minor (15 of 2,118 quota periods).

The Gateway logged repeated `slow SQLite transaction hold` records around
1.5 seconds for `agent.database.maintenance.admission` on
`/state/state/openclaw.sqlite`, plus startup checkpoint and schema work.
OpenClaw 2026.9.6's `runExistingOpenClawStateWriteTransaction` performs a full
`PRAGMA integrity_check` inside these transactions. A read-only direct check
on the 134 MiB state database took 1,568 ms; `foreign_key_check` took under
1 ms. A 20-write probe on the Longhorn SSD volume had 2.8 ms median `fsync`,
so the observed 1.5-second holds were integrity scan work, not raw storage
latency. The 948 MiB Alpar agent database also took 4.4 seconds to verify at
cold open. The state database was 71% full at the filesystem level, with only
8 MiB of freelist pages; `audit_events` held about 99,700 records, with about
53,700 from the past seven days. OpenClaw 2026.9.6 hard codes a 30-day audit
window and a 100,000-row cap. A seven-day window would reduce the audit row
count by roughly 46%, but would still leave full integrity scans on every
maintenance admission. Do not delete audit rows while the live Gateway owns
this SQLite file; use a supported retention and maintenance path when OpenClaw
provides one.

The deployment now uses kubelet HTTP probes directly on the Gateway's pod IP
and allows six failed liveness checks, avoiding an extra Node startup per
probe and allowing brief stalls to recover. Verify after rollout:

```sh
kubectl -n baloo get pods -l app.kubernetes.io/name=openclaw
kubectl -n baloo get deployment openclaw -o yaml
kubectl -n baloo logs deployment/openclaw -c openclaw --since=15m
```

After the 2026-09-29 organizer run completed, the Gateway container had
10.7 GiB charged to its cgroup against a 12 GiB limit: 7.9 GiB anonymous
memory and 2.4 GiB file cache. The gateway process itself was about 2.9 GiB
RSS, but 26 Codex app servers (for 19 configured agents) and their MCP
children remained resident. Seven agents had duplicate app servers. The
deployment reserves 10 GiB and limits this container to 16 GiB as temporary
headroom; this does not shorten SQLite integrity scans. Watch both the cgroup
and the process count, because the gateway's own RSS understates usage.

OpenClaw 2026.9.6 also has a [prepared model catalog worker registry rebuild](https://github.com/openclaw/openclaw/issues/159514)
that can retain modules after repeated requests. The [fix was merged on
2026-09-28](https://github.com/openclaw/openclaw/pull/160055), after the
latest 2026.9.6 release. Upgrade only once a tagged release includes it;
check whether catalog worker heap and container usage stabilize afterward.
Separate upstream reports describe [Codex app-server client eviction across
agents](https://github.com/openclaw/openclaw/issues/79495) and [one-shot
cleanup leaving app servers alive](https://github.com/openclaw/openclaw/issues/101788).
These match the process shape but have not been proven as this pod's exact
cause. An off-peak gateway restart clears accumulated children if memory
approaches the limit; check active sessions first because it interrupts turns.

The upstream redundant full-check issue is
[openclaw/openclaw#118885](https://github.com/openclaw/openclaw/issues/118885).
OpenClaw documents that these checks protect database trust boundaries; do
not disable or replace them with `quick_check` through an image patch. Track a
verified upstream fix and test a candidate against the existing SQLite files
before upgrading. OpenClaw's [SQLite transaction logging reference](https://docs.openclaw.ai/logging)
explains that a hold includes the synchronous callback and is not by itself
proof of a lock wait. A new recurring slow hold after startup needs a fresh
operation label and timing investigation; the measurements above describe this
specific incident.
