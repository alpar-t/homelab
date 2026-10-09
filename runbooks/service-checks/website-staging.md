# Newjoy website staging functional checks

## Polling and incident confirmation

Poll every 1800 seconds (30 minutes); shared failure grace is 3600 seconds.
A problem needs both the elapsed grace and at least two independent failed
executions; recovery needs two independent healthy executions. At this cadence
and grace, ordinary continuous failure normally requires three failed runs.
Minute snapshots never count as new observations, and failures keep the same
slow cadence. Scheduling is staggered. Referenced workload reboot/rescheduling
grace and maintenance preserve confirmed state without declaring recovery.
Availability is advisory and dashboard-only.
See [the shared framework](../service-functional-checks.md) for startup,
unknown/deferred observations and queue freshness.

Every 30 minutes, the Zabbix functional collector checks the internal homepage
for the New Joy identity and staging UI marker, then fetches one declared
first-party Astro stylesheet. Missing assets, HTML fallback responses, broken
content types and an unrelated login/error page fail this check. It separately
validates environment.json identifies staging with the preview banner enabled.
The live homepage contract was inspected read-only on 8 October 2026.

The public signed-out root must redirect to staging.newjoy.ro/oauth2/start with
the expected return URL. That endpoint must redirect to auth.newjoy.ro/authorize
with a code flow, client ID, state, openid scope and the staging callback. No
redirect is followed to Pocket ID and no credentials or cookies are supplied.
An accidentally exposed homepage, wrong callback/issuer, or failed proxy fails.
This verifies sign-in routing, not completed authentication, group authorization,
visual design or importer/build/publication functionality.

Requests use HomePBP-monitor/1, five-second timeouts, a 256KiB response cap and
the shared 30-second execution deadline. Results contain only fixed diagnostic
messages. Existing execution-based alert debounce applies. No credentials, new
RBAC or destination ingress permissions are required: staging has no restricting
NetworkPolicy and the collector permits HTTP/HTTPS egress.

Keep the last accepted/sample staging image monitored while source polling or
publication is idle. No publication-age or story-count expectation is imposed;
an empty project catalog is valid. The source Deployment currently intends one
replica. If staging is deliberately retired or paused, remove this module/config
from the collector generator as part of that reviewed source change rather than
silently considering an unavailable endpoint healthy. See
[newjoy-website-staging.md](../newjoy-website-staging.md) for rollout operations.
