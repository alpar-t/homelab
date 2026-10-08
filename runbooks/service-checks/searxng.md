# SearXNG functional checks

Depends on the shared functional collector in foundation PR #124. Every 30 minutes,
`functional/searxng` makes one fixed General search for `Kubernetes` through the
internal service. It requires the echoed query and at least one nonempty titled
HTTP(S) link. This catches the previous HTTP-200/empty-results failure described in
[the maintenance runbook](../searxng-maintenance.md). Individual unavailable engines
are tolerated; rankings, counts and specific domains are not asserted. Empty,
malformed, unauthorized or timed-out responses fail closed. Details contain only
counts and generic failures, never result titles, URLs or upstream errors.

The MCP check initializes a short-lived protocol session, sends the initialized
notification, and reads `tools/list`, requiring `searxng_web_search` with an object
input schema. It supports JSON and SSE responses and closes its own session with
DELETE when the adapter supplies a session ID. It never calls a tool, browser,
LLM or user job. The deployed 1.14.0 adapter's `/app/dist/http-server.js` is the
protocol authority; its default transport requires initialization before listing.

Requests have 12-second search and 4-second MCP limits, bounded response sizes,
and the common 30-second deadline. Existing three-failure debounce applies. No
credentials or new Kubernetes RBAC are required. SearXNG and its MCP adapter have
no destination ingress NetworkPolicy; collector egress is unrestricted, so no
network access change is necessary. Public Pocket ID protection stays intact.
Deploy the collector ConfigMap through normal GitOps after the foundation merges.

Limitations: this proves a small General query and MCP catalog availability, not
all engines/categories, public sign-in, ranking quality or tool execution through
the adapter. Upstream blocking affecting all usable engines will intentionally
alert. Session cleanup is best effort and bounded; adapter expiry handles a lost
connection. It does not retain search results or create persistent artifacts.
