# Prowlarr functional monitoring

Depends on functional monitoring foundation PR #124. Every 300 seconds the
collector performs three fixed authenticated GETs on the internal Prowlarr
Service: `/api/v1/health`, `/api/v1/indexer`, `/api/v1/indexerstatus`.
Each request has a six-second maximum timeout and 256 KiB response cap;
the worker deadline is 25 seconds. Existing Zabbix failure debounce applies.

API health checks authenticated database-backed response shapes and counts
non-indexer health errors. Warnings are advisory and do not alert. Indexer
health entries and NoIndexerAvailableCheck are excluded: the second check
counts future `disabledTill` values only for explicitly enabled indexers.
An empty list, disabled indexers, expired blocks and historical failure times
are healthy. Counts only are reported; names, URLs, fields, keys and health
messages never appear in result details. Missing credentials, rejection,
malformed responses and timeouts are unavailable failures, never healthy.

## Rollout prerequisite

Prowlarr's native API key grants full application API access, including writes;
there is no dedicated read-only key scope. This implementation only issues the
three fixed GETs, but that does not constrain a stolen key. Provisioning this
broad credential is an explicit rollout prerequisite. No key is copied or
provisioned by this PR and no hypothetical authorization proxy is assumed.
An operator must deliberately store the Prowlarr Settings > General API key in
`zabbix/zabbix-functional-credentials`, key `prowlarr_api_key`, using a protected
local file and the organization's Secret provisioning procedure. Preserve
other keys in this shared Secret; never print or commit values. The optional
foundation volume supplies `/credentials/prowlarr_api_key`; no Secret API
permission is needed. Revoke by rotating Prowlarr's API key, update approved
clients and this Secret, and remove the monitoring key when disabling coverage.

The media manifests contain no destination NetworkPolicy; existing collector
network access suffices. No policy, RBAC or identity access changes are made.

## Limits and source contract

This is passive: cached blocks cannot prove an unused indexer works or that
search results/downloads succeed. No tests, searches, syncs or upstream indexer
requests are triggered. The indexer list can contain sensitive settings in
memory; responses are bounded and never logged or persisted. Indexer warnings
that do not create an active block remain outside the alert baseline.

The deployed manifest pins Prowlarr 2.3.5.5327. Its versioned
[IndexerStatusController](https://github.com/Prowlarr/Prowlarr/blob/v2.3.5.5327/src/Prowlarr.Api.V1/Indexers/IndexerStatusController.cs)
GET reads `GetBlockedProviders()`; status resource fields are `indexerId` and
`disabledTill`. Upstream
[IndexerResource](https://github.com/Prowlarr/Prowlarr/blob/develop/src/Prowlarr.Api.V1/Indexers/IndexerResource.cs)
and [HealthResource](https://github.com/Prowlarr/Prowlarr/blob/develop/src/Prowlarr.Api.V1/Health/HealthResource.cs)
define `enable` and `source`/`type`. Fixtures verify this contract; authenticated
production API behavior has not been live validated. No production credentials
were accessed.
