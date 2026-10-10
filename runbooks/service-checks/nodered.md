# Node-RED runtime monitoring

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

`Node-RED flow runtime` reads only `GET /flows/state` on the internal service
every 15 minutes (15-second worker deadline, HTTP timeout at most five seconds,
4 KiB response cap). It requires HTTP 200 and a JSON object whose `state` is
`start`. `stop`, `safe`, malformed responses, authentication failures, redirects,
timeouts fail. The framework retains the configured polling interval and preserves the existing execution-based alert debounce.

This catches an editor that remains reachable while the automation runtime has
been stopped or started in safe mode. Idle flows are healthy. Never POST runtime
state, deploy flows, inject events or call actuator endpoints for validation.

## API and access evidence

On 2026-10-08, deployed Node-RED 4.1.8 source registered GET `/flows/state`
with `flows.read` permission regardless of `runtimeState.enabled`. The setting
controls the POST stop/start API, not this GET. The handler returns only
`{state: runtime.flows.state()}`; runtime source uses `start`, `stop`, and `safe`.
A read-only live request from both the runtime and the deployed Zabbix collector
returned HTTP 200 and `start`. Effective settings had
no `adminAuth`; Pocket ID protects the public editor through oauth2-proxy.
The monitor uses the existing private ClusterIP API and changes no public
authentication or Kubernetes permissions. Node-RED currently has no ingress
NetworkPolicy; no additional network permission is needed.

No credential is mounted or used by this check. If internal `adminAuth` is
enabled, review the deployed version's read-only permission model before adding
an identity. The current anonymous internal API requires no credential rollout
prerequisite. This baseline has no optional bearer credential configuration. Existing unauthenticated internal access is a residual risk of the
service itself, not a new permission granted by this monitoring PR.

## Limits and investigation

This is a passive runtime-state baseline. It does not fetch `/flows` (which
contains private node configuration), prove any particular flow exists, count
nodes, inspect credentials or execute flows. `start` alone cannot prove all
nodes loaded successfully or individual external dependencies connected; missing
node types and node-specific failures can coexist with runtime state `start`.
There is no safe aggregate dependency status in this endpoint. Check Node-RED's
editor/runtime logs privately when failures occur, and retain existing workload
readiness checks. Do not claim this proves Home Assistant/device connectivity,
the public SSO login, or end-to-end automation execution.

Validate with `scripts/test zabbix` and
`kubectl kustomize config/zabbix/manifests`. Live validation may GET only
`/flows/state` from the collector network and print its status/state, never
arbitrary response bodies, flow definitions or credentials.
