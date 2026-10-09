# Zabbix functional checks

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

The `functional/zabbix` family runs every 15 minutes with a 25-second
execution deadline. Each request is bounded to six seconds, with 256 KiB for API/bootstrap
and 1 MiB for the deployed theme stylesheet;
no redirects are followed. The normal discovery and execution-based
trigger policy applies (cached samples do not count as new executions).

* `Zabbix JSON-RPC capability` anonymously POSTs `apiinfo.version` and requires
  HTTP 200, JSON-RPC 2.0, the matching request ID, no error, and a numeric
  three-component version. This catches broken PHP/API routes and protocol
  changes without pinning a patch release or fetching private monitoring data.
* `Zabbix frontend capability` requires the actual username/password login
  bootstrap and fetches one referenced same-origin CSS asset. A missing asset,
  HTML fallback, wrong MIME type, or unusable bootstrap fails.

No credentials, RBAC, bootstrap roles, network policy changes, LLM calls,
notifications, or production mutations are required. Existing namespace-local
frontend ingress admits the collector. Tests cover malformed/unauthorized API
responses, mismatched IDs, timeout redaction, missing/broken assets and external
asset rejection.

These checks exercise the PHP frontend/API and shipped assets, not authenticated
history queries, server processing queues, notification delivery or database
write capability. `apiinfo.version` alone does not prove database availability.
No existing narrowly scoped identity is mounted into the collector; do not copy
Baloo's credentials or bootstrap an admin role merely to add queue checks.

The native Baloo watchdog independently checks API/collector freshness every 15 minutes. Preserve it and the existing no-data/unsupported-item triggers;
this module does not duplicate its freshness checks. Zabbix cannot report its
own complete outage, and Baloo cannot notify during a whole-cluster/internet
outage. BetterStack remains the independent external detector. See
[monitoring architecture](../zabbix-monitoring.md).
