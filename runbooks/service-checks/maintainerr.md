# Maintainerr functional checks

Every five minutes the collector makes four bounded internal GET requests and
reports three checks, with the standard three-failure alert debounce:

- Database/media integration: `/api/health/ready` must report `status: ok` and
  `database: ok` (SQLite `SELECT 1`), and `/api/media-server` must return a
  nonempty machine ID and known version from the configured Emby integration.
- Radarr and Sonarr: `/api/servarr/{service}/1/profiles` must return a nonempty
  array of quality profiles with integer IDs and item arrays. These use
  Maintainerr's configured upstream clients, exercising its integration rather
  than a separate monitor's credentials. Maintainerr can swallow upstream
  failures into an empty list, so an empty response must fail.

Verified against deployed Maintainerr 3.15.2, image digest
`dcfd3f0862c31fced3a28ad2ae58c232a53d786b8c5b062cfc986570da8cb89f`:
compiled controllers, HealthService, ServarrService and Emby adapter under
`/opt/app/apps/server/dist/`. Read-only live queries returned valid Emby status
and six profiles from each configured Sonarr/Radarr instance. Instance IDs were
confirmed as 1 without printing connection settings or credentials.

No new credential or RBAC permission is required: this deployment authenticates
at its public ingress proxy and permits these internal API reads. Do not copy
upstream admin keys to Zabbix. Media currently has no NetworkPolicy restricting
Maintainerr, so no ingress widening is necessary. If internal authentication or
network isolation changes, requests fail visibly; add a narrow approved policy
or dedicated read identity rather than weakening the sign-in proxy.

The rollout prerequisite is foundation PR #124. Check the two instance IDs in
the JSON config if connections are replaced. Each expected installation must
retain at least one quality profile; an empty media library remains healthy.
Responses, library names, filesystem paths and exception messages are never
logged. Requests cap responses at 128 KiB and use five-second timeouts within
the 30-second service deadline.

This is read-only dependency coverage. It does not execute rules, trigger
cleanup, delete media, or assert scheduler activity: an idle scheduler is
normal. Maintainerr caches media status and upstream profiles/client settings;
a successful query can reflect cached state and does not prove immediate
upstream freshness or a fresh DB settings read. SQLite readiness is queried
separately to cover database reachability. Correct cleanup decisions and write
permissions cannot be proven by this baseline.
