# Newjoy public website functional checks

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

`service_landing_page` runs every 30 minutes with a 30-second worker deadline.
Two checks fetch the internal landing-page Service and public HTTPS `newjoy.ro`
route. Each requires HTTP 200, HTML content type, document/head/body/title/h1
structure, and `newjoy.ro` identity in title or heading. It accepts the current
inline CSS without relying on marketing copy or layout classes.

If the homepage declares same-origin JS or CSS, the first such asset is fetched
and must be nonempty with a matching content type. HTML SPA fallback fails.
Third-party assets are never fetched. Current source declares no first-party
JS/CSS files, so inline stylesheet syntax is the styling baseline. Cloudflare
may rewrite public fonts into inline CSS; font files are outside this baseline.
Requests cap homepage at 256 KiB and the selected asset at 512 KiB, each with
at most six seconds and remaining worker time. Redirects fail visibly.

No credentials, new RBAC, or access policy changes are needed. Landing-page has
no ingress NetworkPolicy and collector has no egress isolation in source.
Deploy only after foundation PR #124; normal execution-based debounce applies.

A failure means the homepage contract, delivery route, or selected frontend
asset is unavailable. Inspect landing-page ConfigMap/Service/Ingress and public
Cloudflare delivery before changing expectations. Keep identity aligned when
replacing the placeholder site. This does not execute JavaScript, render pixels,
check all replicas/assets, follow outbound links, or prove availability from an
external internet location. It performs at most four GETs per 1800-second run.

Live validation on 2026-10-08 ran this exact module and shared HTTP Context
transiently through stdin in the collector pod; internal and public checks
passed. Requests explicitly use `User-Agent: HomePBP-monitor/1`: the default
Python user agent received a public 403, while this monitor identity succeeds.
No Cloudflare policy or persistent collector files were changed.
