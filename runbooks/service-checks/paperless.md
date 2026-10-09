# Paperless functional checks

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

The collector performs only a bounded Redis RESP PING using the existing private
broker listener. Require exactly PONG; no queue, document or task data is read.
Four-second socket limits remain within the shared service deadline. This proves
broker protocol availability, not Celery consumption, OCR, document ingestion,
filesystem access or household archive authentication. Existing workload/CNPG
readiness and Tika/Gotenberg functional checks continue independently.

## Document coverage and credential boundary

`Paperless document API` is deliberately deferred with severity1,
`observation: deferred`, `notification: dashboard`. No document token is mounted,
read or provisioned, and no anonymous document endpoint is invented.

A non-staff user with native `documents.view_document` permission can still read
ownerless documents. A routine `fields=id` request only limits that response; it
does not prevent a stolen DRF token from requesting ownerless household document
bodies, downloads or metadata. An otherwise isolated account is therefore not a
sufficient no-household-data boundary. Keep authenticated document coverage
explicitly deferred until the native permission model can enforce that boundary.
Do not supply an administrator or existing Baloo token to close this gap.

The foundation excludes `paperless_monitor_token` from its credential projection.
Any previously provisioned monitoring token should be revoked/removed by an
authorized operator through the existing private workflow; no production token
is read, provisioned or rotated by this change. No RBAC or NetworkPolicy is added.
Existing unauthenticated Redis network reachability predates the monitoring PR.

## Validation and limits

Run `python3 -m unittest discover -s scripts/tests -p test_service_paperless.py`
and `kubectl kustomize config/zabbix/manifests`. Fixtures prove document coverage
cannot trigger credential/HTTP reads even with legacy config, while fragmented
PONG, malformed/error/oversized replies and timeouts exercise the remaining broker
check. Errors emit fixed diagnostics, never broker data or exception strings.
No production requests or document operations are part of these tests.

This baseline does not prove scanner FTP, OCR workers, filesystem consumption,
mail ingestion, search index, user sign-in or restores. An idle archive is healthy;
absence of document activity never establishes an ingestion failure. The previous
live Redis PING was from the application pod and does not validate the final
collector path before a reviewed GitOps rollout.
