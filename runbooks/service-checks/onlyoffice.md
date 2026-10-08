# OnlyOffice and OpenCloud collaboration

The collector runs five bounded read-only metadata requests every 300 seconds,
with a 30-second service deadline and at most five seconds per request. Three
stable signals use the existing functional-check discovery and alert debounce:

- `Document server dependencies`: `/healthcheck` must return HTTP 200 and literal
  `true`. A native health failure catches dependency trouble reported by the
  document server; it does not independently test every worker or conversion.
- `Editor WOPI capabilities`: parse `/hosting/discovery` as bounded XML without
  DTD/entity declarations. Require `edit` actions for docx/xlsx/pptx, HTTP(S)
  editor URLs on configured expected hosts and `/hosting/wopi/` paths. Require
  `/hosting/capabilities` JSON with a nonempty version, boolean mobile flag and
  available `/lool/convert-to` capability. No conversion is submitted.
- `OpenCloud collaboration contract`: `/app/list` must register the OnlyOffice
  collaboration provider for all three office extensions. An anonymous GET of
  `/wopi/files/monitoring-nonexistent` must return 401 `Unauthorized`. This
  deliberately nonexistent identifier carries no access token and never opens
  user documents. A 404, login HTML, redirect or 200 is a broken contract.

No credentials, new RBAC or identity clients are required. OpenCloud currently
has no ingress NetworkPolicies, so this change adds no broad allow policy.
URLs and expected editor hosts are in `service_onlyoffice.json`. Responses are
size-capped; failures use fixed descriptions without response data or secrets.

This proves dependency self-reporting, editor capability advertisement,
collaboration registration and the anonymous WOPI authentication gate. It does
not prove authenticated CheckFileInfo/GetFile/PutFile, public ingress routing,
user permissions, rendering, save-back or real-time editing. Conversion and
editing failures not exposed by native health can remain undetected. Do not use
household document identifiers or copy application/admin credentials to deepen
this baseline.

The discovery semantics follow [OnlyOffice WOPI discovery](https://api.onlyoffice.com/docs/docs-api/using-wopi/wopi-discovery).
The chart's collaboration deployment itself uses `/app/list` provider
registration as its liveness contract. Live metadata on 2026-10-08 confirmed
OnlyOffice 9.4.0, the capability fields, all three edit formats, registry shape,
and 401 WOPI behavior. The full module passed against temporary read-only local
port-forwards; no document or conversion operation was performed. Collector
DNS/network access still needs normal rollout verification after foundation
PR #124 and this service PR deploy.

For an alert, inspect native document-server health, discovery/capabilities,
and OpenCloud's collaboration registration separately. Check collaboration
logs and its discovery connection before restarting anything. Re-run these
metadata checks after upgrades; do not suppress missing office capabilities as
an intentionally idle service.
