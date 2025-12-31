# Migrate PostgreSQL Databases from Longhorn to Local Storage

This runbook documents migrating CloudNativePG PostgreSQL clusters from Longhorn distributed storage to local SSD storage.

## Why Migrate?

### The Redundancy Problem

With CloudNativePG + Longhorn, you have **double replication**:

| Layer | What It Does | Copies |
|-------|--------------|--------|
| **PostgreSQL** | 2 instances with streaming replication | 2 |
| **Longhorn** | 2 SSD replicas across nodes | 2 |
| **Total** | Up to 4 copies of every database page | 4 |

Plus CNPG's WAL archiving to B2 gives you off-site backups anyway.

### Benefits of Local Storage for Databases

| Benefit | Explanation |
|---------|-------------|
| **Simpler architecture** | Fewer moving parts, easier to debug |
| **Better performance** | No network overhead for storage I/O |
| **Lower latency** | Direct SSD access vs Longhorn's iSCSI layer |
| **Less resource usage** | No instance-manager pods, no storage network |
| **Still HA** | PostgreSQL replication handles node failures |
| **Still backed up** | CNPG WAL archiving to B2 continues working |

### When to Keep Longhorn

Keep Longhorn for applications that **don't manage their own replication**:
- Single-instance apps (Redis standalone, most app PVCs)
- Media storage (Immich photos, Paperless documents)
- Any app that expects "just a disk" without built-in HA

---

## Local Storage Provisioner Options

### Option 1: Rancher Local-Path Provisioner ✅ Recommended

| Pros | Cons |
|------|------|
| Simple, minimal, battle-tested | No volume expansion (must recreate PVC) |
| Single binary, tiny footprint | No built-in monitoring |
| Active community, widely used | Manual cleanup on node failure |
| Supports `WaitForFirstConsumer` | |

**Best for**: Homelabs, simple setups, databases with their own replication

### Option 2: OpenEBS LocalPV

| Pros | Cons |
|------|------|
| More features (quotas, monitoring) | More complex to install |
| Volume expansion support | Heavier resource footprint |
| Better observability | More components to maintain |
| LVM backend option | |

**Best for**: Production environments needing quotas or expansion

### Option 3: TopoLVM

| Pros | Cons |
|------|------|
| LVM-backed, thin provisioning | Requires LVM setup on nodes |
| Proper capacity tracking | More operational complexity |
| Volume expansion | Linux-specific |
| Snapshots via LVM | |

**Best for**: Environments already using LVM, need snapshots

### Option 4: Kubernetes Local Persistent Volumes (Manual)

| Pros | Cons |
|------|------|
| Built into Kubernetes | No dynamic provisioning |
| No extra components | Must pre-create PVs manually |
| Maximum control | Tedious for many volumes |

**Best for**: Small, static deployments (1-2 databases)

### Recommendation

For this homelab: **Rancher Local-Path Provisioner**
- PostgreSQL handles HA, so we don't need storage-level features
- Simplicity matches the homelab philosophy
- Can always migrate to something else later

---

## Prerequisites

### Disk Layout

Current setup per node:
```
SSD (256GB): CoreOS + /var/lib/rancher (k3s data)
HDD1 (2TB): Longhorn storage (/var/mnt/disk1)
HDD2 (2TB): Longhorn storage (/var/mnt/disk2)
```

We'll create a dedicated directory on the SSD for PostgreSQL local volumes.

### Verify CNPG Backups Are Working

Before migrating, ensure all databases have recent backups:

```bash
# List all PostgreSQL clusters
kubectl get clusters -A

# Check backup status for each cluster
for ns in pocket-id homeassistant immich paperless-ngx tandoor vaultwarden stalwart-mail roundcube onlyoffice; do
  echo "=== $ns ==="
  kubectl get backups -n $ns 2>/dev/null || echo "No backups found"
done

# Trigger a fresh backup for critical databases
kubectl cnpg backup pocket-id-db -n pocket-id
kubectl cnpg backup vaultwarden-db -n vaultwarden
```

---

## Step 1: Reserve SSD Space for Local PostgreSQL

### 1a. Create Local Storage Directory on Each Node

SSH to each node and create a dedicated directory:

```bash
for node in pufi buksi pamacs; do
  echo "=== Creating local-postgres directory on $node ==="
  ssh core@${node}.local "sudo mkdir -p /var/mnt/local-postgres && sudo chmod 755 /var/mnt/local-postgres"
done
```

**Why `/var/mnt/local-postgres`?**
- `/var` survives CoreOS upgrades
- Separate from Longhorn paths
- Easy to identify PostgreSQL data

### 1b. Limit Longhorn's SSD Usage (Optional but Recommended)

If you have SSDs configured in Longhorn, reserve space for local PostgreSQL by limiting Longhorn's disk allocation.

In the Longhorn UI (https://longhorn.newjoy.ro):
1. Go to **Node** tab
2. Click on a node
3. Edit the SSD disk
4. Set **Storage Reserved** to leave room for PostgreSQL (e.g., 20Gi)

Or via kubectl:

```bash
# Get current disk config
kubectl get nodes.longhorn.io -n longhorn-system pufi -o yaml

# Patch to add reserved space (example - adjust disk name as needed)
kubectl patch nodes.longhorn.io pufi -n longhorn-system --type=merge -p '
{
  "spec": {
    "disks": {
      "ssd-disk-name": {
        "storageReserved": 21474836480
      }
    }
  }
}'
```

**Estimated space needed per database:**

| Database | Current Size | Recommended Local Allocation |
|----------|--------------|------------------------------|
| pocket-id-db | ~100MB | 2Gi |
| vaultwarden-db | ~200MB | 2Gi |
| homeassistant-db | ~2GB | 25Gi |
| immich-db | ~1GB | 15Gi |
| paperless-ngx-db | ~500MB | 5Gi |
| tandoor-db | ~100MB | 2Gi |
| stalwart-mail-db | ~200MB | 5Gi |
| roundcube-db | ~100MB | 2Gi |
| onlyoffice-db | ~100MB | 2Gi |
| **Total** | ~5GB | **~60Gi** |

Reserve at least 60Gi on each node's SSD (PostgreSQL replicas can land on any node).

---

## Step 2: Install Local-Path Provisioner

### 2a. Create ArgoCD Application

```bash
cat > /Users/alpar/Work/github/homepbp/apps/local-path-provisioner.yaml << 'EOF'
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: local-path-provisioner
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/rancher/local-path-provisioner.git
    targetRevision: v0.0.30
    path: deploy/chart/local-path-provisioner
    helm:
      valuesObject:
        storageClass:
          # We create our own StorageClass
          create: false
        nodePathMap:
          - node: DEFAULT_PATH_FOR_NON_LISTED_NODES
            paths:
              - /var/mnt/local-postgres
  destination:
    server: https://kubernetes.default.svc
    namespace: local-path-storage
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
EOF
```

### 2b. Create Local SSD StorageClass

```bash
mkdir -p /Users/alpar/Work/github/homepbp/config/local-path-provisioner/manifests

cat > /Users/alpar/Work/github/homepbp/config/local-path-provisioner/manifests/storageclass-local-ssd.yaml << 'EOF'
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-ssd
  annotations:
    storageclass.kubernetes.io/is-default-class: "false"
provisioner: rancher.io/local-path
reclaimPolicy: Delete
# CRITICAL: WaitForFirstConsumer ensures PV is created on same node as pod
volumeBindingMode: WaitForFirstConsumer
parameters:
  nodePath: /var/mnt/local-postgres
EOF
```

### 2c. Create README

```bash
cat > /Users/alpar/Work/github/homepbp/config/local-path-provisioner/README.md << 'EOF'
# Local-Path Provisioner

Provides local SSD storage for applications that manage their own replication (PostgreSQL, Redis Cluster, etc.).

## Why Local Storage for Databases?

When an application handles its own HA/replication (like CloudNativePG), adding Longhorn's distributed storage creates redundant complexity:
- Double replication (app + storage layer)
- More failure modes
- Network overhead for storage I/O

Local storage is simpler and faster for these workloads.

## Storage Path

All local volumes are created under `/var/mnt/local-postgres` on each node.

## StorageClass

- **`local-ssd`**: Local NVMe/SSD storage for PostgreSQL and similar workloads

## Important: volumeBindingMode

The `WaitForFirstConsumer` binding mode is critical:
- PV is created on the **same node** where the pod is scheduled
- Pod and data always stay together
- If a node dies, the data on that node is unavailable (but PostgreSQL replica takes over)

## Node Preparation

Each node must have the local storage directory:

```bash
for node in pufi buksi pamacs; do
  ssh core@${node}.local "sudo mkdir -p /var/mnt/local-postgres"
done
```

## Related

- [migrate-postgres-to-local-storage.md](../../runbooks/migrate-postgres-to-local-storage.md) - Migration runbook
- CloudNativePG handles database replication
EOF
```

### 2d. Add to Root Application (if using app-of-apps pattern)

If your `root-application.yaml` discovers apps automatically from the `apps/` directory, the new application will be picked up. Otherwise, add it manually.

### 2e. Commit and Sync

```bash
cd /Users/alpar/Work/github/homepbp
git add apps/local-path-provisioner.yaml config/local-path-provisioner/
git commit -m "Add local-path-provisioner for PostgreSQL local storage"
git push

# Wait for ArgoCD to sync, or force sync
argocd app sync local-path-provisioner
```

### 2f. Verify Installation

```bash
# Check provisioner is running
kubectl get pods -n local-path-storage

# Check StorageClass exists
kubectl get storageclass local-ssd
```

---

## Step 3: Migrate Databases

### Migration Strategy

We use CNPG's **recovery from backup** feature:
1. Old cluster continues running (no downtime yet)
2. Create new cluster that bootstraps from B2 backup
3. New cluster catches up via WAL replay
4. Cut over application to new cluster
5. Delete old cluster

### 3a. Example: Migrate pocket-id-db

**Step 1: Ensure backup is current**

```bash
kubectl cnpg backup pocket-id-db -n pocket-id
# Wait for backup to complete
kubectl get backups -n pocket-id -w
```

**Step 2: Create new cluster manifest**

The key changes are:
- Bootstrap using `recovery` instead of `initdb`
- Reference the B2 backup as external cluster
- Use `local-ssd` storageClass

```yaml
# config/pocket-id/manifests/postgres-cluster.yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: pocket-id-db
  namespace: pocket-id
  labels:
    app: pocket-id
    data-criticality: critical
spec:
  instances: 2
  imageName: ghcr.io/cloudnative-pg/postgresql:16
  
  # MIGRATION: Bootstrap from existing B2 backup
  bootstrap:
    recovery:
      source: pocket-id-db-backup
  
  # External cluster pointing to existing B2 backups
  externalClusters:
    - name: pocket-id-db-backup
      barmanObjectStore:
        destinationPath: "s3://homelab-longhorn-backup/cnpg/pocket-id-db"
        endpointURL: "https://s3.eu-central-003.backblazeb2.com"
        s3Credentials:
          accessKeyId:
            name: cnpg-backup-credentials
            key: ACCESS_KEY_ID
          secretAccessKey:
            name: cnpg-backup-credentials
            key: SECRET_ACCESS_KEY
        wal:
          maxParallel: 2
  
  # CHANGED: Use local SSD instead of Longhorn
  storage:
    size: 2Gi
    storageClass: local-ssd
  
  resources:
    requests:
      memory: "128Mi"
      cpu: "50m"
    limits:
      memory: "256Mi"
      cpu: "500m"
  
  # Continue backing up to B2 (same destination)
  backup:
    barmanObjectStore:
      destinationPath: "s3://homelab-longhorn-backup/cnpg/pocket-id-db"
      endpointURL: "https://s3.eu-central-003.backblazeb2.com"
      s3Credentials:
        accessKeyId:
          name: cnpg-backup-credentials
          key: ACCESS_KEY_ID
        secretAccessKey:
          name: cnpg-backup-credentials
          key: SECRET_ACCESS_KEY
      wal:
        compression: gzip
        maxParallel: 2
      data:
        compression: gzip
    retentionPolicy: "30d"
  
  postgresql:
    parameters:
      log_statement: "ddl"
      log_min_duration_statement: "1000"
      shared_buffers: "64MB"
      work_mem: "4MB"
      max_connections: "50"
      archive_mode: "on"
      archive_timeout: "5min"
```

**Step 3: Delete old cluster and apply new manifest**

```bash
# Scale down application to prevent writes during migration
kubectl scale deployment pocket-id -n pocket-id --replicas=0

# Delete old cluster (Longhorn PVCs will remain until manually deleted)
kubectl delete cluster pocket-id-db -n pocket-id

# Wait for pods to terminate
kubectl get pods -n pocket-id -w

# Apply new cluster manifest
kubectl apply -f config/pocket-id/manifests/postgres-cluster.yaml

# Watch recovery progress
kubectl get cluster pocket-id-db -n pocket-id -w

# Check logs for recovery status
kubectl logs -n pocket-id -l cnpg.io/cluster=pocket-id-db -f
```

**Step 4: Verify and restore application**

```bash
# Check cluster is healthy
kubectl get cluster pocket-id-db -n pocket-id
# Should show: instances=2, ready=2

# Scale application back up
kubectl scale deployment pocket-id -n pocket-id --replicas=1

# Verify application connects
kubectl logs -n pocket-id -l app=pocket-id -f
```

**Step 5: Clean up old Longhorn PVCs**

```bash
# List orphaned PVCs
kubectl get pvc -n pocket-id

# Delete old Longhorn PVCs (names will be like pocket-id-db-1, pocket-id-db-2)
kubectl delete pvc pocket-id-db-1 pocket-id-db-2 -n pocket-id
```

### 3b. Migration Order

Migrate in order of criticality (least critical first for practice):

1. **tandoor-db** - Recipe app, easy to restore
2. **roundcube-db** - Webmail, low usage
3. **onlyoffice-db** - Document server
4. **paperless-ngx-db** - Document management
5. **stalwart-mail-db** - Mail server (test carefully)
6. **homeassistant-db** - Home automation history
7. **immich-db** - Photo metadata (uses pgvecto.rs extension - see note below)
8. **vaultwarden-db** - Password manager (critical - extra careful)
9. **pocket-id-db** - Identity provider (critical - extra careful)

### 3c. Special Case: Immich (pgvecto.rs)

Immich uses a custom PostgreSQL image with the pgvecto.rs extension. The migration process is the same, but ensure you use the correct image:

```yaml
imageName: ghcr.io/tensorchord/cloudnative-pgvecto.rs:16-v0.3.0
```

---

## Step 4: Post-Migration Cleanup

### Remove Longhorn SSD Storage Class (Optional)

Once all databases are migrated, you can remove the `longhorn-ssd` StorageClass to prevent accidental use:

```bash
# Check nothing is using it
kubectl get pvc -A -o jsonpath='{range .items[?(@.spec.storageClassName=="longhorn-ssd")]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}'

# If empty, safe to delete
kubectl delete storageclass longhorn-ssd
```

### Update Documentation

Update `config/postgres/README.md` to reflect the new storage strategy.

---

## Rollback

If migration fails, you can restore from the same B2 backup to a new Longhorn-backed cluster:

```bash
# Delete the failed local-storage cluster
kubectl delete cluster <name> -n <namespace>

# Restore original manifest (from git) with Longhorn storage
git checkout config/<app>/manifests/postgres-cluster.yaml
kubectl apply -f config/<app>/manifests/postgres-cluster.yaml
```

---

## Verification Checklist

After migrating each database:

- [ ] Cluster shows `instances=2, ready=2`
- [ ] Application connects and functions normally
- [ ] New backup completes successfully to B2
- [ ] Old Longhorn PVCs deleted
- [ ] Local storage directory shows data: `ssh core@node.local "ls /var/mnt/local-postgres"`

---

## Troubleshooting

### Recovery takes too long

Large databases may take time to restore. Check progress:

```bash
kubectl logs -n <namespace> -l cnpg.io/cluster=<cluster-name> --tail=100
```

### "No backup found" error

Ensure the B2 path matches exactly:
```bash
# Check what's in B2
aws s3 ls s3://homelab-longhorn-backup/cnpg/ --endpoint-url https://s3.eu-central-003.backblazeb2.com
```

### Pod stuck in Pending (no node has capacity)

Check node storage:
```bash
for node in pufi buksi pamacs; do
  echo "=== $node ==="
  ssh core@${node}.local "df -h /var/mnt/local-postgres"
done
```

### Application can't connect after migration

Service names remain the same (`<cluster>-rw`, `<cluster>-ro`), but verify:
```bash
kubectl get svc -n <namespace>
```

---

## Related

- [config/postgres/README.md](../config/postgres/README.md) - PostgreSQL architecture
- [config/local-path-provisioner/README.md](../config/local-path-provisioner/README.md) - Local storage setup
- [recover-cluster-from-single-node.md](./recover-cluster-from-single-node.md) - Cluster recovery

