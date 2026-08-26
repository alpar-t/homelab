# Migrate CNPG backups to the Barman Cloud Plugin

Status: required before upgrading CloudNativePG from 1.30 to 1.31. The live
operator was `1.30.0` on 2026-08-15; all nine clusters still used the deprecated
in-tree `spec.backup.barmanObjectStore` integration.

This runbook moves WAL archiving, base backups, and restores to the CNPG-I
Barman Cloud Plugin. It does not move PostgreSQL data or rewrite existing
Backblaze B2 backups. Keep the B2 destination paths, credentials, archive names,
compression, and retention periods unchanged during the migration.

References:

- https://cloudnative-pg.io/plugin-barman-cloud/docs/migration/
- https://cloudnative-pg.io/plugin-barman-cloud/docs/intro/
- https://cloudnative-pg.io/docs/1.30/release_notes/v1.30/

## Why and when

Native Barman Cloud support was deprecated in CNPG 1.26 and is scheduled for
removal in CNPG 1.31. CNPG 1.30 still supports both implementations, which gives
us a rollback window. Do not upgrade the operator to 1.31 until every cluster
has completed this runbook and a plugin-based restore has been proven.

The plugin adds one Barman sidecar to every PostgreSQL instance. With nine
two-instance clusters, plan for 18 sidecars plus the plugin controller and its
TLS dependency. The database service should remain available through the
rolling pod update, but clients may observe a normal primary switchover or brief
reconnection. Do not combine this change with PostgreSQL image, major-version,
extension, storage, or application upgrades.

## Current inventory

Every cluster below uses a namespace-local `cnpg-backup-credentials` Secret and
its own B2 prefix. Preserve these values exactly.

| Namespace | Cluster | B2 suffix | Retention | Schedule |
| --- | --- | --- | ---: | --- |
| `vaultwarden` | `vaultwarden-db` | `vaultwarden-db` | 30d | daily 02:00 |
| `pocket-id` | `pocket-id-db` | `pocket-id-db` | 30d | daily 03:00 |
| `immich` | `immich-db` | `immich-db` | 14d | daily 05:15 |
| `paperless-ngx` | `paperless-db` | `paperless-db` | 14d | daily 03:15 |
| `vikunja` | `vikunja-db` | `vikunja-db` | 30d | daily 03:20 |
| `stalwart-mail` | `stalwart-db` | `stalwart-db` | 14d | daily 03:30 |
| `homeassistant` | `homeassistant-db` | `homeassistant-db` | 14d | Saturday 04:00 |
| `tandoor` | `tandoor-db` | `tandoor-db` | 7d | Saturday 04:30 |
| `roundcube` | `roundcube-db` | `roundcube-db` | 7d | Saturday 04:45 |

CNPG schedules have a leading seconds field. Preserve their existing six-field
expressions; do not rewrite them as five-field cron.

## Target resources

Install one cluster-wide plugin controller in `cnpg-system`, but create one
namespaced `ObjectStore` per database. The credentials are namespace-scoped and
retention differs between clusters.

Translate each current `barmanObjectStore` block mechanically into an
`ObjectStore`. Move `retentionPolicy` out of the `Cluster` and onto the
`ObjectStore`:

```yaml
apiVersion: barmancloud.cnpg.io/v1
kind: ObjectStore
metadata:
  name: <cluster>-b2
  namespace: <namespace>
  annotations:
    argocd.argoproj.io/sync-wave: "-1"
spec:
  configuration:
    destinationPath: s3://homelab-longhorn-backup/cnpg/<b2-suffix>
    endpointURL: https://s3.eu-central-003.backblazeb2.com
    s3Credentials:
      accessKeyId:
        name: cnpg-backup-credentials
        key: ACCESS_KEY_ID
      secretAccessKey:
        name: cnpg-backup-credentials
        key: ACCESS_SECRET_KEY
    wal:
      compression: gzip
      maxParallel: 2
    data:
      compression: gzip
  retentionPolicy: <existing-retention>
```

`ObjectStore.spec.configuration.serverName` must remain unset. If a restore
needs an explicit archive/server name, set `serverName` in the plugin parameters
on the referencing `externalClusters` entry instead.

Replace the old `Cluster.spec.backup` section with:

```yaml
spec:
  plugins:
    - name: barman-cloud.cloudnative-pg.io
      isWALArchiver: true
      parameters:
        barmanObjectName: <cluster>-b2
```

Update the existing `ScheduledBackup` without changing its name, cluster,
ownership, `immediate`, or schedule:

```yaml
spec:
  method: plugin
  pluginConfiguration:
    name: barman-cloud.cloudnative-pg.io
```

Old `Backup` custom resources and B2 objects can remain. New backups use method
`plugin`; both generations refer to compatible Barman backup data.

## Phase 1: install prerequisites

The plugin requires CNPG 1.26 or newer and TLS between the operator and plugin.
The cluster had no `cert-manager` namespace or Barman `ObjectStore` CRD at the
2026-08-15 audit.

1. Add cert-manager as a pinned Argo CD application and wait for its controller,
   webhook, and CA injector to become Ready.
2. Add a pinned Barman Cloud Plugin application in `cnpg-system`, the same
   namespace as the CNPG operator.
3. Vendor or declaratively manage the release manifest. Before committing,
   verify every image and pin it as `tag@digest` using
   `scripts/resolve-container-image.py`; do not apply a floating remote
   `manifest.yaml` directly to the cluster.
4. Keep prerequisite installation in a separate commit from database cutover.

Verify:

```bash
kubectl get pods -n cert-manager
kubectl get deployment -n cnpg-system
kubectl get crd objectstores.barmancloud.cnpg.io
kubectl get certificates,issuers -n cnpg-system
```

Require all deployments Ready, the CRD established, and the plugin certificates
Ready before creating an `ObjectStore`.

## Phase 2: migrate a canary

Use `roundcube-db` as the canary: it is small and has a low-frequency workload.
Perform the cutover during the day, away from its scheduled backup.

1. Confirm the cluster is 2/2 Ready, on two nodes, and continuously archiving.
2. Confirm its newest scheduled backup completed.
3. Add the namespaced `ObjectStore`, update the `Cluster`, and update the
   `ScheduledBackup` in one reviewed Git change. Argo sync waves should create
   the `ObjectStore` before rolling the cluster and apply the scheduled-backup
   change last.
4. Watch both PostgreSQL pods roll and return Ready. Do not delete PVCs.

```bash
kubectl cnpg status roundcube-db -n roundcube --verbose
kubectl get cluster.postgresql.cnpg.io roundcube-db -n roundcube -w
kubectl get pods -n roundcube -l cnpg.io/cluster=roundcube-db -o wide
kubectl logs -n cnpg-system deployment/barman-cloud --tail=200
```

Require `ContinuousArchiving=True`, two Ready instances, a current primary, and
no archive failures. Then create one on-demand plugin backup:

```bash
kubectl cnpg backup -n roundcube roundcube-db \
  --method=plugin \
  --plugin-name=barman-cloud.cloudnative-pg.io
```

Wait for that `Backup` to reach `completed`. Inspect the sidecar logs on the
selected backup pod if it does not progress:

```bash
kubectl logs -n roundcube <pod> -c plugin-barman-cloud --tail=200
```

## Phase 3: prove recovery

A green backup is not proof that credentials, archive naming, and restore
configuration all agree. Restore the canary into a temporary cluster with a new
cluster name and new PVCs; never restore over the live cluster.

The recovery manifest must use an `externalClusters[].plugin` reference rather
than `externalClusters[].barmanObjectStore`:

```yaml
spec:
  bootstrap:
    recovery:
      source: roundcube-db-source
  externalClusters:
    - name: roundcube-db-source
      plugin:
        name: barman-cloud.cloudnative-pg.io
        parameters:
          barmanObjectName: roundcube-db-b2
          serverName: roundcube-db
```

Verify PostgreSQL accepts connections and the expected database exists. Record
the recovery point, then delete only the temporary recovery cluster and PVCs.

One canary restore plus one later restore of a critical cluster such as
`vaultwarden-db` is sufficient. Do not repeat an identical restore rehearsal for
all nine clusters; every cluster still needs its own completed plugin backup and
healthy WAL archive.

## Phase 4: migrate the remaining clusters

Proceed in small batches while CNPG remains at 1.30:

1. `tandoor-db`, `vikunja-db`, `paperless-db`
2. `stalwart-db`, `immich-db`
3. `homeassistant-db`
4. `vaultwarden-db`
5. `pocket-id-db`

For every cluster, repeat the preflight, rolling-update observation, archiving
check, and on-demand plugin backup. Stop the batch on the first archive, pod,
or backup failure. Home Assistant is the largest database; allow its base backup
several hours before declaring it stuck.

Do not change the Vikunja PostgreSQL image during this migration. The plugin
removes its need for an image containing in-tree Barman binaries, but switching
to a minimal image is a separate follow-up with separate rollback evidence.

## Rollback

Keep CNPG 1.30 installed throughout the migration. If the canary cannot archive
or complete a backup:

1. Stop and preserve plugin/operator/sidecar logs.
2. Revert that cluster's Git change: restore its previous `spec.backup` block
   and remove the plugin entry; restore the ScheduledBackup's prior method.
3. Let Argo reconcile and wait for the rolling update to finish.
4. Confirm native `ContinuousArchiving=True` and complete a native on-demand
   backup before retrying.

Do not remove the shared plugin or cert-manager while any cluster references
them. Do not upgrade to CNPG 1.31 as a troubleshooting step; native rollback is
unavailable there.

## Completion gates

The migration is complete only when:

- all nine clusters are 2/2 Ready with a primary and
  `ContinuousArchiving=True`;
- every cluster has a completed `method: plugin` backup created after cutover;
- the canary restore and one critical-database restore both succeeded;
- every `ScheduledBackup` explicitly uses the plugin and retains its six-field
  schedule;
- no active cluster or recovery example uses `barmanObjectStore`;
- backup monitoring recognizes the plugin metrics and Baloo's health check still
  evaluates the newest scheduled `Backup` correctly;
- the old restore examples in `config/postgres/README.md` and application
  documentation use plugin-based `externalClusters` configuration;
- CNPG 1.31 remains blocked until all preceding gates are recorded.

After the final migration, wait through the next normal scheduled-backup window
and check all nine newest backups again. Only then remove the operator-upgrade
block.
