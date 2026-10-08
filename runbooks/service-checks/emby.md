# Emby functional checks

Every five minutes the functional collector checks public server-info JSON and a
restricted user library query. Requests take at most six seconds each, return at
most 64 KiB, and have a twenty-second overall deadline. Existing three-sample
Zabbix failure debounce applies. Empty libraries and idle playback pass.

`Emby public server contract` requires a version and server identifier from
`/emby/System/Info/Public`. `Emby scoped library query` requests at most one
nonrecursive item with images and user data disabled, validating Items and
TotalRecordCount. Missing credentials, revoked sessions, authorization failures,
malformed results, or backend errors fail explicitly. Details contain no server
name, library titles, paths, identifiers, token, or returned metadata.

## Credential prerequisite

Create a dedicated nonadministrator Emby user in the dashboard. Restrict its
library access to an empty monitor library (or a deliberately selected existing
library if broader metadata coverage is desired). Disable media playback,
transcoding, downloading, deletion, remote control, and library management where
available. Do not use an administrator account or dashboard API key: API keys
are integration credentials rather than a narrowly scoped user session.
Emby does not provide an HTTP-GET-only user token; account policy is the native
permission boundary, and this module makes only GET requests.

Authenticate this user once through Emby's documented
`POST /emby/Users/AuthenticateByName` workflow using a private provisioning
client with a fixed monitor device identifier. Store the resulting AccessToken
as `emby_monitor_token` and User.Id as `emby_monitor_user_id` in the manually
managed `zabbix/zabbix-functional-credentials` Secret. Use private local files
and `kubectl create secret generic ... --from-file=... --dry-run=client -o yaml`
merged with existing credential keys, then apply securely; never put tokens in
shell arguments, git, logs, or this runbook. Provisioning is an operator action,
not part of this periodic check. Revoke the session through the dashboard or
`POST /emby/Sessions/Logout`, remove/replace the two keys, and disable the account
when retiring monitoring. A revoked token intentionally alerts until replaced.

## Coverage and routing limits

The query exercises authentication and metadata/database browsing. An empty
monitor library does not prove household library permissions, filesystem media
readability, hardware acceleration, actual playback, or transcoding. No media
is played or downloaded, scans started, or jobs changed. Public API success alone
never substitutes for the authenticated check.

The collector uses the internal ClusterIP service, avoiding the LAN MetalLB
Local-routing constraint. This does not prove travel-router/VIP connectivity.
There is no media destination NetworkPolicy in source, so no ingress expansion
is needed. No extra Kubernetes RBAC or Secret API permission is added.

API contracts: [user authentication](https://dev.emby.media/doc/restapi/User-Authentication.html),
[public info](https://dev.emby.media/reference/RestAPI/SystemService/getSystemInfoPublic.html),
and [library browsing](https://dev.emby.media/doc/restapi/Browsing-the-Library.html).
The public-info reference labels authentication required; deployed anonymous
availability should be confirmed on rollout. A server requiring authentication
there raises an explicit public-contract failure rather than silently passing.
