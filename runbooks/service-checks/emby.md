# Emby safe public baseline

`Emby public server contract` anonymously reads `/emby/System/Info/Public` and
requires a nonempty identifier and numeric version. Existing workload and storage
monitoring continue independently. No playback, transcoding, media download,
user listing, library enumeration or credential access occurs.

`Emby scoped library query` remains explicitly deferred with severity1 and
`observation: deferred`, `notification: dashboard`. Public API success does not imply authenticated database,
library, media readability or playback success. The monitor receives no native
user session or dashboard API key. No household-library metadata access is
acceptable for this baseline; no account/token setup is required.

The shared framework samples at a 15-minute healthy cadence. Operational
failures require two real failed observations and a 30-minute grace;
recovery requires two real healthy observations. Cached snapshots are not new
observations. Failure retries follow the same bounded source-controlled cadence,
with shared jitter and overload limits. Deferred checks remain severity1,
observation deferred and dashboard-only; they never assert functional success.

Only the existing anonymous ClusterIP API path is used; no NetworkPolicy or RBAC
is widened. Requests retain a six-second maximum within the source-controlled
service deadline and a 64 KiB response cap; redirects are disabled by the shared
helper. Monitoring evidence contains fixed success/failure messages, never
server identity, returned metadata or exception strings. A server requiring auth
on public info reports an unavailable contract, never falls back to a token.

The foundation excludes Emby keys from its credential projection. If old keys
were separately provisioned, revoke/remove them through the normal private
operator workflow; this source change does not read or rotate credentials.

Validate offline with `python3 -m unittest discover -s scripts/tests -p test_service_emby.py` and `kubectl kustomize config/zabbix/manifests`.
Fixtures cover anonymous public schema, errors/redaction, forbidden credential
reads, legacy config and explicit deferred coverage. No production requests are
performed. This does not establish the live collector path before reviewed
GitOps rollout. The existing public API contract is documented at
https://dev.emby.media/reference/RestAPI/SystemService/getSystemInfoPublic.html.
