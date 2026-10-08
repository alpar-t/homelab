# Tandoor functional checks

Depends on the functional collector foundation (PR #124). Every five minutes,
with a 25-second execution deadline, the collector validates the public
`/api/server-settings/current/` version/configuration schema and performs a
Bearer-authenticated `GET /api/recipe/?page_size=1`. The latter exercises
space selection, permissions, recipe search, PostgreSQL pagination and the
list serializer. An empty library is healthy. Only fixed diagnostic strings
are emitted; recipe names, identifiers, counts and response bodies never enter
Zabbix. Each request has an eight-second maximum and 128 KiB response cap;
redirects are refused. Normal collector three-failure debounce applies.

A configuration failure means the application API is unreachable or its
contract changed. A backend failure means the credential is missing/expired,
authentication/authorization failed, the database-backed query failed, or the
pagination schema changed. Missing credentials deliberately fail the backend
check while preserving the public configuration signal.

## Credential prerequisite

Create a dedicated non-staff, non-superuser monitoring account. Give it only
`guest` membership in the intended recipe space and select that active space.
Create an expiring Tandoor OAuth access token with **only `read` scope** through
its access-token management UI/API as that account. Do not use
`/api-token-auth/`: version 2.6.13 creates a broad `read write app` token there.
Use a dedicated empty space when household recipe access is unnecessary; this
still exercises the same database/search/serializer path. It will not verify
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
