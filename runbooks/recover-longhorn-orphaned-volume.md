# Recovering Data from Orphaned Longhorn Replicas

This runbook documents how to recover data from orphaned Longhorn replica directories when a PVC has been deleted but the underlying data still exists on disk.

**Reference:** [Longhorn KB - Restoring Data from an Orphaned Replica Directory](https://longhorn.io/kb/restoring-data-from-an-orphaned-replica-directory/)

## Overview

When Longhorn volumes are deleted (intentionally or accidentally), the replica data may remain on disk as "orphaned" data. Longhorn tracks these orphans and they're visible in the Longhorn UI under "Orphaned Data".

This runbook covers:
1. Finding orphaned replicas
2. Exporting them as block devices
3. Mounting and extracting data
4. Restoring to a live database (CNPG PostgreSQL example)

## Prerequisites

- SSH access to cluster nodes (`core@<node>.local`)
- `kubectl` access to the cluster
- Longhorn version (check with): `kubectl get daemonset -n longhorn-system -o jsonpath='{.items[0].spec.template.spec.containers[0].image}'`

---

## Step 1: Identify Orphaned Replicas

### Via Longhorn UI
Navigate to **Longhorn UI → Orphaned Data** to see all orphans.

### Via kubectl
```bash
kubectl get orphan -n longhorn-system -o jsonpath='{range .items[*]}{.spec.nodeID}{"\t"}{.spec.parameters.DiskPath}{"\t"}{.spec.parameters.DataName}{"\n"}{end}' | sort
```

Example output:
```
pamacs  /var/mnt/disk1           pvc-9a0faed2-2c8b-4a12-8f0b-c1841fb8c6ce-0b95d8cd
pufi    /var/lib/longhorn-ssd    pvc-9a0faed2-2c8b-4a12-8f0b-c1841fb8c6ce-8b4aa235
```

### Cross-reference with active PVCs
```bash
kubectl get pvc -A -o jsonpath='{range .items[*]}{.spec.volumeName}{"\t"}{.metadata.namespace}/{.metadata.name}{"\n"}{end}' | sort
```

If an orphan's PVC ID doesn't appear in the active PVCs list, it's truly orphaned data.

---

## Step 2: Check Replica Metadata

SSH to the node and check the `volume.meta` file:

```bash
ssh core@<node>.local "sudo cat /var/lib/longhorn-ssd/replicas/<replica-dir>/volume.meta"
```

Example output:
```json
{"Size":1073741824,"Head":"volume-head-002.img","Dirty":true,...}
```

The `Size` field shows the volume size in bytes (1073741824 = 1 GiB).

---

## Step 3: Export Replica as Block Device

Longhorn replicas use a snapshot chain (`.img` files). To access the data, you need to use the `longhorn-engine` container to merge the chain and expose it as a block device.

```bash
ssh core@<node>.local "sudo podman run -d \
  --name <volume-name>-recovery \
  --privileged \
  -v /path/to/replica:/volume \
  -v /dev:/host/dev \
  -v /proc:/host/proc \
  docker.io/longhornio/longhorn-engine:v1.8.1 \
  launch-simple-longhorn <volume-name> <size-in-bytes> tgt-blockdev"
```

**Important:** The arguments are `<volume-name> <size> <frontend>` (not the replica path - that's mounted as `/volume`).

Wait for the block device to appear:
```bash
ls -la /dev/longhorn/
```

---

## Step 4: Mount the Block Device

```bash
sudo mkdir -p /mnt/recovered-<volume-name>
sudo mount -o ro /dev/longhorn/<volume-name> /mnt/recovered-<volume-name>
ls -la /mnt/recovered-<volume-name>/
```

---

## Step 5: Recover PostgreSQL Data (CNPG)

For CloudNativePG databases, the data is in `/pgdata/` subdirectory.

### 5.1 Copy pgdata to a writable location

```bash
sudo mkdir -p /tmp/<db-name>-pgdata
sudo cp -a /mnt/recovered-<volume-name>/pgdata/* /tmp/<db-name>-pgdata/
sudo chown -R 999:999 /tmp/<db-name>-pgdata
```

### 5.2 Create minimal PostgreSQL config

CNPG configs reference controller-specific paths. Replace them with minimal working configs:

```bash
sudo bash -c 'cat > /tmp/<db-name>-pgdata/pg_hba.conf << EOF
local all all trust
host all all 0.0.0.0/0 trust
EOF'

sudo bash -c 'cat > /tmp/<db-name>-pgdata/postgresql.conf << EOF
listen_addresses = '"'"'*'"'"'
port = 5432
max_connections = 100
shared_buffers = 128MB
log_destination = '"'"'stderr'"'"'
logging_collector = off
EOF'

sudo rm -f /tmp/<db-name>-pgdata/custom.conf /tmp/<db-name>-pgdata/override.conf
```

### 5.3 Start a temporary PostgreSQL container

```bash
sudo podman run -d \
  --name <db-name>-pg-source \
  --privileged \
  -v /tmp/<db-name>-pgdata:/var/lib/postgresql/data \
  -e PGDATA=/var/lib/postgresql/data \
  -e POSTGRES_PASSWORD=recovery \
  -p 5433:5432 \
  docker.io/postgres:16
```

### 5.4 Verify data is accessible

```bash
sudo podman exec <db-name>-pg-source psql -U postgres -d <database> -c '\dt'
```

### 5.5 Dump and restore to live cluster

```bash
# Dump from recovered database
sudo podman exec <db-name>-pg-source pg_dump -U postgres -d <database> > /tmp/<database>.sql

# Find the CNPG primary
kubectl get cluster -n <namespace> <cluster-name> -o jsonpath='{.status.currentPrimary}'

# Restore to the primary pod
cat /tmp/<database>.sql | kubectl exec -i -n <namespace> <primary-pod> -c postgres -- psql -U postgres -d <database>
```

### 5.6 Verify restoration

```bash
kubectl exec -n <namespace> <primary-pod> -c postgres -- psql -U postgres -d <database> -c "SELECT * FROM <table> LIMIT 5;"
```

### 5.7 Restart the application

```bash
kubectl rollout restart deployment -n <namespace> <app-deployment>
```

---

## Step 6: Cleanup

```bash
# Stop and remove recovery containers
sudo podman rm -f <db-name>-pg-source <volume-name>-recovery

# Unmount recovered volume
sudo umount /mnt/recovered-<volume-name>

# Remove temporary files
sudo rm -rf /tmp/<db-name>-pgdata /mnt/recovered-<volume-name>
```

---

## Real-World Example: Pocket-ID Database Recovery (2025-12-30)

### Context
- Pocket-ID database PVC was deleted
- Old replicas remained as orphans on `pufi` at `/var/lib/longhorn-ssd/replicas/`
- Needed to recover user accounts and OIDC client configurations

### Orphaned Replicas Found
```
pufi:/var/lib/longhorn-ssd/replicas/
├── pvc-9a0faed2-2c8b-4a12-8f0b-c1841fb8c6ce-0b95d8cd   ← pocket-id-db-2 (primary)
├── pvc-9a0faed2-2c8b-4a12-8f0b-c1841fb8c6ce-8b4aa235   ← pocket-id-db-2 (primary)
├── pvc-0aed6f54-c087-42fa-b735-def47cd04db5-2a8995f5   ← pocket-id-db-1 (replica)
└── pvc-0aed6f54-c087-42fa-b735-def47cd04db5-52bba2b3   ← pocket-id-db-1 (replica)
```

### Recovery Commands Used

```bash
# 1. Export volume as block device
ssh core@pufi.local "sudo podman run -d \
  --name pocket-id-recovery \
  --privileged \
  -v /var/lib/longhorn-ssd/replicas/pvc-9a0faed2-2c8b-4a12-8f0b-c1841fb8c6ce-0b95d8cd:/volume \
  -v /dev:/host/dev \
  -v /proc:/host/proc \
  docker.io/longhornio/longhorn-engine:v1.8.1 \
  launch-simple-longhorn pocket-id-db-recovery 1073741824 tgt-blockdev"

# 2. Mount the recovered volume
ssh core@pufi.local "sudo mkdir -p /mnt/pocket-id-recovery && \
  sudo mount -o ro /dev/longhorn/pocket-id-db-recovery /mnt/pocket-id-recovery"

# 3. Copy pgdata and fix permissions
ssh core@pufi.local "sudo bash -c '
  mkdir -p /tmp/pocket-id-pgdata
  cp -a /mnt/pocket-id-recovery/pgdata/* /tmp/pocket-id-pgdata/
  chown -R 999:999 /tmp/pocket-id-pgdata
'"

# 4. Create minimal config (replace CNPG-specific settings)
ssh core@pufi.local "sudo bash -c '
echo \"local all all trust
host all all 0.0.0.0/0 trust\" > /tmp/pocket-id-pgdata/pg_hba.conf

echo \"listen_addresses = '\\''*'\\''
port = 5432
max_connections = 100
shared_buffers = 128MB
log_destination = '\\''stderr'\\''
logging_collector = off\" > /tmp/pocket-id-pgdata/postgresql.conf

rm -f /tmp/pocket-id-pgdata/custom.conf /tmp/pocket-id-pgdata/override.conf
'"

# 5. Start postgres container with recovered data
ssh core@pufi.local "sudo podman run -d \
  --name pocket-id-pg-source \
  --privileged \
  -v /tmp/pocket-id-pgdata:/var/lib/postgresql/data \
  -e PGDATA=/var/lib/postgresql/data \
  -e POSTGRES_PASSWORD=recovery \
  -p 5433:5432 \
  docker.io/postgres:16"

# 6. Verify tables exist
ssh core@pufi.local "sudo podman exec pocket-id-pg-source psql -U postgres -d pocketid -c '\dt'"

# 7. Dump database
ssh core@pufi.local "sudo podman exec pocket-id-pg-source pg_dump -U postgres -d pocketid > /tmp/pocketid.sql"

# 8. Copy dump locally
scp core@pufi.local:/tmp/pocketid.sql /tmp/pocketid.sql

# 9. Restore to live CNPG cluster (primary is pocket-id-db-2)
cat /tmp/pocketid.sql | kubectl exec -i -n pocket-id pocket-id-db-2 -c postgres -- psql -U postgres -d pocketid

# 10. Verify data restored
kubectl exec -n pocket-id pocket-id-db-2 -c postgres -- psql -U postgres -d pocketid -c "SELECT id, username, email FROM users;"

# 11. Restart Pocket-ID app
kubectl rollout restart deployment -n pocket-id pocket-id

# 12. Cleanup
ssh core@pufi.local "sudo podman rm -f pocket-id-pg-source pocket-id-recovery; \
  sudo umount /mnt/pocket-id-recovery; \
  sudo rm -rf /tmp/pocket-id-pgdata /mnt/pocket-id-recovery"
```

### Data Recovered
- 2 user accounts (alpar, kinga)
- 21 tables including OIDC clients, webauthn credentials, user groups
- All OAuth2 configurations preserved

---

## Troubleshooting

### "unsupported frontend type" error
The argument order for `launch-simple-longhorn` changed in v1.8.x. It's now:
```
launch-simple-longhorn <volume-name> <size-in-bytes> <frontend>
```
Not:
```
launch-simple-longhorn <volume-name> <size-in-bytes> <replica-path>
```

### CNPG postgres won't start - SSL/certificate errors
CNPG configs reference `/controller/certificates/` paths. Solution: Replace `postgresql.conf`, `pg_hba.conf`, and delete `custom.conf`/`override.conf`.

### CNPG postgres won't start - socket/log path errors  
Replace any `/controller/run` or `/controller/log` paths with standard paths like `/var/run/postgresql`.

### "cannot execute COPY during recovery" error
You're trying to restore to a replica pod. Find the primary:
```bash
kubectl get cluster -n <namespace> <cluster-name> -o jsonpath='{.status.currentPrimary}'
```

### Constraint already exists errors during restore
These are harmless - they occur when running the restore twice. The data was still inserted.

