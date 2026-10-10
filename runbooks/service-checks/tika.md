# Tika functional checks

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

Every 30 minutes the Zabbix collector sends a fixed 52-byte plain-text body
with PUT `/tika` to both Paperless's `tika:9998` and OpenCloud's
`opencloud-tika:9998`. It requires HTTP 200, `text/plain`, and an exact decoded
text match after trimming surrounding whitespace. Each instance has its own
stable check under `functional/tika`; the usual execution-based debounce applies.
Requests take at most five seconds each, share a thirty-second worker deadline,
and cap responses at 4 KiB. No documents, credentials, files, or returned content
are retained or included in evidence. Request bodies are constructed in memory;
Tika may use its normal internal temporary-file handling.

This catches unreachable extraction servers, rejected requests, broken text
parsers, unexpected response formats, and empty or corrupt extraction. It does
not establish PDF, OCR, office-format, downstream ingestion, or large-document
performance. No user document is submitted and no conversion artifact is saved.

No credential or Kubernetes permission is required. Neither destination
namespace currently has a NetworkPolicy (live checked 2026-10-08); existing
collector egress permits these requests. If destination ingress is restricted
later, allow only namespace `zabbix`, pod label `app: collector`, TCP 9998 to
the Tika pods. Do not expose either server publicly.

On failure, inspect the indicated instance's application logs and resource
pressure, then repeat this fixed request. A healthy `/tika` GET greeting or
`/version` response alone does not prove extraction works.

Protocol reference: [Apache Tika Server documentation](https://cwiki.apache.org/confluence/spaces/TIKA/pages/148639291/TikaServer).
