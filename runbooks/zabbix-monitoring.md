# HOME-3: Zabbix monitoring

## Current deployment (2026-10-07)

The reviewed `scripts/deploy-zabbix.py --apply` was run with explicit approval.
Zabbix server/frontend and the collector are Ready. CNPG has two Ready replicas
on Buksi and Pufi with 10Gi local SSD PVCs; Zabbix runs on Pamacs. The first B2
base backup completed. The API reports 7.0.31 and the collector produces 205
checks. Live validation corrected Pocket ID's expected health status to 204 and
the Actual Budget probe to port 5006.

The Zabbix check/role bootstrap is applied. Live validation confirms 205
discovered checks, no unsupported items, and API-role rejection of forbidden
methods for both identities. Baloo's ten-tool MCP catalog and live read,
history, acknowledgement, bounded suppression/unsuppression, and scoped
maintenance/cancellation tests passed against a disposable check. The user
confirmed both problem and recovery messages arrived in WhatsApp; a bounded
hook test independently returned completed execution and `delivered: true`.
The old periodic LLM `cluster-health` job is disabled in source. Its replacement
is the native command watchdog every five minutes; a healthy manual run completed
in 369 ms with `NO_REPLY` and silent delivery suppression. Per the user's chosen
mail policy, incoming activity monitoring replaces the synthetic round-trip
gate: check continuously, start at 24 hours of silence, then adapt from actual
completed arrival gaps. No synthetic messages or additional mailbox credentials
are required.

The protected web UI and administrator portal card are deployed through GitOps.
Pocket ID's live inventory has 30 explicitly restricted clients; live tests
confirmed no-group and kids denial for monitoring. The user verified browser
access. A fresh post-configuration CNPG base backup completed. Measured server,
frontend, collector, proxy, and two database pods used about 430 MiB combined;
the Baloo bridge is additional. Measurements are a point-in-time sample.

## Architecture

Zabbix 7.0.31 LTS provides problem history, acknowledgements, suppression,
recovery, and planned maintenance. The server and Nginx/PHP frontend share one
movable pod, softly preferred on Pamacs. Two CNPG PostgreSQL 17 replicas use
separate nodes and local SSD PVCs. Daily base backups and continuous WAL archive
go to B2 through the currently deployed native CNPG backup backend. Include this
cluster in the Barman Cloud Plugin migration before upgrading to CNPG 1.31.

The `collector` Deployment uses Python's standard library and queries the
Kubernetes API once a minute. Its ServiceAccount has get/list access to nodes,
pods, deployments, DaemonSets, node metrics, Longhorn volumes/backups/targets,
and CNPG clusters/schedules. Namespace-local Roles add node-config readiness
events and Stalwart pod logs. It cannot read Secrets/ConfigMaps, execute
commands, or change cluster resources. Log checks retain counts, not mail
content. HTTP/TCP probes are explicitly configured in `assets/policy.json`.

Zabbix polls `/snapshot` once a minute. Discovery creates check state, severity,
and evidence items. A problem requires three failing samples. Collection/API
failures produce explicit problems; an HTTP snapshot older than three minutes
returns 503. Zabbix raises a no-data problem if collection or polling stops and
also monitors unsupported items. Expected nodes, core Deployments, and database
clusters stay in the inventory even when missing. Newly created infrastructure
must be added to the expected inventory. Longhorn volumes and DaemonSets are
discovered dynamically.

Lost discovered resources are disabled immediately and deleted after one day.
Dependent preprocessing first selects the check object, discarding absent
retired checks, then extracts each field with normal error handling. Malformed
fields on an active check remain unsupported. This prevents replaced pod names
from producing false preprocessing alarms while preserving schema-failure
detection. Live verification and Baloo current-item queries exclude disabled
historical items; check count varies with pod and resource inventory.

Physical storage uses the existing `node-storage-health` readiness result and
failure events. It preserves that collector's disk quarantine and latched-error
policy. It does not collect separate SMART counter histories. Longhorn backup
freshness uses completed Backup objects, rather than trusting recurring-job
labels or cached Volume backup status. Enabled critical/default backup groups
have 48-hour/10-day thresholds. An excluded marker does not cancel a remaining
active backup group. CNPG schedules require six fields; supported daily/weekly
schedules get the same freshness limits. Missing archive/backup conditions fail
closed.

The web UI is at `https://monitor.newjoy.ro`, gated by the `zabbix` Pocket ID
client and an oauth2-proxy allowing only `advanced_apps`. Both the root and
public API paths require Pocket ID; only `/oauth2` serves the sign-in flow.
Zabbix keeps its own application login after Pocket ID authentication.
The proxy does not grant Zabbix roles or administrative access.
The shared provisioner creates a denied-by-default client; reconcile its group
policy with `scripts/reconcile-pocket-id-access.py --apply` after provisioning.
OIDC and cookie secrets are generated in-cluster and never committed.

For private administrative API work:

```bash
kubectl -n zabbix port-forward service/zabbix-web 18080:80
```

Open `http://127.0.0.1:18080`. The bootstrap script replaces the default Admin
password and stores it only in `zabbix/zabbix-admin`. Retrieve credentials
privately when needed. Namespace ingress policy permits Baloo/monitoring HTTP,
namespace-local PostgreSQL, CNPG operator management traffic, and ingress-nginx
traffic to the frontend and authentication proxy. Collector snapshots have no
public route. Baloo uses the internal Service and does not pass through SSO.

## Baloo boundary

The private Baloo repository owns `openclaw/tools/zabbix-client.js`,
`zabbix-mcp.js`, and the `manage-monitoring` skill. Only Alpar allows
`zabbix__*`; every other agent explicitly denies it. The MCP server is on pod
loopback port 18812 and has no Service. Separate read and operations tokens in
`baloo/zabbix-mcp` are mounted only into the sidecar.

Zabbix roles enforce exact API method allowlists. Read access covers problems,
events, hosts, triggers, items, history, and maintenance. Operational access adds
only event acknowledgements and maintenance creation/deletion. The operational
user has read-write access only to the HomePBP host group. Both machine accounts
have disabled frontend access. Neither credential can execute scripts, import
configuration, manage hosts/templates/users/tokens, or change global settings.

The adapter separately validates arguments, caps query responses at 1 MiB,
bounds suppression to 30 days, and restricts maintenance to existing check IDs,
at most seven days, with a start within 30 days. It can cancel only `Baloo: `
windows. MCP sessions are limited to 32 and expire after five idle minutes.
Baloo changes problem state only when Alpar requests the action and records a
reason. Maintenance suppresses selected problem tags while collection continues.

The candidate initMAX implementation was audited at v1.34, commit
`48f7f58b071687f4d7ad595e89defcd167d845c6`. Its tool-registration filters select
groups such as `host`, including configuration writes; it does not implement
an exact method registration allowlist. This deployment uses a smaller curated
adapter with the MCP SDK already shipped in the pinned OpenClaw image, avoiding
an additional Python/MCP/reporting/admin runtime. Reconsider upstream if it can
provide the required exact surface without a local fork.

Zabbix's webhook uses a separate `MONITORING_HOOK_TOKEN`, never the Gateway auth
token. It posts only event ID/state/name to `/hooks/zabbix`. The mapping targets
Alpar in an isolated low-thinking run and sends a concise problem/recovery
message to the configured owner WhatsApp destination. Alert data stays wrapped
as untrusted external input. Alpar reads current evidence before responding and
does not remediate from an alert alone. Gateway HTTP 200 proves admission, not
model completion or delivery; validate the actual channel result during cutover.

BetterStack remains the independent external outage detector. Zabbix and Baloo
cannot notify while their cluster or internet connection is completely down.

Routine collector polling and the five-minute `managed: monitoring-watchdog`
command do not invoke an LLM. The watchdog reads the Zabbix API and collector
freshness through the bridge's `/watchdog` endpoint, stays silent on healthy or
single failed checks, alerts after two consecutive failures, reminds at most
every six hours, and reports recovery once. It cannot report if Baloo itself is
down; independent external monitoring covers that case. Zabbix invokes Alpar
on problem/recovery events, and interactive monitoring requests also invoke an
LLM. Other unrelated Baloo scheduled jobs retain their own behavior.

## Deployment and cutover

1. Validate local tests and Kubernetes dry runs. Deploy through the `zabbix`
   ArgoCD Application in `apps/zabbix.yaml`, using the normal reviewed GitOps
   workflow. Publish the coordinated Baloo source and homelab manifests; preserve
   unrelated working-tree changes. Do not restart OpenClaw before its new source
   files and credentials exist.
2. Create the `zabbix` namespace. Copy the existing B2 credentials to a
   namespace-local `cnpg-backup-credentials` Secret with `ACCESS_KEY_ID` and
   `SECRET_ACCESS_KEY` keys, without writing credentials to git or stdout.
3. Let ArgoCD sync the Zabbix manifests and wait for CNPG Ready, both Zabbix containers,
   and the collector. The collector must return a fresh snapshot; investigate
   initial problems instead of suppressing them wholesale.
4. With the private port-forward running, reconcile the owned Zabbix objects:

   ```bash
   python3 scripts/bootstrap-zabbix.py --apply
   ```

   The helper creates a HomePBP host, discovery/item/trigger prototypes,
   restricted machine users/roles, and API tokens. Repeated runs preserve tokens
   and update integration-owned settings. An existing Zabbix instance with a
   changed Admin password requires the correct `zabbix-admin` Secret; do not
   reset an existing database to regain access.
5. Bootstrap provisions a distinct random `MONITORING_HOOK_TOKEN` key in `baloo-secrets`.
   The render-config and config-renderer containers consume it. Deploy the
   coordinated Baloo source and sidecar manifest. One OpenClaw rollout is needed
   for the new sidecar/volume/environment. Later policy/skill changes hot-reload.
6. Verify MCP discovery from the deployed OpenClaw version and confirm other
   agents cannot see the namespace. Inspect Zabbix API roles and prove denied
   read/operational methods are rejected by the API itself. Test one disposable
   problem, acknowledgement, bounded suppression/unsuppression, scoped
   maintenance/cancellation, and recovery.
7. Enable delivery only after the hook is configured and validated:

   ```bash
   python3 scripts/bootstrap-zabbix.py --apply --enable-alerts
   ```

   Test a disposable notification and confirm actual WhatsApp delivery. Check
   Zabbix alert status and Gateway logs when a webhook fails. Keep the existing
   cluster-health cron running during cutover. Disable it only after alert
   delivery and recovery are proven; retain a deterministic external check of
   monitoring/Baloo availability.
8. Confirm a successful new CNPG base backup after configuration, continuous
   archiving, replica health, and actual CPU/RSS. Nominal requests for the new
   server/frontend/collector/two DB instances total 800 MiB, plus 48 MiB for
   the Baloo sidecar. These are scheduling requests, not measured usage.

## Incoming-mail activity

The collector checks Stalwart SMTP/IMAPS, Migadu IMAPS/SMTP connectivity,
fetchmail errors, Stalwart delivery failures, and mail workload readiness. The
`Mail incoming activity` check additionally observes actual receiving activity
across the configured Migadu mailboxes, 24 hours a day.

It matches a `queue.queue-message` SMTP submission on port 25 from loopback
(fetchmail in the same pod) to a successful `message-ingest.ham` or
`message-ingest.spam` record. Internal app mail, outbound relay success, IMAP
imports, and failed ingestion do not qualify. Queue IDs are hashed and
deduplicated, including messages delivered to multiple recipients. Only hashed
identifiers and timestamps are retained; mail contents, addresses, subjects,
and Message-IDs are not stored or sent to Baloo.

The user selected an initial 24-hour silence threshold with adaptation. The
policy lives in `config/zabbix/manifests/assets/policy.json`. After at least ten
completed gaps are available, use 1.5 times the 90th-percentile gap from a rolling
seven-day history, rounded up to a whole hour and bounded to 6–48 hours. The
current silent interval does not enter the baseline. Recalibrate on new arrivals
or an explicit policy change; freeze the threshold between arrivals. A gap
that already crossed the alert deadline is excluded from normal-rate training
after recovery. This prevents a stopped receiving path from extending its own
deadline or recovering just because its training samples aged out.

Count today's arrivals from midnight in Europe/Bucharest, but carry elapsed
silence continuously across midnight. The check runs once a minute and uses
the existing three-failing-sample Zabbix trigger and Baloo problem/recovery
delivery. A log-query or state-persistence failure reports monitoring
unavailability rather than a healthy receiving path. A silence problem is a
traffic anomaly; it does not establish that mail was sent during the interval
or prove outbound end-to-end delivery.

`collector-arrival-state` is a 512Mi single-replica SSD PVC containing this
replaceable timestamp cache. Its `longhorn-ssd-noreplica` class uses the supported
`excluded` recurring-job group. Seed from retained Stalwart logs at startup and
rescan seven days every six hours; between full scans, query overlapping recent
logs and cover any poll gap. Bounded log responses fail visibly if truncated.
The collector keeps its read-only Kubernetes RBAC and receives no mail secrets.

After the replacement check is fresh and healthy, retire the old gate through
the private API port-forward:

```bash
python3 scripts/bootstrap-zabbix.py --apply --retire-synthetic-mail-check
```

The guarded helper requests closure of only the HOME-3 synthetic mail warning,
with an audit comment identifying the policy change. Verify it leaves the
current problem list after Zabbix processes the asynchronous task. Disabling a
lost discovery item alone does not close its existing problem.

Initial measurements on 2026-10-07 found two external messages by 10:25
Bucharest time, at 07:13 and 10:02 (a 2h49m gap). Retained weekly history held 27
arrivals, with a median gap of 2h33m and a longest normal gap of 20h03m. Later
validation found four arrivals that day and an adaptive threshold of 24 hours.

## Validation and recovery

```bash
scripts/test zabbix access-policy
kubectl -n zabbix get pods
kubectl -n zabbix get cluster zabbix-db
kubectl -n zabbix get backups.postgresql.cnpg.io
kubectl -n zabbix logs deployment/collector --tail=30
kubectl -n zabbix logs deployment/zabbix -c server --tail=50
```

In the dedicated Baloo workdir:

```bash
node --test openclaw/tools/zabbix-client.test.js
```

Run `zabbix-mcp.integration-test.js` inside the pinned OpenClaw image to validate
the actual SDK HTTP contract using fake API credentials and no messages or LLM.
It exercises initialization, tool discovery, rendered/structured results,
credential separation, and rejection of unsupported fields.

Wait for actual Zabbix suppression state before testing unsuppression: those
updates are asynchronous, and an immediate unsuppress can be reduced to a comment
before suppression is effective. Maintenance validation queries only requested
check keys; avoid fetching a capped whole-host inventory as the check set grows.
The webhook bootstrap uses Zabbix 7.0's `maxattempts` field and explicitly enables
the media type with `status: 0`; see the
[media type API reference](https://www.zabbix.com/documentation/7.0/en/manual/api/reference/mediatype/object).

For bad check configuration, correct `policy.json`/collector code, sync, and
verify fresh state plus Zabbix recovery. For a dead collector, inspect its API
permissions, readiness and logs; stale snapshots deliberately fail. For dead
Zabbix, check CNPG primary/replica health, schema/startup logs, and memory limits.
For dead alerts, inspect webhook alert failures, hook authentication/admission,
Gateway completion/delivery facts, and the owner channel. Acknowledging a problem
does not recover its service.

Before a Zabbix major upgrade, take and verify a CNPG backup. Database schema
changes may require restoring the pre-upgrade database to roll back the image.
For database loss, restore CNPG from B2 following the existing CNPG recovery
procedures, then reconcile the integration. The DB holds history, problem state,
maintenance, users, and tokens; preserve Kubernetes credentials alongside it.
If a restored DB predates token creation, rotate/re-provision the corresponding
API tokens rather than assuming a retained Secret still matches.

To roll back the Baloo integration, disable the Zabbix action first, restore the
previous coordinated source and Deployment, and leave the old cluster-health
job enabled. Do not prune Zabbix or its PVCs as an incident workaround; preserve
history and backups while investigating.
