# CloudNativePG functional baseline

The `functional/cnpg` module observes all ten explicitly configured database
clusters every five minutes. Each cluster has one stable `CNPG SQL and
replication <namespace>/<cluster>` check. Failures retry after one minute and
use the existing three-failing-sample Zabbix trigger.

The native instance exporter on TCP 9187 executes SQL queries. Required finite
metrics prove database-size and recovery-state queries work, compare SQL
recovery roles with the operator's designated primary, require standby WAL
receivers and the primary's expected streaming replica count, and reject replay
lag above 300 seconds. Empty databases and zero activity are healthy. The default
CNPG lag query returns zero when received and replayed WAL positions match, so
an idle database does not fail merely because its last transaction was long ago.
See the [official default query definitions](https://github.com/cloudnative-pg/cloudnative-pg/blob/release-1.28/config/manager/default-monitoring.yaml).
Live primary/standby metric schema should be revalidated after operator upgrades.

Allow ten minutes following a Ready-condition transition, primary transition,
or PostgreSQL startup before enforcing roles/replication. Explicit CNPG node
maintenance and `cnpg.io/hibernation: on` defer observation with visible evidence.
This grace prevents normal restarts and switchovers paging before replication
settles. A long-running maintenance flag suppresses this baseline intentionally;
clear it when maintenance ends. Existing readiness, backups and WAL archive
checks continue independently. Use Zabbix maintenance for other planned work.

No database credentials, Secret reads, writes, pod exec, or new RBAC are required.
A single existing cluster-list GET obtains instance IPs from
`status.instancesReportedState`; incomplete instance coverage fails visibly.
Its existing API timeout is 15 seconds and it is admitted only with at least
16 seconds remaining. Responses with pagination fail rather than fetching
unbounded pages. At most 100 CRs / 80 instance scrapes / eight workers are
allowed, and each HTTP scrape has a maximum three-second timeout, 256 KiB body
limit and the shared 30-second module deadline. Non-200, timeout, missing,
ambiguous and nonfinite required metrics fail without emitting response bodies,
database names, IPs or exception text.

Rollout needs the source module/config and the narrow `cnpg-metrics-monitoring`
NetworkPolicy permitting only `zabbix/app=collector` to `zabbix-db` TCP 9187.
Other database namespaces currently do not isolate exporter ingress. If they
become isolated, add equivalent narrow access in that service's source manifests.
Add newly deployed clusters to the explicit JSON inventory. The exporter remains
internal and database TCP access stays unchanged.

This proves native SQL observation and streaming/replay consistency, not an
application login, permissions on each application's tables, an actual write,
end-to-end client routing, restore success, or durability under failure. A native
exporter could itself serve incorrect/cached data; this check does not introduce
synthetic writes to rule that out. Replication-slot backlog and backup/archive
health remain outside this check's scope.

Validation: unit fixtures cover idle/healthy metrics, wrong SQL roles, replay
lag, disconnected streaming, malformed/missing/nonfinite metrics, errors,
maintenance/startup grace, missing inventory and deadline exhaustion. A safe
live Kubernetes API proxy scrapes confirmed the deployed primary and standby's
exact required metric names: primary recovery=0/streaming=1 and standby
recovery=1/receiver=1/lag=0. This uses the operator exporter's
SQL privileges; it does not demonstrate the collector's future network path.
