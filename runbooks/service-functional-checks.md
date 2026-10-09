# Service functional checks

Add `config/zabbix/manifests/assets/service_<slug>.py` and adjacent JSON to the
collector ConfigMap. Each module exports `run(ctx, config)` with at most128
unique stable, service-prefixed rows. Never include credentials, response bodies,
user data or exception messages in evidence. Standard-library helpers provide
bounded read-only HTTP and the collector's restricted Kubernetes client.

```python
def run(ctx, config):
    response = ctx.http(config['url'])
    return [ctx.check('Example catalog', response.status != 200,
                      'catalog contract valid or unavailable')]
```

`ctx.check(name, bad, detail, severity=3, observation='known', workloads=None,
notification=None)` produces a safe observation. `known` means a real completed
probe supplies service evidence. Use `unknown` during expected maintenance,
startup grace, or when a dependency cannot be observed; its supplied Boolean is
ignored and it cannot recover an existing incident. A module/API failure raises
one shared telemetry problem; retain unknown dependent rows rather than inventing
several application failures. If a module handles its own API failure, emit one
known telemetry failure row and unknown dependent service rows (Frigate example).

`ctx.http(url, method='GET', headers=None, data=None, timeout=8,
max_bytes=262144, follow_redirects=False)` returns `status`, `headers`, and
`body` bytes, including HTTP error responses. HTTP(S) only; URL userinfo is
refused. Responses are bounded (maximum 1 MiB). Each HTTP request has an elapsed body-read
budget capped by its timeout and remaining service deadline; bounded read1 chunks
reset the socket timeout to the remaining budget so trickled bodies cannot keep a
worker occupied. Chunked transfer framing uses a deadline-aware raw-reader
adapter so internal chunk-size and trailer readlines cannot extend that budget.
Synchronous DNS resolution and response-header parsing remain
subject to platform resolver / socket inactivity limits; no resolver threads are
created. Kubernetes requests use five-second transport budgets and 4 MiB JSON
caps; inventory pagination stops at four pages / 2000 objects / 20 seconds and
fails visibly instead of returning incomplete inventory. Historical mail logs
retain their 2 MiB cap and truncation detection. Redirects are disabled by default; opted-in
redirects must remain on the same origin, including when no explicit auth
header is present. The default User-Agent is `HomePBP-monitor/1`; callers may override it.
Do not bypass this helper for service HTTP calls.
`ctx.now` is Unix time, `ctx.remaining()` reports remaining seconds, and
`ctx.kube` is the existing read-only Kubernetes client. Its RBAC has no Secret
read access; do not widen permissions to retrieve credentials.

Use `deferred` for deliberately unavailable or unprovisioned coverage. It creates
a visible informational severity1/dashboard problem. Withdrawing coverage cannot
close an already-confirmed service outage. Prefer credential-free or narrowly
scoped read-only checks; do not provision native write-capable tokens to silence
coverage problems. No tool or collector gets Secret API read permission.

The JSON policy uses these keys:

- `interval`:60–86400 seconds, default900; `deadline`:1–30 seconds, default30.
- `failure_grace_seconds`:0–172800, default900.
- `minimum_failure_observations` and `minimum_recovery_observations`:1–20,
  both default2.
- `severity`:0–5, default3, caps the row severity. `notification`: `page`
  (default) or `dashboard`; row overrides are permitted. Severity1/2 default
  to dashboard unless a row explicitly selects otherwise.
- `workloads`: list of `{namespace,kind,name}` objects. Supported kinds are
  Deployment, DaemonSet, StatefulSet, Cluster (CNPG), and Node. Per-row workloads
  override `check_workloads` (a mapping of exact check names to workload lists),
  which overrides the module default `workloads`. Keep external Home Assistant/upstream checks
  empty, and scope multi-target rows separately to avoid unrelated node grace.

Initial probes receive a deterministic phase over the full interval. Subsequent
probes are due one interval after completion, including failures; there is no
one-minute error retry. Three workers and a bounded queue operate independently
of infrastructure collection. Initial due time plus queue allowance and deadline
permits normal warmup. Missed completion/freshness bounds create one telemetry
incident. Workers may remain occupied by an underlying synchronous operation;
transport limits and the independent collector freshness/watchdog stay important.

The runner advances failure/recovery counters only on completed real executions.
Failure requires elapsed grace plus the configured count of independent failed
observations. Recovery requires the configured count of real healthy observations.
A cached snapshot never advances counters. Raw observation, count and timestamp
remain visible separately from confirmed/latching incident state. Unknown retains
confirmed state and interrupts positive recovery evidence. A new check without a
trustworthy baseline publishes no state sample until genuine healthy confirmation
or confirmed failure; this prevents cached zeroes from closing an old Zabbix
incident after lost state. Warmup and pending raw-failure counts remain visible in
the module telemetry detail.

`/state/functional-checks.json` atomically persists only bounded safe check names,
confirmed states, counters, timestamps, severity and notification policy; never
bodies, credentials or module diagnostic details. Valid saved failures survive
collector restart/source reload. Restored healthy history requires new independent
healthy observations before it can supply recovery samples. Missing/corrupt state requires an independent
baseline before healthy publication. Corruption remains a visible persistence
problem across restart until real baselines have been restored. Persistence failures
also report explicitly. State is a replaceable monitoring cache, not application
backup. Do not delete it merely to clear a service incident.

The collector joins declared workloads to already-loaded pod/Deployment/DaemonSet
inventory, CNPG labels and StatefulSet pod owners. No extra API permissions are
needed. Existing placement-based10-minute node recovery grace,30-minute Longhorn
rebuild grace, five-snapshot native recovery gate, delayed one-shot actions and
recipient-only recovery remain active. The runner's independent confirmation is
additional to those snapshot gates. Explicit `notification=dashboard` trigger
tags exclude every problem notification action, including severity1 coverage
problems; severity alone does not determine WhatsApp delivery. Existing untagged
native monitoring triggers retain their notification behavior.

Credentials remain optional read-only mounts under `/credentials`. Declare exact
keys and approved permissions in each service runbook; absence must not pressure
operators to broaden access. Validate `scripts/test zabbix` and Kustomize output,
then inspect fresh observed timestamps, raw/confirmed states, parent-node fields,
discovered trigger expressions and action tags after approved deployment. Collector
and Zabbix HTTP success do not prove message completion/delivery.
