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

Every 900 seconds, the collector performs a bounded authenticated GET of
`/api/documents/?page_size=1&fields=id` and a Redis RESP PING. The first validates
authentication, document permissions, pagination and a real PostgreSQL query;
empty permitted archives pass. Only one numeric ID can be returned, and neither
IDs nor counts appear in monitoring output. Unexpected fields fail safely.
Redis must return exactly PONG; no queue or document data is read. Each HTTP
request has an eight-second limit and 16 KiB cap; Redis has four-second socket
limits within the shared thirty-second deadline. Foundation alert debounce applies.

A failed API check means a rejected/revoked supplied credential, denied permissions,
network/backend failure, or an incompatible response. A failed Redis check
means the ingestion broker cannot answer its protocol. Neither check uploads,
reprocesses, acknowledges tasks, sends mail, or changes stored data.

## Required credential before rollout

Provision a dedicated `zabbix-monitor` Paperless user, active, non-staff and
non-superuser, with an unusable password. Give only the global
`documents.view_document` permission. Do not grant archive-wide object access,
write permissions or staff access, and do not copy the existing Baloo/admin
token. Paperless permits ownerless documents by design, but the request selects
only IDs. The monitor does not need a real document: an empty result still
exercises the database and permission filter.

An authorized administrator can provision through `manage.py shell` using this
code (capture stdout in a mode-0600 file; never display it):

```python
import sys
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.authtoken.models import Token
if get_user_model().objects.filter(username="zabbix-monitor").exists():
    raise RuntimeError("Account already exists; verify ownership before separate rotation")
user = get_user_model().objects.create(username="zabbix-monitor")
user.is_active, user.is_staff, user.is_superuser = True, False, False
user.set_unusable_password()
user.save()
user.user_permissions.set(Permission.objects.filter(
    content_type__app_label="documents", codename="view_document"))
token, _ = Token.objects.get_or_create(user=user)
sys.stdout.write(token.key)
```

Merge the captured value as key `paperless_monitor_token` into the optional
`zabbix/zabbix-functional-credentials` Secret, preserving other services' keys.
Use the repository's secure Secret-management procedure; never commit the token
or read the Secret through collector RBAC. The foundation mounts it at
`/credentials/paperless_monitor_token`. Absent credentials defer authenticated coverage; rejected credentials fail explicitly.
For rotation delete/recreate this user's DRF Token and update that key. For
revocation deactivate the user or delete its token; the next sample must fail.
These setup operations require separate administrator authorization and were
not executed as part of implementation.

## Coverage and evidence

The deployed manifest pins Paperless 2.20.15. Its
[versioned DocumentViewSet source](https://github.com/paperless-ngx/paperless-ngx/blob/v2.20.15/src/documents/views.py)
supports `fields`; its combined system status endpoint requires `is_staff`.
The check deliberately avoids staff credentials. Redis has no password in the
current manifest. Source and live namespace inventory show no Paperless ingress
NetworkPolicy, so no new broad access rule is needed. Collector egress is not
restricted by its current policies.

This does not prove OCR workers, filesystem consumption, scanner FTP uploads,
email ingestion, search index or user sign-in work. Redis PING proves broker
protocol availability, not Celery consumption. Existing infrastructure checks
cover pod readiness and database health; Tika/Gotenberg have separate functional
checks. Do not infer stuck ingestion from an idle archive or add activity-age
alerts without an explicit expected workload. No authenticated live API probe
was run because a dedicated monitoring token has not been provisioned.

Live Redis PING from the Paperless application pod returned PONG during
implementation. This validates the configured broker endpoint, but does not
prove the collector network path; validate that path after rollout.

Missing monitoring credentials defer the authenticated portion at informational
severity with dashboard-only evidence; this is a coverage prerequisite, not an
application-outage page or a confirmed recovery. Public/dependency observations
continue independently. A supplied credential that is rejected remains a real
failed execution. No additional authority is accepted to expand coverage.
