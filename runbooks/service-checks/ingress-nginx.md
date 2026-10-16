# Ingress nginx functional routing

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

Every 600 seconds, the collector requests `/` on the internal
`ingress-nginx-controller.ingress-nginx.svc.cluster.local` service with
`Host: newjoy.ro`. A healthy result requires HTTP 200, HTML content type,
an HTML document and a title containing `newjoy.ro`. This is the public
landing-page backend declared in `config/landing-page/manifests/ingress.yaml`;
the branded title is checked instead of the temporary construction copy.
Redirects, authentication responses, default-backend HTML and upstream errors
fail. The foundation supplies the `HomePBP-monitor/1` User-Agent.

Requests are read-only, capped at 64 KiB and five seconds (or the remaining
30-second service deadline). Existing execution-based alert debounce applies.
No credentials, extra Kubernetes RBAC, ingress changes or NetworkPolicy
changes are required: the controller and public backend have no destination
NetworkPolicy isolation. No user response data is included in evidence.

A failure means the selected ingress path cannot deliver its expected backend;
inspect controller configuration, endpoints and the landing-page backend.
This shared-service sample does not prove every replica, every route, TLS,
Cloudflare or external DNS. A backend failure also fails this check. Native
reload-success metrics are not enabled in the deployed Helm values; this
baseline deliberately does not enable a new metrics listener or parse
controller logs. It cannot independently detect an un-applied configuration
change that leaves this existing route working.

Before rollout, verify the controller service and public ingress still exist.
If the public site changes its title identity or moves hosts, update this
check alongside that change. Safe live evidence on 2026-10-08: an internal
HTTP request from the existing Baloo pod returned 200, `text/html` and the
source-controlled branded construction title. This is path validation from
Baloo, not a post-deployment collector result.
