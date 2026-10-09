# Portal functional checks

## Polling and incident confirmation

Poll every 1800 seconds (30 minutes); shared failure grace is 3600 seconds.
A problem needs both the elapsed grace and at least two independent failed
executions; recovery needs two independent healthy executions. At this cadence
and grace, ordinary continuous failure normally requires three failed runs.
Minute snapshots never count as new observations, and failures keep the same
slow cadence. Scheduling is staggered. Referenced workload reboot/rescheduling
grace and maintenance preserve confirmed state without declaring recovery.
Persistent ordinary outages page; module-specific advisories stay on the dashboard.
See [the shared framework](../service-functional-checks.md) for startup,
unknown/deferred observations and queue freshness.

The collector samples every 30 minutes with a 30-second deadline and three-second
HTTP timeouts. execution-baseds trigger the existing Zabbix alert debounce.
No credentials or additional Kubernetes permissions are required. The portal has
no destination NetworkPolicy restricting the collector; no access policy changes
are introduced.

- `Portal frontend assets`: internal shell semantic marker and its required theme script,
  application script and stylesheet must be nonempty and have expected MIME types.
- `Portal catalog contract`: internal `/catalog.json` requests use synthetic trusted-backend
  group headers for admin, family and kids. Validate sections/cards, capability
  policy coverage, referenced SVG icons. Direct
  backing-catalog access must remain 404. This deliberately exercises the backend
  contract; headers never go to the public endpoint. Catalog contents, link URLs,
  and response bodies are never reported.
- `Portal public sign-in gate`: anonymous public entry must redirect to the same portal's
  `/oauth2/start` with its root return URL. Redirects are not followed. Accept the root return URL in relative or absolute form.
  Use the existing collector user agent `HomePBP-monitor/1`; Cloudflare rejects
  the default Python urllib user agent with 403 on this monitoring path.

Failures mean the shipped site/catalog/assets are unusable, inconsistent, or the
public authentication entry gate changed. This does not perform a user login or
prove OIDC group enforcement, correct role membership, JavaScript execution,
linked-service functionality or successful Pocket ID authorization. Asset requests
are tiny read-only operations; catalog links are never visited. Fixed asset paths
match the shipped portal contract, so an intentional frontend contract change
requires updating this monitor. A live anonymous collector request with this user agent returned 302 to the
portal sign-in route with a valid root return URL. No deployment was performed.
