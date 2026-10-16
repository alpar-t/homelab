# Tandoor functional checks

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

Depends on the functional collector foundation (PR #124). Every 15 minutes,
with a 25-second execution deadline, the collector validates the public
`/api/server-settings/current/` version/configuration schema and performs a
Bearer-authenticated `GET /api/recipe/?page_size=1`. The latter exercises
space selection, permissions, recipe search, PostgreSQL pagination and the
list serializer. An empty library is healthy. Only fixed diagnostic strings
are emitted; recipe names, identifiers, counts and response bodies never enter
Zabbix. Each request has an five-second maximum and 128 KiB response cap;
redirects are refused. Normal collector execution-based debounce applies.

A configuration failure means the application API is unreachable or its
contract changed. A backend failure means a supplied credential expired or was rejected,
authentication/authorization failed, the database-backed query failed, or the
pagination schema changed. Absent credentials defer authenticated coverage; rejected credentials deliberately fail the backend
check while preserving the public configuration signal.

## Credential prerequisite

Create a dedicated non-staff, non-superuser monitoring account. Give it only
`guest` membership in a dedicated empty monitoring recipe space and select that
active space. Give the account no household-space memberships.
Create an expiring Tandoor OAuth access token with **only `read` scope** through
its access-token management UI/API as that account. Do not use
`/api-token-auth/`: version 2.6.13 creates a broad `read write app` token there.
Keep the monitoring space empty. The read-scoped token can read every recipe
visible to its identity if stolen, so account and space isolation are essential.
An empty space still exercises the same database/search/serializer path. It will not verify
household-space permissions or existing recipe rows in that configuration.

Store the token as key `tandoor_read_token` in the existing manually managed
`zabbix/zabbix-functional-credentials` Secret. Preserve other services' keys;
use the established secure Secret provisioning process and do not put the
value into Git, command arguments, or logs. The collector optional Secret
volume reads it without Secret API permissions. Delete/revoke the token in
Tandoor to revoke access; provision a replacement key before expiry. No broad
administrator token or RBAC expansion is required. Tandoor has no destination
NetworkPolicy in the source manifests, and collector egress already permits
this internal HTTP request; no policy widening is necessary.

## Validation and limits

`scripts/test zabbix` covers empty/populated lists, malformed responses,
unauthorized responses, refused redirects, missing credentials, and timeouts.
`kubectl kustomize config/zabbix/manifests` validates packaging.

API semantics were confirmed by reading the deployed 2.6.13 Python source:
`ServerSettingsViewSet`, `RecipePagination`, `RecipeViewSet`,
`CustomRecipePermission`, `CustomTokenHasReadWriteScope`, and OAuth settings.
The guest role permits safe recipe reads, and OAuth `read` scope is checked
for safe methods. [Upstream versioned API source](https://github.com/TandoorRecipes/recipes/blob/2.6.13/cookbook/views/api.py)
is a reference. No authenticated live query was performed because a dedicated
monitor token has not been provisioned. This does not prove recipe edits,
imports, meal planning, image delivery, OIDC login or outbound email work.

Missing monitoring credentials defer the authenticated portion at informational
severity with dashboard-only evidence; this is a coverage prerequisite, not an
application-outage page or a confirmed recovery. Public/dependency observations
continue independently. A supplied credential that is rejected remains a real
failed execution. No additional authority is accepted to expand coverage.
