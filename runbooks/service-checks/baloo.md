# Baloo functional monitoring

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

`Baloo Kubernetes MCP read` negotiates MCP 2024-11-05, acknowledges
initialization, and reads `tools/list` from the existing private mcp-k8s Service.
It requires the Kubernetes server identity, tools capability, nonempty valid
object input schemas, unique names, and the deployed read metadata tools
`kubectl_get`, `kubectl_describe`, `kubectl_logs`, and `list_api_resources`.
Both JSON and SSE responses are supported. A future paginated catalog must
retain these required tools on its first page or update this bounded check.
After catalog validation it invokes only the explicitly read-only `kubectl_get`
with fixed arguments: `services/kubernetes`, namespace `default`, JSON output.
It asserts a v1 Service with the exact identity and API port 443, exercising the
adapter-to-Kubernetes API path and its existing RBAC. No resource metadata is
logged. It never starts a job, invokes a model, or sends a message.

The healthy interval is 15 minutes, with a 25-second worker deadline. Each
HTTP request is capped at five seconds and 256 KiB; session termination, when
a server supplies a session ID, is capped at three seconds and 4 KiB. The
foundation retains the configured failure polling interval and applies the existing Zabbix
execution-based debounce (cached failures do not count as new executions). Session IDs,
catalog contents, and server errors never appear in monitoring evidence.

No credential or RBAC change is needed: this endpoint already permits anonymous
MCP negotiation on its ClusterIP. Current Baloo manifests have no ingress policy
selecting mcp-k8s; the collector has unrestricted egress. This change adds no
Service, port, public exposure, or access to loopback listeners. If ingress is
restricted later, allow only namespace `zabbix`, pod label `app: collector`,
TCP 3000. Preserve mcp-k8s's Kubernetes read-only ServiceAccount RBAC.
The deployed catalog includes write-sounding tool names even with
`ALLOW_ONLY_NON_DESTRUCTIVE_TOOLS=true`; metadata presence is not proof of write
access or an authorization test. The monitor deliberately does not test writes.

## Existing coverage and explicit limits

The deployed OpenClaw `/app/docs/gateway/health.md` defines `/readyz` as startup,
drain, required agent-database admission, and configured channel deep readiness.
Its existing kubelet readiness probe already uses `/readyz`; infrastructure
monitoring observes that verdict. Native channel monitoring also owns channel
restart/recovery. Do not add a second channel connectivity alert or quiet-channel
traffic heuristic. `/healthz` alone is merely HTTP liveness. The independent
monitoring watchdog checks Zabbix/collector availability, not MCP catalogs.

Newjoy-organizer and image-tools have loopback `/health` probes on 18806/18807;
OLX-auth and court-case MCP have credential-bound loopback probes on
18803/18804; Vikunja tools and Zabbix MCP use 18802/18812. Paperless MCP has its
existing sidecar probes. Their pod/container readiness remains the baseline:
this PR does not expose these listeners or copy their credentials to Zabbix.
Image-api's existing health endpoint covers process readiness; dedicated
product-model, technical-plan, browser, Paperless, and other service checks
cover their own deterministic capabilities separately. Successful probes do
not prove organizer processing, image generation, court authentication, OLX
login, tool execution, upstream access, or message delivery. Those workflows
need a narrowly scoped existing health aggregator before deeper monitoring can
be added safely. There is no such shared aggregator in the current manifests.

The check catches broken transport, initialization, missing tools, malformed
schemas, and failed adapter-to-Kubernetes reads after an upgrade. It cannot prove
OpenClaw loaded an integration or that other tool operations succeed.
Investigate failures via local MCP diagnostics and existing pod/container
status; do not use an LLM conversation as a health test.

## Validation evidence

On 2026-10-08, read-only requests from the running OpenClaw container returned
ready=true and MCP initialization protocol 2024-11-05, server kubernetes 3.9.2,
an SSE catalog of 18 valid tools, including all four required tools. The fixed `kubectl_get` read also returned the expected Service; no writes
were invoked. This establishes the deployed contract, not collector-network
reachability after rollout. Unit tests cover JSON/SSE, negotiation/schema drift,
missing tools, auth errors, malformed replies, timeouts, failed/wrong Service
reads, redaction, and session
cleanup. Run `scripts/test zabbix` and render the Zabbix Kustomization before
review; verify a fresh healthy functional record after normal GitOps rollout.
