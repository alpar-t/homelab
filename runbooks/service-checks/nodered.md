# Node-RED runtime monitoring

`Node-RED flow runtime` reads only `GET /flows/state` on the internal service
every five minutes (15-second worker deadline, HTTP timeout at most five seconds,
4 KiB response cap). It requires HTTP 200 and a JSON object whose `state` is
`start`. `stop`, `safe`, malformed responses, authentication failures, redirects,
timeouts and missing configured credentials fail. Foundation retries failures
after 60 seconds and preserves the existing three-sample alert debounce.

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

The [Admin API authentication documentation](https://nodered.org/docs/api/admin/oauth/)
describes scoped API tokens. If internal `adminAuth` is enabled, provision a
dedicated monitoring identity/token with only `flows.read` and add
`"token_key": "nodered-runtime-token"` to the JSON config. Store only that token
in the `nodered-runtime-token` key of the namespace-local
`zabbix/zabbix-functional-credentials` Secret through the approved private
credential workflow, preserving other service keys. Do not copy an editor/admin
token. Revoke the dedicated token/account to remove access; rotate the mounted
key with its replacement. Missing/revoked tokens fail visibly. The current
anonymous internal API requires no credential rollout prerequisite.

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
