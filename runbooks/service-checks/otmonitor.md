# OTmonitor functional monitoring

The collector observes existing `log-tailer` output every five minutes. The
native web data endpoint is disabled (`web enable false`); port 80 exposes the
VNC GUI and does not establish boiler communication. No endpoint, exporter,
heating setting, gateway command, or MQTT publication is added.

`OTmonitor live OpenTherm exchanges` requires gateway `R` Read-Data status
(ID 0), boiler `B` Read-Ack status (ID 0), and boiler Read-Ack water temperature
(ID 25) within 180 seconds. These frames were verified in deployed logs on
2026-10-08. Constant temperatures, zero status flags, a cold/idle boiler and
night heating modes all pass; freshness means new protocol messages, never
changing measurements. Missing replies detect a disconnected/noncommunicating
bridge even while the VNC GUI remains available. Message values and raw logs
never appear in check evidence.

Both Kubernetes log timestamps and OTmonitor's local message clock must be
recent. The configured Europe/Bucharest timezone matches the deployment.
Midnight is handled by selecting the nearest source day to log ingestion.
The application's daily log format omits its date: replay of a historical file
at exactly the same time of day cannot be reliably distinguished. This is a
passive communication baseline, not proof of thermostat-origin traffic (the
gateway can generate requests), actual heating, correct setpoints, MQTT delivery,
or fault-free boiler operation. Read acknowledgements for other measurements
alone do not satisfy the check.

The query selects one running, nonterminating pod and reads at most 600 lines /
128 KiB from the previous three minutes. Kubernetes calls use the foundation's
15-second timeout; each is started only with at least 15 seconds left in the
30-second service deadline. Missing/ambiguous source, malformed or stale frames,
permission errors, truncation, and timeouts fail visibly. The foundation retries
failed checks every minute and the existing three-failure alert debounce applies.

No credentials or network ingress changes are needed. Existing pod GET access
is reused; a namespace-local Role adds only `get` on `pods/log` in `otmonitor`
to the Zabbix collector. Kubernetes RBAC cannot restrict log reads to a container,
so the collector technically can read other containers' logs in this namespace;
implementation reads only `log-tailer`. Revoke by removing that RoleBinding.
On rollout, confirm new source/Role files are synced and a fresh check is healthy.
Investigate missing exchanges through the gateway connection and log sidecar;
do not change heating commands as part of monitoring verification.

Validation: `scripts/test zabbix` and
`kubectl kustomize config/zabbix/manifests`. Tests cover idle values, one-way
traffic, stale/replayed/malformed/future logs, midnight, denied reads, missing pods
and deadline handling. Safe live verification reads existing logs only; no
outage is induced.
