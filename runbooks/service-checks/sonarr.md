# Sonarr functional baseline

Depends on functional-monitoring foundation PR #124. Every 300 seconds, within
a 30-second worker deadline, the collector issues four bounded GET requests:
`/ping`, `/api/v3/system/status`, `/api/v3/health`, `/api/v3/rootfolder`.
Each request has at most five seconds and 256 KiB. No redirects are followed.
Contracts were checked against the [deployed Sonarr 4.0.17.2952 OpenAPI](https://github.com/Sonarr/Sonarr/blob/v4.0.17.2952/src/Sonarr.Api.V3/openapi.json);
Sonarr v4 uses API v3.

Three checks cover the application/authenticated system contract, native cached
health warnings/errors (including download-client and root-folder diagnostics),
and configured root accessibility. Notices do not alert. Empty health and root
lists pass; an empty library does not alert. Details contain counts and fixed
strings only, never health messages, filesystem paths, titles, or keys.
Missing credentials, HTTP denial, HTML login pages, malformed responses and
timeouts fail explicitly. The foundation applies its existing alert debounce
and freshness checks.

## Credential prerequisite

No credentials are copied or provisioned by this change. Sonarr exposes one
application API key with broad read/write authority; it cannot be restricted to
these GETs or to a monitoring account. The service-specific Secret key name
`sonarr_read_api_key` describes intended use, not an application-enforced scope.
No existing read-only facade was found in the media manifests. The implementation
targets the actual Sonarr Service and uses fixed GET paths exclusively. The
rollout prerequisite is operator acceptance of the native key's inherent broad
permissions and provisioning through the approved secret-management workflow.
No existing administrator credential is copied by this implementation. An
independent read-only facade is possible future hardening, not a required new
component of this baseline.

Provision the approved native key under `sonarr_read_api_key` in the existing
`zabbix/zabbix-functional-credentials` Secret using the approved secret-management
workflow, preserving other keys. It is mounted as an optional file; there is no
Secret API access. Remove collector access by deleting only this key, or rotate
Sonarr's application API key in Settings > General > Security when using direct
access (rotation also affects other integrations). Coordinate those integrations.
Until a credential path is approved/provisioned, the anonymous ping is evaluated
but authenticated checks explicitly report unavailable; they never claim health.

## Limits and diagnosis

Use Sonarr's System > Status UI to investigate warning/error counts; no message
content enters Zabbix. Health is Sonarr's cached native assessment; the collector
does not invoke client tests, searches, scans, downloads, imports, or mutations.
It does not prove a download/import can complete, indexer search quality, media
integrity, or end-to-end playback. Root GET may enumerate unmapped folder metadata
internally, bounded by the response cap; none is output. An oversized response
fails and needs review rather than increasing bounds automatically.

The media manifests have no ingress NetworkPolicy selecting arr-stack, and the
collector has no egress policy, so no network-access or RBAC expansion is needed.
There was no authenticated live validation; fixtures and render checks validate
the implementation pending the credential prerequisite.
