# Functional monitoring self-review

Three independent Sol reviewers inspected all 50 PRs: security, performance,
and reporting. This review covers the proposed GitOps changes; it is not evidence
of production deployment or successful end-to-end authenticated workflows.

## Decisions

- Do not introduce write-capable application tokens or new access to browser and
  renderer control APIs. Explicitly defer those functional paths and keep safe
  anonymous or Kubernetes evidence. Project only vetted credential keys.
- Isolate Zabbix server/frontend egress to DNS, its database, the read-only collector,
  and the existing authenticated notification hook. Kubernetes telemetry RBAC remains
  read-only with no Secret reads or execution privileges.
- Run ordinary functional checks every 10–15 minutes, low-use metadata every
  30 minutes, and Chromium conversion/search hourly. Stagger startup, keep three
  workers, bound transport sizes/time, and do not accelerate retries during outages.
- Confirm failures and recoveries with independent executions. Cached snapshots
  do not increase counters. Preserve confirmed incidents over observer failures
  and collector restarts; allow startup, workload recovery and node reboot grace.
- Page on sustained user-facing failures. Partial capacity loss, historical
  diagnostics and unavailable optional coverage stay on the dashboard. There is
  no automatic digest. Existing infrastructure urgency remains separate.

The per-service JSON and [framework contract](service-functional-checks.md)
are authoritative for cadence, observation gates, workload dependencies and
notification routing. A service failure grace starts at its first failed execution,
not at the physical outage. Polling, queueing, Zabbix trigger confirmation and
notification delay add to detection latency. Slow cadence deliberately trades
speed for low load; two recovery observations also delay recovery notifications.

## Review coverage and policy

All three reviewers inspected every original PR head and re-reviewed the fixes.
The combined 49-service tree passes 367 monitoring/access-policy tests and the
rendered boundary regression: 19 read-only bindings, four projected keys, five
allowed and fifteen denied egress cases, four private-ingress denials, and six
adversarial permission/network mutations. These are offline checks, not production
rollout or delivery evidence.

| PR | Service | Security | Performance | Reporting | Interval | Failure grace |
| --- | --- | --- | --- | --- | --- | --- |
| [#123](https://github.com/alpar-t/homelab/pull/123) | gotenberg | reviewed | reviewed; 1 findings | reviewed | 60 min | 120 min |
| [#124](https://github.com/alpar-t/homelab/pull/124) | foundation | reviewed; 1 findings | reviewed; 3 findings | reviewed; 6 findings | shared | per service |
| [#125](https://github.com/alpar-t/homelab/pull/125) | pihole | reviewed | reviewed | reviewed | 10 min | 15 min |
| [#126](https://github.com/alpar-t/homelab/pull/126) | pocket-id | reviewed | reviewed | reviewed | 10 min | 15 min |
| [#127](https://github.com/alpar-t/homelab/pull/127) | vikunja | reviewed | reviewed | reviewed | 15 min | 30 min |
| [#128](https://github.com/alpar-t/homelab/pull/128) | paperless | reviewed | reviewed | reviewed | 15 min | 30 min |
| [#129](https://github.com/alpar-t/homelab/pull/129) | immich | reviewed | reviewed | reviewed | 15 min | 30 min |
| [#130](https://github.com/alpar-t/homelab/pull/130) | vaultwarden | reviewed | reviewed | reviewed | 15 min | 30 min |
| [#131](https://github.com/alpar-t/homelab/pull/131) | opencloud | reviewed; 1 findings | reviewed | reviewed; 1 findings | 15 min | 30 min |
| [#132](https://github.com/alpar-t/homelab/pull/132) | homeassistant | reviewed; 1 findings | reviewed | reviewed | 10 min | 15 min |
| [#133](https://github.com/alpar-t/homelab/pull/133) | frigate | reviewed | reviewed | reviewed; 1 findings | 10 min | 15 min |
| [#134](https://github.com/alpar-t/homelab/pull/134) | tandoor | reviewed | reviewed | reviewed | 15 min | 30 min |
| [#135](https://github.com/alpar-t/homelab/pull/135) | actual-budget | reviewed; 1 findings | reviewed | reviewed | 15 min | 30 min |
| [#136](https://github.com/alpar-t/homelab/pull/136) | trek | reviewed | reviewed | reviewed | 15 min | 30 min |
| [#137](https://github.com/alpar-t/homelab/pull/137) | roundcube | reviewed | reviewed | reviewed | 15 min | 30 min |
| [#138](https://github.com/alpar-t/homelab/pull/138) | sonarr | reviewed; 1 findings | reviewed | reviewed; 1 findings | 15 min | 30 min |
| [#139](https://github.com/alpar-t/homelab/pull/139) | prowlarr | reviewed; 1 findings | reviewed | reviewed; 1 findings | 15 min | 30 min |
| [#140](https://github.com/alpar-t/homelab/pull/140) | radarr | reviewed; 1 findings | reviewed | reviewed; 1 findings | 15 min | 30 min |
| [#141](https://github.com/alpar-t/homelab/pull/141) | qbittorrent | reviewed | reviewed | reviewed | 15 min | 30 min |
| [#142](https://github.com/alpar-t/homelab/pull/142) | emby | reviewed | reviewed | reviewed | 15 min | 30 min |
| [#143](https://github.com/alpar-t/homelab/pull/143) | portal | reviewed | reviewed | reviewed | 30 min | 60 min |
| [#144](https://github.com/alpar-t/homelab/pull/144) | searxng | reviewed | reviewed | reviewed | 60 min | 120 min |
| [#145](https://github.com/alpar-t/homelab/pull/145) | landing-page | reviewed | reviewed | reviewed | 30 min | 60 min |
| [#146](https://github.com/alpar-t/homelab/pull/146) | tika | reviewed | reviewed | reviewed | 30 min | 60 min |
| [#147](https://github.com/alpar-t/homelab/pull/147) | website-staging | reviewed | reviewed | reviewed | 30 min | 60 min |
| [#148](https://github.com/alpar-t/homelab/pull/148) | maintainerr | reviewed | reviewed | reviewed | 15 min | 30 min |
| [#149](https://github.com/alpar-t/homelab/pull/149) | onlyoffice | reviewed | reviewed | reviewed | 15 min | 30 min |
| [#150](https://github.com/alpar-t/homelab/pull/150) | otmonitor | reviewed | reviewed | reviewed | 10 min | 15 min |
| [#151](https://github.com/alpar-t/homelab/pull/151) | stalwart-mail | reviewed | reviewed | reviewed | 15 min | 30 min |
| [#152](https://github.com/alpar-t/homelab/pull/152) | nodered | reviewed | reviewed | reviewed | 15 min | 30 min |
| [#153](https://github.com/alpar-t/homelab/pull/153) | baloo | reviewed | reviewed | reviewed | 15 min | 30 min |
| [#154](https://github.com/alpar-t/homelab/pull/154) | pinchtab | reviewed; 1 findings | reviewed | reviewed; 1 findings | 15 min | 30 min |
| [#155](https://github.com/alpar-t/homelab/pull/155) | omada | reviewed | reviewed | reviewed | 15 min | 30 min |
| [#156](https://github.com/alpar-t/homelab/pull/156) | whisper | reviewed | reviewed | reviewed | 30 min | 60 min |
| [#157](https://github.com/alpar-t/homelab/pull/157) | product-models | reviewed; 1 findings | reviewed | reviewed | 15 min | 30 min |
| [#158](https://github.com/alpar-t/homelab/pull/158) | technical-plans | reviewed | reviewed | reviewed | 30 min | 60 min |
| [#159](https://github.com/alpar-t/homelab/pull/159) | ingress-nginx | reviewed | reviewed | reviewed | 10 min | 15 min |
| [#160](https://github.com/alpar-t/homelab/pull/160) | interior-designer | reviewed | reviewed | reviewed | 30 min | 60 min |
| [#161](https://github.com/alpar-t/homelab/pull/161) | cloudflare-tunnel | reviewed | reviewed | reviewed; 1 findings | 10 min | 15 min |
| [#162](https://github.com/alpar-t/homelab/pull/162) | argocd | reviewed | reviewed | reviewed | 10 min | 15 min |
| [#163](https://github.com/alpar-t/homelab/pull/163) | metallb | reviewed | reviewed; 1 findings | reviewed | 10 min | 15 min |
| [#164](https://github.com/alpar-t/homelab/pull/164) | longhorn | reviewed | reviewed | reviewed | 15 min | 30 min |
| [#165](https://github.com/alpar-t/homelab/pull/165) | wireguard | reviewed | reviewed | reviewed | 10 min | 15 min |
| [#166](https://github.com/alpar-t/homelab/pull/166) | velero | reviewed | reviewed | reviewed | 10 min | 15 min |
| [#167](https://github.com/alpar-t/homelab/pull/167) | coredns | reviewed | reviewed | reviewed | 10 min | 15 min |
| [#168](https://github.com/alpar-t/homelab/pull/168) | cnpg | reviewed | reviewed; 2 findings | reviewed; 1 findings | 15 min | 30 min |
| [#169](https://github.com/alpar-t/homelab/pull/169) | metrics-server | reviewed | reviewed | reviewed; 1 findings | 10 min | 15 min |
| [#170](https://github.com/alpar-t/homelab/pull/170) | github-runners | reviewed | reviewed | reviewed; 1 findings | 15 min | 30 min |
| [#171](https://github.com/alpar-t/homelab/pull/171) | zabbix | reviewed | reviewed | reviewed | 15 min | 30 min |
| [#172](https://github.com/alpar-t/homelab/pull/172) | platform-controllers | reviewed | reviewed | reviewed | 10 min | 15 min |

## Validation commands

Run `scripts/test zabbix access-policy` for functional/state-machine, transport,
credential-canary and access-policy fixtures. Then run
`python3 scripts/test-monitoring-security.py --root . --expected-services 49 --self-test`
in the combined 49-service tree. The latter renders manifests locally with kubectl
and PyYAML; it makes no Kubernetes API requests. Omit `--expected-services` for
foundation-only or an individual service PR. Its negative fixtures reject added
mutation/Secret/exec access, broadened egress and additive renderer ingress.

Approximate functional-page windows for continuous failures, including normal
poll phase and the existing snapshot/action delay, are 32–42 minutes for
10-minute checks, 42–57 minutes for 15-minute checks, 72–102 minutes for
30-minute checks and 132–192 minutes for hourly checks. Queueing, module-specific
graces and parent recovery can add time. Existing infrastructure failures retain
their faster independent policy. These are policy estimates, not measured delivery
latencies; notification-path verification remains a rollout gate.

Kubernetes API/log redirects are refused before credentials can leave the
authorized origin. Chunked response framing is covered by elapsed read budgets.
Raw Pod termination messages, storage event messages, Longhorn condition text and
CNPG condition messages are excluded from new evidence. Legacy cached Pod details
are sanitized on replay while preserving incident state. This review does not
purge previously stored Zabbix history or assert that it contained a real secret.

## Rollout gate

Deploy the foundation by itself first. It adds the discovery fields and egress
boundary without registering the 49 service modules. Verify fresh snapshots,
database access and the existing notification hook path, then reconcile the
reviewed Zabbix prototypes **and notification actions** with the bootstrap helper
(`--apply --enable-alerts`) during the authorized rollout. A plain `--apply` does
not update the action filters. Confirm informational coverage prototypes and the
`notification=dashboard` exclusion before merging service PRs. Validate discovered
expressions and discovery errors, not only a successful bootstrap response.

Then retarget and merge service PRs in small groups, observing one full cadence
plus the configured confirmation/recovery windows. No credentials or application
control access should be broadened to turn deferred coverage green. Keep the
existing infrastructure notifications operating throughout the rollout.

## Coverage limits and residual risk

Anonymous metadata/readiness cannot prove authenticated user workflows. Home
Assistant actuator/integration checks, native arr administrative diagnostics,
OpenCloud personal-space access, budget sessions, browser profiles, renderer
execution, Paperless document queries and Emby authenticated library access remain deliberately deferred.
Missing approved read-only credentials are visible coverage gaps. Do not solve
those gaps by supplying administrator, household or write-capable tokens.

Some existing internal services already permit unauthenticated mutations. These
PRs do not grant new access to those endpoints, but a compromised collector still
inherits its existing network reachability; this is not a claim that the cluster's
pre-existing network security is complete. Zabbix's network boundary is narrower
than the collector's. NetworkPolicy enforcement and the four allowed Zabbix flows
need verification during controlled rollout.

The collector is in the monitored cluster. Total cluster, uplink or notification
channel loss still needs an independent outside-in monitor. No live faults,
synthetic notifications, household mutations, model calls or production renders
were introduced by this review.
