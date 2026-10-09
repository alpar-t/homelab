# Vaultwarden functional baseline

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

The Zabbix functional runner samples the internal Vaultwarden service every 15 minutes with a 30-second worker deadline and the existing execution-based alert
debounce. Four requests produce three signals:

- `/api/config` must advertise the Vaultwarden client config schema, a version,
  the expected public vault/API/identity URLs, and disabled public registration.
- POST `/identity/accounts/prelogin` with fixed
  `functional-monitor@monitor.invalid` must return coherent legacy and nested
  PBKDF2 KDF settings. This read-only handler acquires a database connection and
  looks up the identifier; it does not attempt authentication or change data.
- The web vault must include `app-root` and a first-party JavaScript bundle.
  A referenced polyfills bundle must return JavaScript rather than an HTML SPA
  fallback, with nontrivial content. Only one bundle is downloaded; large main
  and vendor bundles are deliberately avoided.

No credentials, new RBAC or network access policy changes are needed: the service
currently has no ingress-restricting NetworkPolicy. Keep the reserved identifier
unregistered. Requests have five-second timeouts, response caps and no redirect
following. Responses, account fields and exception strings never enter output.

These checks catch broken config/domain settings, database-backed bootstrap API
failures and missing frontend bootstrap assets despite `/alive` passing. They do
not prove authenticated vault sync, decryption, attachment retrieval, notifications
or compatibility with every newly released client. Continue the release review
and real-client post-upgrade checks in [Vaultwarden maintenance](../vaultwarden-maintenance.md).

Protocol reference: deployed [1.37.1 config handler](https://github.com/dani-garcia/vaultwarden/blob/1.37.1/src/api/core/mod.rs)
and [prelogin handler](https://github.com/dani-garcia/vaultwarden/blob/1.37.1/src/api/core/accounts.rs).
The latter returns default KDF metadata for unknown identifiers without writes.
