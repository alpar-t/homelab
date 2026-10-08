# OpenCloud functional monitoring

The collector samples every five minutes with a 30-second worker deadline,
eight-second request limits and 32 KiB response caps. Foundation discovery and
three-failure debounce apply. The internal service origin exercises the backend independently of public edge
routing; requests never follow redirects. The chart explicitly sets PROXY_TLS=false
between ingress and OpenCloud, so this service uses HTTP port 9200.

`OpenCloud API contract` validates `/status.php`: installed OpenCloud, a nonempty
version and maintenance disabled. This is a protocol/version contract, not proof
of a logged-in session. `OpenCloud monitor storage metadata` authenticates using
an App Token and performs PROPFIND with Depth 0 against one explicitly selected
collection. It requires a single matching DAV response with successful collection
and nonempty ETag properties. HTTP 207 alone is insufficient. This exercises
authentication, routing and storage metadata lookup without enumerating children,
reading files or writing anything. Empty monitor folders are healthy.

## Rollout prerequisite and least privilege

Before rollout, create a dedicated Pocket ID monitoring identity with only the
existing OpenCloud user access group; do not grant administrator or space-manager
roles. Sign in once to provision it. Share an empty dedicated monitoring folder
with Viewer permission, without sharing household or Newjoy project folders.
The account may also have its own personal space: keep it empty. Create an
expiring OpenCloud App Token and copy the user UUID from account preferences.
App Tokens can access everything visible to their identity, so account/share
isolation is the permission boundary. Do not reuse Baloo or admin credentials.

Set `workspace_path` in `service_opencloud.json` to the exact URL path copied
from that monitoring folder's WebDAV info panel, preserving URL escaping and a
trailing slash (for example `/dav/spaces/<resource-id>/monitor/`). The configured
origin is `http://opencloud-opencloud.opencloud.svc.cluster.local:9200`; paths are source-controlled, never discovered
from a household listing. The default empty path deliberately reports unavailable
until provisioned. Verify the copied path with the deployed version; existing
`/remote.php/dav/spaces/` paths are also accepted.

Provision `opencloud-username` and `opencloud-app-token` keys in the manually
managed `zabbix/zabbix-functional-credentials` Secret using secure local files.
Merge the two keys into the existing Secret without replacing other services'
keys. Prepare a mode-0600 local JSON merge-patch file with the shape
`{"data":{"opencloud-username":"<base64 UUID>","opencloud-app-token":"<base64 token>"}}`
from the secure files, then apply it with:

```bash
kubectl -n zabbix patch secret zabbix-functional-credentials \
  --type=merge --patch-file=/secure/local/opencloud-credentials-patch.json
```

Create an empty `zabbix-functional-credentials` Secret first if this is the first
service to provision it. Remove the local patch securely after provisioning;
never put tokens in shell history, manifests, logs or PRs. The collector
mounts that Secret at `/credentials` and rereads it per sample. No Secret API read
permission, Kubernetes RBAC changes or new identity clients are needed. OpenCloud
currently has no ingress NetworkPolicy restriction requiring an exception.

Rotate by creating another expiring token, securely updating the two Secret keys,
verifying successful monitor metadata samples, then revoking the old token in
OpenCloud preferences. Revoke monitoring access by removing the token and folder
share; delete the dedicated identity when retiring the integration. Missing keys,
wrong path, expired credentials, redirects, malformed XML and denied metadata
all report failure with fixed redacted details. Response bodies, hrefs, ETags,
usernames and tokens never enter results.

## Failure meaning and limits

Use API-contract failure to investigate backend routing, upgrades or maintenance. Storage
metadata failure means the monitor workspace/credentials need checking or the
authentication/storage lookup failed; a running pod alone cannot establish this
path (see [PosixFS recovery](../restore-opencloud-posixfs-from-backup.md)).

This checks one isolated collection only. It does not prove household files are
present, downloads/uploads work, free capacity exists, full-text search works,
OIDC interactive login works or collaborative editing works. It neither lists
household files nor tests restoration/write permissions. Do not substitute an
admin account to increase coverage.

API references: [OpenCloud WebDAV protocol](https://docs.opencloud.eu/docs/dev/server/apis/http/webdav/)
and [user WebDAV/App Token setup](https://docs.opencloud.eu/docs/user/admin/web-dav/).
Access pattern follows [Baloo's OpenCloud integration](../baloo-opencloud-mcp.md)
with a separate, read-only monitoring identity.
