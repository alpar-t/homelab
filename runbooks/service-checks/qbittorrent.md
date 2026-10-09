# qBittorrent functional checks

## Polling and incident confirmation

Poll every 900 seconds (15 minutes); shared failure grace is 1800 seconds.
A problem needs both the elapsed grace and at least two independent failed
executions; recovery needs two independent healthy executions. At this cadence
and grace, ordinary continuous failure normally requires three failed runs.
Minute snapshots never count as new observations, and failures keep the same
slow cadence. Scheduling is staggered. Referenced workload reboot/rescheduling
grace and maintenance preserve confirmed state without declaring recovery.
Persistent ordinary outages page; module-specific advisories stay on the dashboard.
See [the shared framework](../service-functional-checks.md) for startup,
unknown/deferred observations and queue freshness.

Every 15 minutes, the collector uses the existing internal Web API session policy at `qbittorrent.media.svc.cluster.local:8080`. Two GET requests validate `/api/v2/app/version` and `/api/v2/transfer/info`; only a disconnected global session requires a third request to `/api/v2/torrents/info?filter=downloading&limit=1`. Each request has a five-second timeout, a bounded response, and a shared twenty-second deadline. Existing execution-based alert debounce applies.

The session check catches unauthorized responses, login HTML, incompatible version payloads and timeouts. Transfer validation requires the documented connection status and nonnegative integer speeds. Disconnected sessions alert only when the downloading filter contains unfinished activity. Zero torrents and disconnected idle sessions pass; firewalled sessions pass because they can still download. Names, paths, hashes, trackers, cookies and response bodies never enter results. No torrents are added, resumed, deleted, rechecked or changed.

## Authentication and rollout

Read-only production probes on 2026-10-08 from the existing OpenClaw pod returned a valid application version and `connected` transfer schema without cookies. This establishes the deployed internal API behavior, not an authenticated monitor identity or proof that the collector's different source IP is accepted. Validate the collector after rollout. There is no destination NetworkPolicy restricting the arr-stack pod and the collector has no egress restriction.

qBittorrent's native WebUI has one account with full torrent-management privileges, cookie authentication and no read-only role. This implementation does not provision or copy that account, a SID, or Radarr credentials. It does not widen authentication bypass ranges or attempt login. If the collector's source is rejected (or native bypass is removed), checks report unavailable rather than healthy. In that case a separately reviewed read-only API gateway restricted to these exact GET routes is needed before deeper coverage can be restored; native least-privilege credentials are unsupported. Revoke existing trusted-subnet access in qBittorrent's WebUI settings if required, accepting that this baseline will then report unavailable. Preserve existing public access controls.

This baseline cannot prove tracker reachability, disk writes, successful downloads, individual torrent progress, storage capacity or inbound peer access. Connected-but-stalled torrents, intentionally paused queues and slow swarms do not alert. A deliberately disconnected session with downloads should be put into monitoring maintenance. No torrent content is downloaded.

API semantics: [official qBittorrent 5.x WebUI API](https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-%28qBittorrent-5.0%29). The deployed manifest uses qBittorrent 5.1.4.
