# MetalLB functional monitoring

The collector checks the ten explicitly expected LAN LoadBalancer services every
300 seconds (failed checks retry at 60 seconds), under the shared 30-second
execution deadline and three-sample alert policy. Expected names and VIPs are in
`service_metallb.json`; update that inventory and resourceName-scoped RBAC together
when intentionally adding/removing services. Unlisted services, including an
intentionally pending new service, do not alert.

Each expected service must retain its configured VIP and have a native
ServiceL2Status native metallb.io/node label owned by a current ready speaker pod on
that node. Stale owner records after a speaker replacement do not count. For
externalTrafficPolicy Local, that node must also have a ready service-selected
backend pod. In deployed v0.15.3, status.node can lag metadata after failover: the
[versioned reconciler](https://github.com/metallb/metallb/blob/v0.15.3/internal/k8s/controllers/layer2_status_controller.go)
uses CreateOrPatch for labels, owners and status on a CR with a status subresource.
Use the native node label matched to a live owner UID, and report a lagging status
node as diagnostic evidence without declaring an outage. This is reconciliation evidence, rather than a repeated
controller Deployment readiness check. Source: [MetalLB API reference](https://metallb.io/apis/).

A second check makes a bounded 5-second, 16 KiB GET to Emby's LAN VIP
192.168.1.204:8096 `/emby/System/Info/Public`, requiring a successful JSON public
server-info contract with Version and Id. Only a fixed success or
failure summary is emitted. It neither plays media nor authenticates a user.
This detects a broken representative VIP/backend path. An inside-cluster VIP
request can take kube-proxy's service path, so it does **not** prove LAN ARP,
external-client reachability, every VIP port, or remote WireGuard connectivity.
L2 status itself is a passive report, not a packet-level ARP test.

No credentials, Secret reads, writes, synthetic services, or network changes are
required. Namespaced Roles grant GET only for the ten expected Service names and
GET/list only for metallb-system ServiceL2Status. Existing pod read access proves
speaker ownership and Local-policy placement. API reads run concurrently using
the client's 15-second timeout to avoid sequential timeout accumulation. API
permission/schema errors fail visibly, with no exception body emitted. Media
currently has no ingress NetworkPolicy, so no policy exception is needed.

Local-policy VIPs must announce where a backend exists; cross-node traffic from
WireGuard can still be rejected by kube-proxy. Preserve the co-location guidance
in AGENTS.md and `runbooks/wireguard-travel-router.md`. The monitor follows live
Local/Cluster policy instead of assuming a historical placement configuration.

Read-only validation on 2026-10-08 observed all ten allocations and native
announcement records and a semantic Emby response (version 4.9.3.0). All ten
allocation/announcement checks passed using current native metadata and owner
UIDs. WireGuard status.node still named pamacs while native label, current owner
and Local backend were on buksi; this is diagnostic status lag, not proven
VIP outage. This was
workstation validation, not a deployed collector test. After rollout, confirm
fresh functional/metallb records and the collector's granted RBAC. Missing or
malformed inventory produces monitoring failure, never a healthy substitute.


## Combined collector load bounds

The review caps this module at three concurrent requests. Workers are joined
before a poll returns, so running scrape threads are never abandoned for a later
execution to multiply. The shared foundation enforces elapsed body-read budgets
with read1 and remaining socket timeouts; Kubernetes transport uses five seconds
and a 4 MiB JSON cap. Synchronous DNS and response header parsing remain platform
resolver / socket inactivity limits. No retry threads or broader RBAC are added.

The pod and L2-status lists request one page (500 pods / 100 statuses), reject
continuation, and retain ten name-scoped Service GETs. No clusterwide Service
permission is added to optimize request count. An oversized inventory reports
monitoring unavailable and requires explicit review.
