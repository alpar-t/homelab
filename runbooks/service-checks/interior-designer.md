# Interior Designer Open WebUI functional baseline

## Polling and incident confirmation

Poll every 1800 seconds (30 minutes); shared failure grace is 3600 seconds.
A problem needs both the elapsed grace and at least two independent failed
executions; recovery needs two independent healthy executions. At this cadence
and grace, ordinary continuous failure normally requires three failed runs.
Minute snapshots never count as new observations, and failures keep the same
slow cadence. Scheduling is staggered. Referenced workload reboot/rescheduling
grace and maintenance preserve confirmed state without declaring recovery.
Persistent ordinary outages page; module-specific advisories stay on the dashboard.
See [the shared framework](../service-functional-checks.md) for startup,
unknown/deferred observations and queue freshness.

Every 1800 seconds, the collector makes five anonymous bounded GET requests to
`interior-designer.baloo.svc.cluster.local:8080`, with a 30-second execution
budget. Failure retries and execution-based alert behavior follow
[the shared framework](../service-functional-checks.md).

`Interior Designer backend contract` compares `/api/version` and `/api/config`
version strings, requires application status, and verifies the deployed Pocket
ID provider, authentication enabled, password sign-in/signup disabled, and no
first-user onboarding. The config handler reads Users and Config from the
application database, so this detects database/API faults and unusable sign-in
configuration beyond `/health`. Versions are compared, not pinned, to allow
normal upgrades. Verified against deployed Open WebUI 0.11.3 main.py routes and
actual anonymous config on 2026-10-08.

`Interior Designer frontend assets` parses `/` for the first-party Svelte start
and app entry modules and downloads both. It requires JavaScript content type,
nontrivial bytes and import/export syntax, rejecting an HTTP-200 HTML SPA
fallback. Requests never follow redirects or external asset references.

No credential, new RBAC, or NetworkPolicy changes are required: this deployment
has no selecting ingress NetworkPolicy, and the collector has unrestricted
egress. No model completion, message, upload, image generation or user job is
submitted. Response content is never emitted as evidence.

## Limits and response

This baseline proves anonymous application/database configuration and delivery
of its entry modules. It does not prove Pocket ID login, authenticated model
catalog access, OpenClaw provider connectivity, inference, WebSockets, all lazy
frontend chunks, or external preview/image tools. Those workflows require
separate integration checks or user activity; a login page alone is not evidence
that they work. The progress-filter Function is installed by a PVC-backed sync
sidecar; no anonymous read-only route exposes its active/installed state.
Therefore this check makes no progress-filter health claim and does not read
chat contents or reuse administrative credentials to inspect it.

On backend failure, inspect application database/API errors and OIDC settings.
On frontend failure, check image/build and static routing. Restore valid service
configuration through GitOps; do not trigger inference as a monitoring test.
