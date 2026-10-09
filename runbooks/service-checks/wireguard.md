# Travel WireGuard ingress monitoring

## Polling and incident confirmation

Poll every 600 seconds (10 minutes); shared failure grace is 900 seconds.
A problem needs both the elapsed grace and at least two independent failed
executions; recovery needs two independent healthy executions. At this cadence
and grace, ordinary continuous failure normally requires three failed runs.
Minute snapshots never count as new observations, and failures keep the same
slow cadence. Scheduling is staggered. Referenced workload reboot/rescheduling
grace and maintenance preserve confirmed state without declaring recovery.
Persistent ordinary outages page; module-specific advisories stay on the dashboard.
See [the shared framework](../service-functional-checks.md) for startup,
unknown/deferred observations and queue freshness.

The functional collector checks every 10 minutes, with the shared execution-based
debounce. It validates the UDP/41641 LoadBalancer mapping, reserved VIP
192.168.1.208, Local traffic policy and dedicated selector. A second check requires
exactly one ready, non-terminating EndpointSlice endpoint with UDP/41641 and
pod/node routing metadata. This catches an upgrade or manifest change that leaves
the interface Ready but makes its Service route incorrectly or lose its VIP.

The collector needs only get on the named Service and list on EndpointSlices in
the wireguard namespace, supplied by wireguard-monitoring-rbac.yaml. No credentials,
Secret/config reads, exec, logs, host access, extra capabilities, exporter or
network policy changes are required. Missing/unauthorized/malformed API data fails
closed with generic details. The bounded list rejects pagination rather than
claiming complete coverage. Stable details exclude addresses and peer identities.

This is passive ingress metadata coverage. Existing pod probes run `wg show wg0`
and already cover interface availability. Endpoint metadata does not prove the
kernel listener, MetalLB advertisement, internet-router port forward, firewall/NAT
rules, external UDP path, peer handshake or remote LAN access. There is no existing
unprivileged runtime exporter, and unauthenticated UDP cannot prove a WireGuard
listener. Do not add NET_ADMIN, host access or key reads to the collector to obtain
that signal. A real remote transaction requires an explicitly expected-online
travel peer and a separately authorized remote observer; this baseline has neither.
The travel router may be powered off indefinitely without a handshake alert.

For an alert, inspect Service/EndpointSlices and compare with
[the travel runbook](../wireguard-travel-router.md). Validate the external path from
the GL while it is connected using that runbook's read-only application checks.
Never simulate an outage or restart the production tunnel as a monitoring test.
