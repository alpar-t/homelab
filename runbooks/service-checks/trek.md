# TREK trip-planner functional checks

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

The collector checks the internal TREK service every 15 minutes with a 25-second
worker deadline, three GETs, five-second request limits and bounded responses.
The foundation's normal execution-based debounce applies. No credentials, RBAC or
NetworkPolicy changes are needed: TREK has no ingress NetworkPolicy and the
collector namespace has no egress isolation.

* **Database and sign-in bootstrap:** `/api/auth/app-config` must return the
  deployed boolean/version contract, existing users and at least one configured
  enabled sign-in method. In deployed 3.4.1 `getAppConfig` performs SQLite reads
  against users and app_settings, so this catches backend/database breakage.
  `setup_complete` is checked for type only: a bootstrap administrator awaiting a
  password change reports false even while OIDC users can sign in normally.
* **Frontend bundle:** `/` must contain the React root and a same-origin module
  asset under `/assets/`. Fetch bytes 0–4095 of that module; require HTTP 206,
  correct Content-Range, JavaScript type and a non-HTML body. The deployed main
  bundle is about 7 MB, so Range prevents downloading it every 15 minutes.
  Servers that stop supporting ranges intentionally fail this bounded contract.

Response bodies, user counts, itinerary data and exception messages are never
included in results. These checks prove SQLite-backed sign-in configuration and
frontend delivery, not browser execution, complete bundle integrity, successful
OIDC login, trip permissions, writes, maps, or authenticated trip-list reads.
No monitoring account is required for this baseline. Authenticated trip metadata
coverage is deferred until TREK provides a suitably scoped read-only credential;
do not copy an administrator token or household session into the collector.

Contract verified from running 3.4.1 source:
`/app/server/dist/services/authService.js` (`getAppConfig`),
`/app/server/dist/nest/auth/auth-public.controller.js`, and
`/app/server/public/index.html`. Live anonymous bootstrap and asset Range reads
confirmed the expected schemas on 2026-10-08. No production mutation was made.
