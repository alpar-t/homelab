# Omada functional bootstrap

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

Every 15 minutes, the collector reads the anonymous `/api/info` endpoint,
with an five-second request timeout, 15-second worker deadline and 16 KiB
response limit. It requires HTTP 200, integer `errorCode=0`, a numeric controller
version, API version 3, and both `configured=true` and `registeredRoot=true`.
This catches backend errors, HTML login/redirect responses, missing controller
configuration after storage loss and incompatible API changes despite a working
web root. Failed executions use the configured cadence and shared confirmation policy.

The deployed 6.1.0.19 controller was checked through a local port-forward on
2026-10-08 and returned this contract. The ClusterIP Service exposes the existing
HTTP 8088 listener for this credential-free bootstrap only; no Ingress is added.
The controller already uses hostNetwork and has no destination NetworkPolicy;
this change adds no broad allow rule. HTTP is used because the controller's
internal HTTPS listener has its own certificate and the common HTTP context
validates TLS. Never send credentials over this endpoint.

No credentials or additional RBAC are needed. No login sessions, network/device
changes or upstream calls occur. Response values (including controller identity)
are never emitted. Errors produce fixed safe summaries.

This proves the configured controller backend serves its bootstrap API. It does
not prove authentication, adoption, device connectivity, radio health or network
traffic. Offline devices and an idle controller never cause an alert here.
Adopted-device checks remain deferred until an explicitly provisioned monitor
identity with verified read-only/site-restricted API access is available. Do not
copy an administrator password or broad API client into monitoring. Before adding
that coverage, verify the deployed API, permissions and offline expectations;
only report aggregate counts, never device names, MAC addresses or client data.

Investigate a failure by checking controller startup/storage and reading the
anonymous API locally; verify configuration remains present before taking action.
An API version change requires reviewing the actual response before updating the
expected version. Do not suppress contract errors by accepting arbitrary JSON.
