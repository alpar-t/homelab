# Cloudflare Tunnel functional checks

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

The Zabbix collector samples every ten minutes with a 30-second deadline and
execution-based confirmation. Two aggregate assertions supplement existing
pod readiness/restart checks:

- At least three nonterminating connectors expose a valid native
  `cloudflared_tunnel_ha_connections` gauge of at least one. A fourth surge
  connector may still be connecting during rolling upgrades. Lost connection
  capacity, unreadable metrics, missing replicas or malformed inventory fail.
- `https://newjoy.ro/` returns HTTP 200 HTML with `<html`, `<title` and
  `newjoy.ro` markers. Login redirects, Cloudflare errors and arbitrary status
  pages fail. Requests use `HomePBP-monitor/1`, avoiding the WAF treatment of
  Python's default user agent without changing any WAF policy.

The inventory request uses existing pod-read RBAC, a single bounded list with
limit five and a five-second request budget. At most four metrics requests
use two seconds each, and the public request uses four seconds (17 seconds
of transport budget total). The admission guard reserves those 17 seconds,
and each body read also consumes the remaining service deadline.
Bodies are capped at 256 KiB. No credentials, Secret reads, RBAC additions or
NetworkPolicy changes are required: cloudflared currently has no restricting
NetworkPolicy and its configured metrics listener is on port 2000.

Keep `expected_replicas` aligned with the intended Deployment count. More than
four active connectors or paginated inventory reports unavailable instead of
silently sampling a subset. Details contain aggregate counts, never pod names,
metrics labels, credentials or HTTP bodies.

This is an inside-out observation from the cluster's own public DNS/internet
path. It cannot prove reachability from every outside ISP or region, every
hostname, authenticated application workflows, or every connector's ability
to proxy user traffic. A connection gauge proves reported edge connections;
a healthy public response can be cached by Cloudflare and does not alone prove
an origin transaction. Partial connection loss within an otherwise connected
connector is tolerated. Existing readiness/OOM alerts remain responsible for
process health. Native gauge semantics are documented in
[Cloudflare observability](https://developers.cloudflare.com/tunnel/observability/).

Safe live verification on 2026-10-08: from the existing collector, one native
connector gauge reported four connections and the public homepage returned
200 HTML with the expected markers. The full module was subsequently checked
against all live connectors as recorded in the PR. No outage was simulated.
See [availability history](../cloudflare-tunnel-availability.md) for recovery.

Partial connector loss is a Warning dashboard problem while at least one
connector remains connected; complete observed loss is Average and page-eligible.
Unreadable Kubernetes inventory raises one shared telemetry incident rather than
inventing zero connected replicas. Public semantic failure remains actionable
with its own independent-observation grace; it also depends on the website.
