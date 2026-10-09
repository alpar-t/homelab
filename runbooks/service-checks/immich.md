# Immich functional checks

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

The Zabbix collector runs three read-only checks every 15 minutes, with a 30-second worker deadline and the existing execution-based alert debounce. Requests have five-second timeouts and 16 KiB response limits. Redis calls have four-second timeouts and the same response cap. No response bodies, counts, credentials or personal records appear in results.

- **Public API configuration:** `/api/server/version` has nonnegative integer version components; `/api/server/config` reports initialized, onboarded and outside maintenance mode. These are semantic API checks, not proof of sign-in. Schedule maintenance downtime in Zabbix when intentionally enabling maintenance mode.
- **Authenticated asset statistics:** `/api/assets/statistics` validates nonnegative integer image/video/total fields and their consistency. This exercises scoped API authentication and a database metadata query. Empty libraries pass. Missing credentials defer authenticated coverage; rejected supplied credentials, incompatible schema and unavailable backend fail explicitly.
- **Redis dependency:** `INFO persistence` parses bounded RESP bulk framing and requires loading complete, last RDB background save healthy and last AOF write healthy. This detects dependency startup or persistence failures even if Redis accepts connections. It performs no writes and does not inspect queues, keys or assets.

## Credential prerequisite

Create a dedicated **non-admin** Immich monitoring user with no household albums/shared assets. In that user's account settings, create an API key named `zabbix-monitor` with **only `asset.statistics`** permission. The account may remain empty: its statistics query still exercises the application database. Do not use an administrator key or `server.statistics`, which requires admin access and returns per-user information.

Store the key as `immich-api-key` in the optional-mounted `zabbix/zabbix-functional-credentials` Secret. For example, place the value in a temporary file with mode 0600 and merge that key into the existing Secret using your normal secret-management procedure; avoid command arguments containing the value and preserve other service keys. For an existing Secret, generate a protected JSON patch file containing only `{"data":{"immich-api-key":"<base64 of key>"}}` and run `kubectl -n zabbix patch secret zabbix-functional-credentials --type merge --patch-file /path/to/protected-patch.json`. For a new Secret, use `kubectl -n zabbix create secret generic zabbix-functional-credentials --from-file=immich-api-key=/path/to/protected-key-file`. Remove the local key and patch files after provisioning. These commands keep the token out of shell arguments and preserve other keys when patching.

Provision to enable authenticated coverage: an absent key leaves that coverage informational and deferred. Revoke the key in Immich and remove/replace the Secret key to rotate or retire access. Never commit the token.

Immich currently has no ingress NetworkPolicy; the collector can reach the server and Redis service directly. No RBAC, identity clients or network access policies are widened by this change. Redis presently has no authentication; if that changes, this check must be adapted with a dedicated restricted Redis identity rather than exposing an admin credential.

## Evidence and limits

Read-only live checks on 2026-10-08 confirmed Immich 3.1.0, HTTP 200 for configuration with the expected field names, and a Redis persistence response with loading zero. No monitoring user/key was provisioned and authenticated statistics were not live validated. Fixtures verify healthy empty statistics, rejected/missing credentials, malformed schemas, bounded fragmented Redis responses, persistence failures and timeouts. The production collector path remains untested until rollout.

API contracts were checked against the deployed tag's official source: [server controller](https://github.com/immich-app/immich/blob/v3.1.0/server/src/controllers/server.controller.ts), [asset controller](https://github.com/immich-app/immich/blob/v3.1.0/server/src/controllers/asset.controller.ts), and [asset DTO](https://github.com/immich-app/immich/blob/v3.1.0/server/src/dtos/asset.dto.ts).

This baseline does not prove household library mounts, downloads, uploads, thumbnail generation, queue progress, vector search, OIDC sign-in, or GPU/ML inference. The [ML service source](https://github.com/immich-app/immich/blob/v3.1.0/machine-learning/immich_ml/main.py) exposes only identity/ping GET endpoints; actual model validation requires `/predict`. Existing ML readiness covers ping. No duplicate ping check or prediction is added; the functional dependency signal here is Redis. No rescans, jobs or media requests occur.

Missing monitoring credentials defer the authenticated portion at informational
severity with dashboard-only evidence; this is a coverage prerequisite, not an
application-outage page or a confirmed recovery. Public/dependency observations
continue independently. A supplied credential that is rejected remains a real
failed execution. No additional authority is accepted to expand coverage.
