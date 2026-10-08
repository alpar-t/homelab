# Zabbix functional checks

The `functional/zabbix` family runs every five minutes with a 25-second
execution deadline. Each request is bounded to six seconds, with 256 KiB for API/bootstrap
and 1 MiB for the deployed theme stylesheet;
no redirects are followed. The normal discovery and three-failing-snapshot
trigger policy applies (cached samples are included between executions).

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

The native Baloo watchdog independently checks API/collector freshness every
five minutes. Preserve it and the existing no-data/unsupported-item triggers;
this module does not duplicate its freshness checks. Zabbix cannot report its
own complete outage, and Baloo cannot notify during a whole-cluster/internet
outage. BetterStack remains the independent external detector. See
[monitoring architecture](../zabbix-monitoring.md).
