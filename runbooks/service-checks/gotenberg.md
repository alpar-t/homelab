# Gotenberg functional monitoring

## Polling and incident confirmation

Poll every 3600 seconds (1 hour); shared failure grace is 7200 seconds.
A problem needs both the elapsed grace and at least two independent failed
executions; recovery needs two independent healthy executions. At this cadence
and grace, ordinary continuous failure normally requires three failed runs.
Minute snapshots never count as new observations, and failures keep the same
slow cadence. Scheduling is staggered. Referenced workload reboot/rescheduling
grace and maintenance preserve confirmed state without declaring recovery.
Persistent ordinary outages page; module-specific advisories stay on the dashboard.
See [the shared framework](../service-functional-checks.md) for startup,
unknown/deferred observations and queue freshness.

Every 1 hour the collector posts one small, fixed `index.html` multipart
file to the internal Gotenberg Chromium conversion API. The document includes
no JavaScript, external resources, URLs, or user data. It asserts HTTP 200,
`application/pdf`, PDF magic, an EOF marker, and a 512-byte to 256-KiB response.
The PDF exists only in memory and is discarded. Gotenberg manages its temporary
conversion files normally; no persistent monitoring artifacts are created.

The service deadline is 20 seconds; the request timeout is at most 15 seconds
and bounded by the remaining deadline. Oversized responses, timeouts, errors,
redirects, and malformed PDFs fail the stable `Gotenberg HTML to PDF` check.
The foundation uses the normal execution-based Zabbix debounce, so cached
failures may alert before three separate conversions have run.

Failure means the Chromium HTML conversion path is unusable from the collector,
even if `/health` and pod readiness remain healthy. Inspect Gotenberg logs,
Chromium startup, resource pressure, and Service connectivity. No credentials or
additional Kubernetes RBAC are needed. Paperless has no ingress NetworkPolicy
in the current manifests, and collector egress is unrestricted; if isolation
is introduced, allow only namespace `zabbix`, pod `app: collector`, TCP 3000
to pods `app: gotenberg`.

This does not verify rendered text/layout, LibreOffice conversion, PDF engines,
remote asset fetching, or Paperless ingestion. It does not inspect user documents
or prove that every document format can convert. There is one tiny disposable
conversion per interval, adding a small amount of Chromium work.

API contract: [Gotenberg HTML-to-PDF documentation](https://gotenberg.dev/docs/convert-with-chromium/convert-html-to-pdf).
The deployed image is Gotenberg 8 and accepts `files` with filename `index.html`
at `/forms/chromium/convert/html`.
