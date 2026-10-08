# Cloudflare Tunnel functional checks

The Zabbix collector samples every five minutes with a 30-second deadline and
existing three-failure debounce. Two aggregate assertions supplement existing
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
limit five and its existing 15-second timeout. At most four metrics requests
use two seconds each, and the public request uses four seconds (27 seconds
of transport timeout total), additionally bounded by remaining worker time.
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
