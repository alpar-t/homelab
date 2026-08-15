# Migrate CNPG PostgreSQL from Longhorn to local SSD

Status: the first four migrations were completed on 2026-08-12. `tandoor-db`,
`vikunja-db`, `roundcube-db`, and `paperless-db` are on local SSD. Tandoor's
planned standby-node reboot covered the local-PVC recovery mechanism;
`stalwart-db` is the next migration.

This runbook records the storage decision, current inventory, rolling migration
procedure, and the operational changes required when CloudNativePG (CNPG) uses
node-local storage.

## Decision

Use the existing `local-ssd` StorageClass for CNPG PostgreSQL data. Keep two
CNPG instances on different nodes and keep CNPG-native WAL archiving and base
backups in B2.

Do not generalize this decision to application data. Longhorn remains useful
for single-instance applications and irreplaceable files that do not have their
own replication and recovery controller.

The migration is worthwhile because the current design duplicates the same
redundancy at two layers:

| Layer | Current copies |
| --- | ---: |
| CNPG physical streaming replication | 2 |
| Longhorn replicas for each CNPG PVC | 2 |
| Effective copies of each database page | up to 4 |

CNPG also archives WAL and base backups to B2. During the 2026-08-12 whole-site
power cut, PostgreSQL recovered and failed over correctly, while Longhorn had to
rebuild many volume replicas before storage redundancy returned. Local storage
removes that block-storage recovery layer from database startup.

### What Longhorn still provides

Longhorn is not valueless for a replicated database:

- An individual PVC can be detached and attached on another node without
  cloning a new PostgreSQL standby, but attachment does not guarantee that its
  data replicas are local to the new workload node.
- `longhorn-ssd` supports volume expansion; Rancher local-path volumes do not.
- Longhorn adds volume health reporting, snapshots, and another recoverable
  copy of each CNPG instance.

Those benefits are modest here because CNPG already fails over, recreates a
missing standby from the surviving primary, and performs application-consistent
PostgreSQL backups. Longhorn also adds network I/O, instance managers, snapshot
chains, attachment ordering, and replica rebuild traffic.

The live `longhorn-ssd` class uses two replicas and `dataLocality:
best-effort`. Longhorn therefore tries to keep one replica with the workload,
but after a pod moves it may initially serve I/O from remote replicas and then
rebuild a local one. Even after locality converges, the Longhorn engine
synchronously replicates block writes to the other replica on another node, so
network latency and availability remain in PostgreSQL's storage write path.

That makes PVC mobility primarily an availability and recovery convenience,
not a performance benefit. For these databases, CNPG promotion of an existing
standby already on local NVMe is preferable to moving the old primary's block
device and running it against remote storage. The current CNPG clusters do not
configure synchronous PostgreSQL replication, so standby WAL transport is not
an equivalent remote block-write acknowledgement on every commit.

`longhorn-ssd-noreplica` is a possible compromise, but it retains most Longhorn
failure modes while removing storage-level redundancy. Prefer direct local
storage unless a specific cluster needs Longhorn's expansion or PVC mobility.

### Risks accepted with local storage

- A failed node makes its local PVC unavailable. CNPG promotes the surviving
  instance, but the cluster is single-copy until the node returns or the failed
  instance and PVC are replaced on the third node.
- Replacing a local standby copies the whole database from the primary. This is
  quick for the current databases except Home Assistant, which is about 40 GB.
- `local-ssd` has no volume expansion. Increasing a request does not grow the
  existing local volume; recreate instances one at a time on larger PVCs.
- Local-path does not provide useful capacity accounting or per-PVC enforcement.
  Monitor the node's `/var` filesystem and preserve generous free space.
- Loss of two nodes containing both CNPG instances requires recovery from B2.

These risks are acceptable only while every cluster has two ready instances on
different nodes and verified CNPG backups.

## Current storage and inventory

`local-ssd` already exists and uses the k3s built-in Rancher local-path
provisioner with `WaitForFirstConsumer`. It currently provisions below:

```text
/var/lib/rancher/k3s/storage
```

That path and `/var/lib/longhorn-ssd` are both on each node's approximately 1 TB
NVMe `/var` filesystem. They are not separate physical SSDs. Free space at the
2026-08-12 audit was:

| Node | NVMe size | Used | Available |
| --- | ---: | ---: | ---: |
| `buksi` | 931 GB | 224 GB | 708 GB |
| `pamacs` | 953 GB | 495 GB | 459 GB |
| `pufi` | 931 GB | 480 GB | 452 GB |

Every live CNPG PVC used `longhorn-ssd` at the start of that audit. The status
column below is the migration record:

| Namespace | Cluster | Instances | PVC size each | Approx. database size | Status / notes |
| --- | --- | ---: | ---: | ---: | --- |
| `tandoor` | `tandoor-db` | 2 | 5 Gi | 24 MB | Migrated; verified, post-backup and standby-node reboot test completed 2026-08-12 |
| `vikunja` | `vikunja-db` | 2 | 5 Gi | 18 MB | Migrated; verified and post-backup completed 2026-08-12 |
| `roundcube` | `roundcube-db` | 2 | 5 Gi | 22 MB | Migrated; verified and pre/post backups completed 2026-08-12 |
| `paperless-ngx` | `paperless-db` | 2 | 5 Gi | 65 MB | Migrated; verified and pre/post backups completed 2026-08-12; documents remain on Longhorn |
| `stalwart-mail` | `stalwart-db` | 2 | 8 Gi | 77 MB | Migrated; verified and pre/post backups completed 2026-08-13; mail blobs remain on Longhorn |
| `immich` | `immich-db` | 2 | 20 Gi | 3.8 GB | Migrated; VectorChord/indexes and pre/post backups verified 2026-08-13 |
| `homeassistant` | `homeassistant-db` | 2 | 45 Gi | 40 GB | Migrated; recorder connectivity and pre/post backups verified 2026-08-13 |
| `vaultwarden` | `vaultwarden-db` | 2 | 5 Gi | 17 MB | Migrated; SQL/app and pre/post backups verified 2026-08-14 |
| `pocket-id` | `pocket-id-db` | 2 | 5 Gi | 19 MB | Migrated last; identity app and pre/post backups verified 2026-08-14 |

There is no separate OnlyOffice CNPG cluster. Vikunja was missing from the old
inventory and is included here.

Recommended order:

1. `tandoor-db`
2. `vikunja-db`
3. `roundcube-db`
4. `paperless-db`
5. `stalwart-db`
6. `immich-db`
7. `homeassistant-db`
8. `vaultwarden-db`
9. `pocket-id-db`

Stop after each of the first two pilots and observe a normal backup plus one
planned node reboot before continuing in batches.

## Required target configuration

For each cluster, replace the Longhorn-specific storage block with:

```yaml
spec:
  affinity:
    enablePodAntiAffinity: true
    podAntiAffinityType: required
    topologyKey: kubernetes.io/hostname
  storage:
    size: <keep-current-size>
    storageClass: local-ssd
    resizeInUseVolumes: false
```

Why these fields matter:

- `required` anti-affinity prevents both database copies from landing on one
  node. CNPG defaults to `preferred`, which is not strong enough for local data.
- `WaitForFirstConsumer` binds each new local PVC to the node selected for its
  PostgreSQL pod.
- `resizeInUseVolumes: false` reflects that local-path cannot expand an existing
  volume and prevents CNPG from treating it like expandable storage.

Remove any `recurring-job-group.longhorn.io/*` labels from the CNPG
`pvcTemplate`; they have no meaning on local storage. Do not change the image,
PostgreSQL major version, extensions, resource settings, backup destination, or
credentials during the storage migration.

Before the first migration, also update these operational controls:

- Add `/var` capacity and NVMe health alerts for every node.
- Extend `runbooks/node-maintenance.md` with CNPG local-PVC handling.
- Decide whether to re-enable CNPG PodDisruptionBudgets; all current clusters
  explicitly use `enablePDB: false`.
- Keep the `kubectl cnpg` plugin compatible with the deployed operator. Version
  1.30.0 was installed with Homebrew on the workstation on 2026-08-12; verify
  `kubectl cnpg version` before a migration window. Installation reference:
  https://cloudnative-pg.io/docs/1.30/kubectl-plugin/

## Migration method

Use CNPG's rolling PVC recreation. Do not delete the `Cluster` and restore it
under the same name merely to change StorageClass. Rolling recreation keeps the
primary online, preserves services and credentials, and avoids B2 archive-name
collisions.

CNPG's storage documentation explicitly supports moving a multi-instance
cluster by changing its storage configuration and deleting one PVC and pod at a
time, with the primary last:

- https://cloudnative-pg.io/docs/1.30/storage/#re-creating-storage
- https://cloudnative-pg.io/docs/1.30/failure_modes/#self-healing
- https://cloudnative-pg.io/docs/1.30/kubernetes_upgrade/

The commands below are a template. Substitute the namespace and cluster name.

Use `scripts/migrate-cnpg-to-local-storage.sh` for the actual migration. It
implements the gates below, derives progress from the live PVC and primary
state, and can safely resume after interruption. Mutations require the explicit
`--execute` flag.

```bash
# Review the inferred state and complete plan.
scripts/migrate-cnpg-to-local-storage.sh \
  --namespace vikunja --cluster vikunja-db \
  --argocd-app vikunja --deployment vikunja

# Execute or resume every stage.
scripts/migrate-cnpg-to-local-storage.sh \
  --namespace vikunja --cluster vikunja-db \
  --argocd-app vikunja --deployment vikunja \
  --stage all --execute
```

The stage names are `status`, `preflight`, `backup-pre`, `replace-standby`,
`promote`, `replace-remaining`, `verify`, `backup-post`, and `all`. Prefer
`all`; select a stage only for diagnosis or an explicitly controlled resume.

### 1. Preflight

Require a healthy cluster, healthy storage, different current nodes, and a
recent successful CNPG base backup:

```bash
namespace=tandoor
cluster=tandoor-db

kubectl get cluster.postgresql.cnpg.io "$cluster" -n "$namespace"
kubectl get pods -n "$namespace" -l "cnpg.io/cluster=$cluster" -o wide
kubectl get pvc -n "$namespace" -l "cnpg.io/cluster=$cluster"
kubectl get backups.postgresql.cnpg.io -n "$namespace" \
  -l "cnpg.io/cluster=$cluster" --sort-by=.metadata.creationTimestamp
kubectl get volumes.longhorn.io -n longhorn-system
kubectl get nodes
```

Require `instances: 2`, `readyInstances: 2`, two distinct nodes, no degraded
Longhorn volume, and current continuous archiving. Verify the CNPG plugin, then
trigger and wait for a fresh on-demand backup:

```bash
kubectl cnpg version
kubectl cnpg backup "$cluster" -n "$namespace"
kubectl get backups.postgresql.cnpg.io -n "$namespace" --watch
```

For Home Assistant, confirm the standalone HA device can reconnect after a
brief database switchover. For Pocket ID, keep an existing authenticated admin
session or break-glass path available.

### 2. Commit the target storage policy

Edit the cluster manifest in `config/<app>/manifests/postgres-cluster.yaml` to
use the required target configuration above. Commit and push it, then let Argo
CD sync.

Confirm that only the desired live cluster spec changed. Existing PVCs remain
on Longhorn until replaced:

```bash
kubectl get cluster.postgresql.cnpg.io "$cluster" -n "$namespace" \
  -o jsonpath='{.spec.storage.storageClass}{"\n"}'
kubectl get pvc -n "$namespace" -l "cnpg.io/cluster=$cluster" \
  -o custom-columns='NAME:.metadata.name,CLASS:.spec.storageClassName,NODE:.metadata.annotations.volume\.kubernetes\.io/selected-node'
```

Do not combine this change with an image, PostgreSQL, extension, or application
upgrade.

### 3. Replace the standby first

Identify the current primary and choose the other pod:

```bash
kubectl get cluster.postgresql.cnpg.io "$cluster" -n "$namespace" \
  -o jsonpath='{.status.currentPrimary}{"\n"}'
kubectl get pods -n "$namespace" -l "cnpg.io/cluster=$cluster" -o wide
```

Delete the standby PVC and pod together. This is intentionally destructive to
one redundant database copy; confirm the names immediately before running it:

```bash
kubectl delete pvc/<standby-name> pod/<standby-name> -n "$namespace"
```

CNPG creates a new instance with a new serial number, provisions a `local-ssd`
PVC, and clones it from the primary. Wait for the replacement to become ready:

```bash
kubectl get pods -n "$namespace" -l "cnpg.io/cluster=$cluster" -w
kubectl get cluster.postgresql.cnpg.io "$cluster" -n "$namespace" -w
```

Do not continue until the cluster is healthy with two ready instances, the new
PVC says `local-ssd`, the replacement is on a different node from the primary,
and streaming replication is current.

### 4. Promote the local instance

Promote the newly created local-storage standby so the remaining Longhorn
instance is no longer primary:

```bash
kubectl cnpg promote "$cluster" <new-local-instance-name> -n "$namespace"
kubectl get cluster.postgresql.cnpg.io "$cluster" -n "$namespace" -w
```

Expect a short client reconnect window. Confirm the application is healthy and
the cluster again reports two ready instances before proceeding.

### 5. Replace the remaining Longhorn instance

Delete the old Longhorn-backed instance's PVC and pod together:

```bash
kubectl delete pvc/<old-longhorn-instance> pod/<old-longhorn-instance> \
  -n "$namespace"
```

Wait for CNPG to create and synchronize a new local standby. The final state
must have two `local-ssd` PVCs on different nodes:

```bash
kubectl get cluster.postgresql.cnpg.io "$cluster" -n "$namespace"
kubectl get pods -n "$namespace" -l "cnpg.io/cluster=$cluster" -o wide
kubectl get pvc -n "$namespace" -l "cnpg.io/cluster=$cluster" \
  -o custom-columns='NAME:.metadata.name,CLASS:.spec.storageClassName,CAPACITY:.status.capacity.storage'
```

Verify the deleted Longhorn PVs and volumes disappear. Investigate rather than
blindly deleting any leftover replica directory or Longhorn orphan.

### 6. Post-migration gates

Before marking a database complete:

- The cluster has two ready instances on different nodes.
- Both PVCs use `local-ssd` and their PV node affinities match their pods.
- The application passes a write/read smoke test.
- Continuous WAL archiving reports success.
- A new base backup completes after the migration.
- `/var` remains below the alert threshold on all nodes.
- Argo CD reports the application `Synced/Healthy`.

After the first pilot, perform a planned reboot of the node hosting its standby
and verify that the same local PVC is reused when the node returns. Do not test
by deleting both copies or powering off two nodes. A second identical reboot is
not required when the storage class, FCOS/k3s stack, and CNPG configuration are
unchanged; rely on normal maintenance observations instead.

### Post-outage backup recovery

After the 2026-08-12 whole-site power outage, Pocket ID's scheduled `Backup`
remained in `walArchivingFailing` even though its standby had returned and WAL
archiving was healthy. The operator kept retrying the stale object because it
still carried an outage-era backup session. Before removing such an object,
verify all of the following on the current primary:

```sql
SELECT application_name, state, sync_state,
       pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS lag_bytes
FROM pg_stat_replication;
SELECT archived_count, failed_count, last_archived_wal, last_archived_time,
       last_failed_wal, last_failed_time
FROM pg_stat_archiver;
SELECT count(*) FROM pg_stat_progress_basebackup;
```

Require streaming replication, current successful WAL archiving with no new
failure, and zero active base backups. Compare the `Backup` object's recorded
pod/container and session with current state and check operator and instance
logs. Only when the recorded session is demonstrably stale, delete the fully
qualified control object and immediately prove the path with a named backup:

```bash
kubectl -n pocket-id delete backup.postgresql.cnpg.io \
  pocket-id-db-daily-20260812030000
kubectl cnpg backup pocket-id-db -n pocket-id \
  --backup-name pocket-id-db-post-outage-check
kubectl -n pocket-id get backup.postgresql.cnpg.io \
  pocket-id-db-post-outage-check --watch
```

Do not use the ambiguous `backup` short name because Longhorn also registers
it. Pocket ID's replacement completed on `pocket-id-db-2`, covering WAL
`000000230000005300000002`.

Vaultwarden's outage backup was terminally `failed` with `instance manager was
restarted during backup`; it did not need deletion. A new named backup on
`vaultwarden-db-2` completed through WAL `000000210000001400000025` and restored
the cluster's `LastBackupSucceeded=True` condition. Preserve terminal failed
objects as incident evidence unless their presence is blocking reconciliation.

### Tandoor standby-node reboot record (2026-08-12)

Rebooted `buksi`, which hosted standby `tandoor-db-2`. Buksi returned `Ready`
after about three minutes. CNPG retained `tandoor-db-1` as primary on `pamacs`;
`tandoor-db-2` restarted once on `buksi` and reused the unchanged local PVC/PV
`pvc-8ebb28bc-e814-4cc1-96f9-98316443a76e`. Final verification confirmed two
ready instances, zero replication lag, `Synced/Healthy` Argo and application
status, and a new completed base backup `tandoor-db-20260812124323`.

### Stalwart migration record (2026-08-13)

Migrated `stalwart-db` with the resumable script after the global database and
backup gate passed. CNPG cloned `stalwart-db-2` to `local-ssd` on `buksi`,
promoted it, then rebuilt `stalwart-db-1` on `pamacs`. Final verification found
both instances ready on node-matched local PVs, streaming replication at zero
lag, SQL and continuous archiving healthy, Stalwart `1/1`, and Argo
`Synced/Healthy`. The retired Longhorn PVs and volumes disappeared. Backups
`stalwart-db-local-migration-pre` and `stalwart-db-local-migration-post`
completed; the latter covered WAL `000000280000008800000058` through
`000000280000008800000059`. Stalwart's mail-blob PVC remains on Longhorn HDD.

The WAL archiver recorded one transient failure for `00000028.history` during
the controlled switchover at 02:48:50Z, followed by a successful archive at
02:49:39Z and a completed post-migration backup. Treat cumulative failure
counters in context; require a later success and healthy CNPG archiving rather
than expecting the counter to reset.

### Immich migration record (2026-08-13)

Kept the exact VectorChord image/digest, preload library, extensions,
PostgreSQL parameters, 20 Gi size, and backup configuration while changing only
the storage and anti-affinity policy. The policy update caused CNPG's expected
rolling restart; the primary's smart shutdown took several minutes while
existing client sessions drained, then recovered without forced deletion.

The resumable script backed up the Longhorn cluster, rebuilt and promoted
`immich-db-1` on `local-ssd` at `pamacs`, then created `immich-db-2` on
`local-ssd` at `buksi`. A Kubernetes HTTP/2 watch disconnected during the last
clone, but CNPG and the script recovered without intervention. Final checks
confirmed `vchord` 1.1.1, `vector` 0.8.3, the 604 MB `clip_index`, the 872 MB
`face_index`, zero-lag streaming replication, successful archiving, and no
obsolete `pg_vectors` path. The old Longhorn PVs and volumes disappeared;
Immich remained `1/1` and Argo `Synced/Healthy`.

Backups `immich-db-local-migration-pre` and
`immich-db-local-migration-post` completed. The post-backup covered WAL
`0000002600000047000000CF`. Node filesystem use after migration was 21% on
`buksi`, 49% on `pamacs`, and 48% on `pufi`.

### Home Assistant migration record (2026-08-13)

The standalone Home Assistant device had five active recorder connections and
current writes before migration. The 40 GB pre-backup ran on
`homeassistant-db-2` for four hours and six seconds. The initial script run used
a four-hour transition timeout and exited at the backup gate six seconds before
CNPG marked it completed; no PVC had been deleted. Resuming with a six-hour
timeout reused the completed backup and continued from standby replacement.

CNPG cloned and promoted `homeassistant-db-2` to `local-ssd` on `pamacs`, then
rebuilt `homeassistant-db-1` on `local-ssd` at `pufi`. Final verification found
both instances ready on node-matched local PVs, zero-lag streaming replication,
five recorder connections, and recorder writes within two seconds of current
time. The `homeassistant-db-external` service retained `192.168.1.200` and its
primary selector, Argo reported `Synced/Healthy`, and the retired Longhorn PVs
and volumes disappeared.

Backups `homeassistant-db-local-migration-pre` and
`homeassistant-db-local-migration-post` completed. The post-backup covered WAL
`00000024000000D300000043` through `00000024000000D30000005E`. A transient
archive failure for `00000024.history` during the controlled switchover at
12:54:06Z was followed by successful archives through 15:58:28Z and the
completed post-backup. Node filesystem use after migration was 21% on `buksi`
and 38% on both `pamacs` and `pufi`.

The migration script now performs a final ten-second grace poll after a backup
deadline so a controller update at the boundary does not produce a false
timeout. Long-running databases should still use an explicit timeout sized for
their observed backup and clone duration; use at least six hours for this Home
Assistant database at its current CPU limit.

### Vaultwarden migration record (2026-08-13/14)

Migrated `vaultwarden-db` after a fresh global health and backup gate. CNPG
cloned and promoted `vaultwarden-db-2` to `local-ssd` on `pufi`, then rebuilt
`vaultwarden-db-1` on `local-ssd` at `pamacs`. Both local instances reached
CNPG Ready before the primary's `pg_stat_replication` view contained the new
standby, so the script's first final verification stopped safely before the
post-backup. A later idempotent resume skipped all completed storage stages,
verified zero-lag streaming, and created the post-backup.

Final checks confirmed SQL access, two node-matched local PVs, zero-lag
replication, continuous archiving with no failures, Vaultwarden `1/1`, Argo
`Synced/Healthy`, and removal of both old Longhorn PVs and volumes. Backups
`vaultwarden-db-local-migration-pre` and
`vaultwarden-db-local-migration-post` completed; the post-backup covered WAL
`000000220000001400000041` through `000000220000001400000042`.

The migration script now waits for the database-level replication row to reach
`streaming` with zero lag instead of assuming Kubernetes/CNPG Ready immediately
implies that stronger condition. This gate is used both before destructive PVC
replacement and during final verification.

### Pocket ID and fleet completion record (2026-08-14)

Migrated `pocket-id-db` last, after its daily backup and identity application
were healthy. CNPG cloned and promoted `pocket-id-db-2` to `local-ssd` on
`pufi`, then rebuilt `pocket-id-db-1` on `local-ssd` at `pamacs`. Final checks
confirmed SQL access, zero-lag streaming replication, node-matched local PVs,
Pocket ID `1/1`, Argo `Synced/Healthy`, and removal of both old Longhorn PVs and
volumes. Backups `pocket-id-db-local-migration-pre` and
`pocket-id-db-local-migration-post` completed; the post-backup covered WAL
`000000240000005300000035` through `000000240000005300000036`.

The final fleet audit found all nine CNPG clusters at `2/2` with Ready,
ContinuousArchiving, and LastBackupSucceeded true. All 18 CNPG PVCs were Bound
on `local-ssd`; every database's newest backup was completed; every
ScheduledBackup used the required six-field cron; and all nine Argo applications
were `Synced/Healthy`. Node filesystem use was 22% on `buksi` and 37% on both
`pamacs` and `pufi`. This completes the database portion of the Longhorn exit;
application data PVCs explicitly called out in the inventory remain on their
documented storage classes.

## Node loss after migration

CNPG automatically promotes the surviving instance when the primary's node is
lost. What happens to redundancy is an operational choice:

- For a short outage or planned reboot, leave the pod and local PVC bound to the
  node and let them return together.
- For a permanent node or NVMe failure, delete the failed instance's pod and PVC
  after confirming the surviving primary is healthy. CNPG provisions a new
  local PVC on the third node and clones a standby.
- If neither local instance survives, bootstrap a new cluster from the latest B2
  base backup plus archived WAL. Do not attempt an in-place recovery over an
  existing cluster.

Node-local storage makes the first two cases explicit; Longhorn previously hid
some of this by moving or rebuilding the block volume.

## Rollback

If the live cluster is healthy, rollback uses the same rolling method:

1. Change the manifest back to `longhorn-ssd` and sync it.
2. Delete one local standby PVC and pod together.
3. Wait for the new Longhorn standby to become ready.
4. Promote it.
5. Delete and recreate the remaining local instance.

If a migration leaves only one healthy instance, stop and preserve it. Do not
delete its PVC. Repair replication or recover a separate cluster from B2 before
taking another destructive step.

## Tracking checklist

- [x] Add `/var`, inode, NVMe, and SATA SMART health alerts
- [x] Update node-maintenance procedure for local CNPG PVCs
- [x] Enable CNPG-managed PDBs and document the maintenance policy
- [x] Install and verify the CNPG 1.30 `kubectl` plugin
- [x] Migrate `tandoor-db`
- [x] Validate Tandoor's normal post-migration backup
- [x] Validate a planned Tandoor standby-node reboot (buksi, 2026-08-12)
- [x] Migrate `vikunja-db`
- [x] Verify Vikunja's SQL access, zero-lag replication, PV placement, Argo/app health, Longhorn cleanup, and post-backup
- [x] Validate the local-PVC standby-reboot path on the first pilot; no duplicate Vikunja test required
- [x] Review both pilots; proceed to `roundcube-db`
- [x] Migrate `roundcube-db`; SQL, zero-lag replication, PV placement, Argo/app health, Longhorn cleanup, and pre/post backups verified
- [x] Migrate `paperless-db`; SQL, zero-lag replication, PV placement, Argo/app health, Longhorn cleanup, and pre/post backups verified
- [x] Migrate `stalwart-db`; SQL, zero-lag replication, PV placement, Argo/app health, Longhorn cleanup, and pre/post backups verified
- [x] Migrate `immich-db`; VectorChord/indexes, zero-lag replication, PV placement, Argo/app health, Longhorn cleanup, and pre/post backups verified
- [x] Migrate `homeassistant-db`; recorder freshness, external service, zero-lag replication, PV placement, Argo health, Longhorn cleanup, and pre/post backups verified
- [x] Migrate `vaultwarden-db`; SQL, zero-lag replication, PV placement, Argo/app health, Longhorn cleanup, and pre/post backups verified
- [x] Migrate `pocket-id-db`; SQL, zero-lag replication, PV placement, Argo/app health, Longhorn cleanup, and pre/post backups verified
