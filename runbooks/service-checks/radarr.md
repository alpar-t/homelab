# Radarr functional baseline

Depends on functional-monitoring foundation PR #124. Every five minutes the
collector reads `GET /api/v3/health` and `GET /api/v3/rootfolder` using the
native Radarr API. Each request allows five seconds and 128 KiB;
the worker deadline is twenty seconds. Existing three-failure debounce applies.

The health assertion validates the native health array and alerts for warnings
or errors, including Radarr's cached download-client and root-folder checks.
The storage assertion validates Boolean `accessible` fields and alerts for
inaccessible configured roots. Empty arrays and empty libraries are healthy.
HTTP failures, redirects, malformed responses, missing credentials and request
failures report unavailable. Details contain counts only, never titles, paths,
messages, URLs or API keys. This does not invoke searches, scans, client tests,
commands or movie operations. Native checks are passive/cached; this cannot
prove a future download or successful movie import. Notices do not alert.

## Required rollout prerequisite

Radarr 6.1.1 has an application API key with administrative write permissions;
there is no dedicated read-only API-key scope. A different key name or Secret
does not reduce that authority. Monitoring sends GET requests only, but a
compromised collector holding this key could modify Radarr. Before merging or
rollout, the owner must explicitly accept this inherent application limitation
and manually provision `radarr-monitor-api-key` in the optional
`zabbix/zabbix-functional-credentials` Secret. No production key is read, copied
or provisioned by this change, and no existing Baloo credential is reused.
Missing credentials intentionally report unavailable.

Obtain the application key privately through Radarr's settings, store it in a
protected local file, and merge only the `radarr-monitor-api-key` key into the
existing Secret without replacing other service keys. For an initially absent
Secret use `kubectl -n zabbix create secret generic zabbix-functional-credentials
--from-file=radarr-monitor-api-key=/protected/path/key`. Never put the key in
command arguments, logs, or source control. The collector rereads each cycle.
Radarr key rotation also requires updating every other integration using that
application key; deleting the collector Secret key revokes collector access
without rotating the application. A separately operated GET-only facade is a
future alternative if accepting this residual write authority is unsuitable;
none exists or is provisioned by this PR.

The internal target is the deployed Radarr Service on port 7878. Media manifests
have no ingress isolation NetworkPolicy, so no additional network grant or RBAC
is required. Native health covers cached download-client connectivity failures;
this check avoids `/downloadclient`, which exposes connection configuration.

API schema references: [official health resource](https://github.com/Radarr/Radarr/blob/develop/src/Radarr.Api.V3/Health/HealthResource.cs)
and [root folder resource](https://github.com/Radarr/Radarr/blob/develop/src/Radarr.Api.V3/RootFolders/RootFolderResource.cs).
These upstream resources confirm fields. Fixtures were used for validation,
not authenticated live production calls; verify installed response shapes when
manually provisioning credentials.
