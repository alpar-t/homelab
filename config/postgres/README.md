# PostgreSQL - Cloud-Native Database Infrastructure

PostgreSQL databases managed by CloudNativePG operator with single-tenant clusters per application.

## Architecture Decision

### Single-Tenant vs Multi-Tenant

We use **single-tenant clusters** (one PostgreSQL cluster per application) rather than a shared multi-tenant instance.

| Approach | Pros | Cons |
|----------|------|------|
| **Single-Tenant** ✅ | Isolation, independent upgrades, per-app tuning, simpler backup/restore | More resources, more clusters to manage |
| **Multi-Tenant** | Resource efficient, fewer clusters | Blast radius (one bad migration affects all), manual user management, shared upgrades |

**Why single-tenant works for us:**
- **64GB total RAM** (16GB + 16GB + 32GB across 3 nodes) — plenty of headroom
- **Estimated usage**: ~3-4GB for all database clusters combined
- **Isolation benefits**: A bad Immich migration won't take down Bitwarden
- **Operator handles everything**: Database, user, and password creation automated
- **Cleaner GitOps**: Each app owns its database configuration

### Hardware

| Node | Model | RAM | Storage |
|------|-------|-----|---------|
| Node 1 | Odroid H3+ | 16GB | SSD + 2x HDD |
| Node 2 | Odroid H3+ | 16GB | SSD + 2x HDD |
| Node 3 | Odroid H3 Ultra | 32GB | SSD + 2x HDD |

### Storage

**Recommended: Local SSD storage** (`local-ssd` storage class)
- CloudNativePG handles replication at the database level
- Local storage provides better performance (no network overhead)
- Simpler architecture with fewer failure modes
- See [runbooks/migrate-postgres-to-local-storage.md](../../runbooks/migrate-postgres-to-local-storage.md) for migration guide

**Legacy: Longhorn SSD storage** (`longhorn-ssd` storage class)
- Provides storage-level replication
- **Redundant** when combined with CNPG's database replication
- Migration to local storage recommended

## Cluster Sizing

| App | Instances | Memory Request | Memory Limit | Notes |
|-----|-----------|----------------|--------------|-------|
| Nextcloud | 2 | 512Mi | 1Gi | Primary + replica, heavy usage |
| Immich | 2 | 512Mi | 1Gi | Write-heavy (photo ingestion) |
| Bitwarden | 2 | 256Mi | 512Mi | Critical app, must be reliable |
| Paperless | 2 | 256Mi | 512Mi | Light usage |
| Tandoor | 1-2 | 256Mi | 512Mi | Very light usage |
| Authentik | 2 | 256Mi | 512Mi | Auth system, needs HA |

## CloudNativePG Operator

### Installation

The operator is installed via ArgoCD application. See `apps/cloudnativepg.yaml`.

### Features Used

- **Automatic failover**: Primary failure promotes replica
- **Rolling updates**: Zero-downtime minor version upgrades
- **In-place major upgrades**: Uses `pg_upgrade` (with downtime)
- **Connection pooling**: Built-in PgBouncer support
- **Monitoring**: Prometheus metrics exposed

## Per-App Database Setup

Each application that needs PostgreSQL gets its own `Cluster` CR in its config directory:

```
config/
├── nextcloud/
│   └── manifests/
│       └── postgres-cluster.yaml
├── immich/
│   └── manifests/
│       └── postgres-cluster.yaml
└── ...
```

### Example Cluster Definition

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: nextcloud-db
  namespace: nextcloud
spec:
  instances: 2
  
  imageName: ghcr.io/cloudnative-pg/postgresql:16
  
  bootstrap:
    initdb:
      database: nextcloud
      owner: nextcloud
      secret:
        name: nextcloud-db-credentials
  
  storage:
    size: 10Gi
    storageClass: longhorn-ssd
  
  resources:
    requests:
      memory: "512Mi"
      cpu: "200m"
    limits:
      memory: "1Gi"
      cpu: "2"
  
  affinity:
    tolerations: []
    # Instances spread across nodes automatically
```

### Credentials Secret

Create before deploying the cluster:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: nextcloud-db-credentials
  namespace: nextcloud
type: kubernetes.io/basic-auth
stringData:
  username: nextcloud
  password: <generate-strong-password>
```

Or use a Job to auto-generate (see `config/authentik/manifests/secrets-job.yaml` for pattern).

## Connecting Applications

### Connection String

```
postgresql://<user>:<password>@<cluster-name>-rw.<namespace>.svc.cluster.local:5432/<database>
```

Example for Nextcloud:
```
postgresql://nextcloud:${PASSWORD}@nextcloud-db-rw.nextcloud.svc.cluster.local:5432/nextcloud
```

### Service Names

CloudNativePG creates three services per cluster:

| Service | Purpose | Use Case |
|---------|---------|----------|
| `<cluster>-rw` | Read-write (primary) | Application writes |
| `<cluster>-ro` | Read-only (replicas) | Read scaling |
| `<cluster>-r` | Any instance | Admin access |

## Backup Strategy

We use **CNPG-native backups** with WAL archiving to Backblaze B2.

### What CNPG Provides

| Feature | How It Helps |
|---------|--------------|
| **Continuous WAL archiving** | Point-in-time recovery to any moment |
| **Base backups to B2** | Full database snapshots (daily/weekly) |
| **Retention policies** | Automatic cleanup of old backups |
| **Recovery bootstrap** | New clusters can restore from any backup |

### Why CNPG Backups Over Longhorn?

| Approach | Pros | Cons |
|----------|------|------|
| **CNPG to B2** ✅ | Database-aware, PITR, cross-version restore | Requires B2 credentials |
| **Longhorn snapshots** | Simple, works for any PVC | Not database-aware, no PITR |

CNPG backups are **database-aware** — they understand PostgreSQL's WAL format and can restore to any point in time, not just snapshot moments.

### Backup Configuration

Each cluster specifies its backup policy:

```yaml
backup:
  barmanObjectStore:
    destinationPath: "s3://homelab-longhorn-backup/cnpg/<cluster-name>"
    endpointURL: "https://s3.eu-central-003.backblazeb2.com"
    # ... credentials ...
  retentionPolicy: "14d"  # or "30d" for critical apps
```

### Backup Schedules by Application

| App | Base Backup Frequency | Retention | Rationale |
|-----|----------------------|-----------|-----------|
| pocket-id-db | Weekly | 30 days | Identity data - critical |
| vaultwarden-db | Weekly | 30 days | Passwords - critical |
| immich-db | Daily | 14 days | Photo metadata - valuable |
| homeassistant-db | Weekly | 14 days | Sensor history - replaceable |
| paperless-ngx-db | Weekly | 14 days | Document metadata |
| Others | Weekly | 14 days | Standard |

### Manual Backup

Trigger a backup before maintenance:

```bash
kubectl cnpg backup <cluster-name> -n <namespace>
```

### Critical Apps: Extra Protection

For **Vaultwarden**: Export your vault periodically (built-in feature).
This protects against scenarios where corruption goes unnoticed.

### Alternative: Logical Backups (Optional)

If you later want extra protection, `pg_dump` CronJobs can be added. They provide:
- Cross-version restore capability
- Human-readable backups
- Individual table recovery

See git history for example CronJob manifest if needed.

## Updates and Maintenance

### Minor Version Updates

CloudNativePG handles automatically with rolling restart:

```yaml
spec:
  imageName: ghcr.io/cloudnative-pg/postgresql:16.2  # Update version
```

The operator will:
1. Update replica first
2. Promote replica to primary
3. Update old primary (now replica)

**Downtime**: ~1-2 seconds during failover

### Major Version Updates

CloudNativePG supports **in-place major upgrades** using `pg_upgrade`:

```yaml
# Simply update the image tag
spec:
  imageName: ghcr.io/cloudnative-pg/postgresql:16  # was :15
```

The operator will:
1. Shut down all pods (primary + replicas)
2. Run `pg_upgrade` on the data
3. Restart cluster with new version

**Important:**
- **Downtime required** — entire cluster unavailable during upgrade (typically minutes)
- **Snapshot first** — always take a Longhorn snapshot before upgrading
- **Check extensions** — verify your extensions are compatible with new version

**Downtime**: Minutes (depends on database size)

### Vacuum and Maintenance

PostgreSQL autovacuum handles routine maintenance. For manual intervention:

```bash
# Connect to primary
kubectl exec -it nextcloud-db-1 -n nextcloud -- psql -U postgres

# Check vacuum status
SELECT schemaname, relname, last_vacuum, last_autovacuum 
FROM pg_stat_user_tables;

# Manual vacuum if needed
VACUUM ANALYZE;
```

## Monitoring

### Prometheus Metrics

CloudNativePG exposes metrics on port 9187:

```yaml
# ServiceMonitor (if using Prometheus Operator)
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: cnpg-clusters
spec:
  selector:
    matchLabels:
      cnpg.io/cluster: "*"
  endpoints:
  - port: metrics
```

### Key Metrics to Alert On

| Metric | Alert Threshold | Meaning |
|--------|-----------------|---------|
| `cnpg_pg_replication_lag` | > 30s | Replica falling behind |
| `cnpg_pg_database_size_bytes` | > 80% of PVC | Running out of space |
| `pg_stat_activity_count` | > 80% of max_connections | Connection exhaustion |

## Disaster Recovery

### Scenario: Single Node Failure

**Automatic**: CloudNativePG promotes the replica to primary. No data loss (streaming replication is synchronous by default for 2-instance clusters).

With **local storage**: The failed node's database instance is unavailable until the node recovers. The promoted replica handles all traffic.

With **Longhorn**: Same behavior, but Longhorn also rebuilds volume replicas (unnecessary overhead).

### Scenario: Complete Cluster Loss

1. Rebuild Kubernetes cluster (see `genesis/README.md`)
2. Restore Kubernetes secrets (from Velero or manual backup)
3. Deploy Cluster CRs with `bootstrap.recovery` pointing to B2 backups
4. Clusters restore automatically from B2

Example recovery bootstrap:
```yaml
bootstrap:
  recovery:
    source: backup-source
externalClusters:
  - name: backup-source
    barmanObjectStore:
      destinationPath: "s3://homelab-longhorn-backup/cnpg/<cluster-name>"
      # ... B2 credentials ...
```

### Scenario: Database Corruption

1. Stop application (prevent further writes)
2. Identify point-in-time before corruption
3. Delete cluster and recreate with recovery target:

```yaml
bootstrap:
  recovery:
    source: backup-source
    recoveryTarget:
      targetTime: "2024-12-30 10:00:00"  # Before corruption
```

### Scenario: Accidental Data Deletion

Same as corruption — use PITR to recover to moment before deletion.

## Troubleshooting

```bash
# Check cluster status
kubectl get clusters -A

# Describe cluster for events
kubectl describe cluster nextcloud-db -n nextcloud

# Check pod logs
kubectl logs nextcloud-db-1 -n nextcloud

# Connect to database
kubectl exec -it nextcloud-db-1 -n nextcloud -- psql -U postgres

# Check replication status
kubectl exec -it nextcloud-db-1 -n nextcloud -- psql -U postgres -c "SELECT * FROM pg_stat_replication;"
```

## External Access

Some applications outside the Kubernetes cluster (e.g., Home Assistant Green) need to connect to PostgreSQL.

### Options

| Method | Use Case |
|--------|----------|
| **LoadBalancer (MetalLB)** | Clean IP on standard port 5432 |
| **NodePort** | Simple, no extra components needed |

See `config/homeassistant/README.md` for a complete example with MetalLB.

### MetalLB Overview

MetalLB provides LoadBalancer IPs for bare-metal Kubernetes. In Layer 2 mode:
1. You define a pool of LAN IPs (outside DHCP range)
2. MetalLB assigns IPs from the pool to LoadBalancer services
3. MetalLB responds to ARP requests, routing traffic to cluster

See `config/metallb/README.md` for installation and configuration.

## Future Considerations

- [ ] Configure Prometheus/Grafana dashboards for database monitoring
- [ ] Test major version upgrade procedure on non-critical database first
- [ ] Consider PgBouncer for connection pooling if apps create many connections
- [ ] Add pg_dump CronJobs if extra corruption protection desired

