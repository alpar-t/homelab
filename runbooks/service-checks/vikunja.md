# Vikunja functional checks

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

Every 15 minutes, with a 20-second service deadline, the collector requests
`GET /api/v2/info` and `GET /api/v2/projects?page=1&per_page=1` internally.
The first validates a nonempty version, the configured public frontend URL,
and enabled Pocket ID provider. The second validates authenticated database
access and the v2 pagination envelope, accepting an empty account (including
`items: null`). Neither endpoint creates tasks, comments, or projects. Responses
are capped at 64 KiB and each request at six seconds or the remaining deadline.
Failures use the foundation's normal Zabbix alert debounce; project titles,
counts, bodies, URLs and credentials are never emitted in evidence.

## Credential prerequisite

Provision a dedicated Vikunja monitoring bot user, with no household project/team
membership, using an authorized operator account's bot-user UI/API. Give its API
token only `projects: [read_all]`, verified against the installed `/api/v2/routes`
permission catalog. Alternatively use a dedicated ordinary account with no
shared household projects. Do not reuse a household/admin or Baloo token. Set a
bounded expiry and arrange rotation before expiry. An empty account still
exercises authentication, permissions and the project/database query.

Store the token as key `vikunja_read_token` in the manually managed Secret
`zabbix/zabbix-functional-credentials`. Merge the key with existing service keys;
do not replace their Secret. For example, create a private token file, then:

```bash
kubectl -n zabbix create secret generic zabbix-functional-credentials \
  --from-file=vikunja_read_token=/private/path/vikunja-token \
  --dry-run=client -o json > /private/path/vikunja-secret.json
```

Use the generated file as input to the site's private secret-management workflow
while preserving existing keys; never commit or print it. The foundation mounts
this Secret read-only at `/credentials`, without Kubernetes Secret API access.
Revoke the token in Vikunja's API-token UI (or DELETE the token by ID), remove
its Secret key and rotate the private file. Missing tokens defer authenticated coverage; supplied expired/unauthorized tokens
fail the authenticated check explicitly; no credentials were provisioned by this
PR. No service ingress NetworkPolicy exists in the current source, and no new
RBAC, identity groups, or public exposure is required.

## Evidence and limits

Read-only live port-forward validation on 2026-10-08 confirmed v2.5.0 `/info`
and its Pocket ID configuration. Deployed `/api/v2/openapi.json` confirms the
project query parameters and `PaginatedProject` object fields (`items`, `page`,
`per_page`, `total`, `total_pages`), including nullable items. Authenticated live
validation awaits the dedicated credential. Source contracts:
[info](https://github.com/go-vikunja/vikunja/blob/v2.5.0/pkg/routes/api/v2/info.go),
[project reads](https://github.com/go-vikunja/vikunja/blob/v2.5.0/pkg/routes/api/v2/projects.go).

This baseline detects changed API contracts, missing sign-in configuration and
broken authenticated database reads. It does not prove interactive OIDC login,
task writes, attachments, reminders, or the separate Baloo task adapter. It does
not read household tasks or validate their contents. Public ingress remains
covered separately; these calls exercise the internal backend.

Missing monitoring credentials defer the authenticated portion at informational
severity with dashboard-only evidence; this is a coverage prerequisite, not an
application-outage page or a confirmed recovery. Public/dependency observations
continue independently. A supplied credential that is rejected remains a real
failed execution. No additional authority is accepted to expand coverage.
