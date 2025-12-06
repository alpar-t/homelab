# Longhorn Storage

Distributed block storage for Kubernetes using local HDDs on each node.

## Prerequisites

Each node needs storage disks mounted before Longhorn can use them.

### 1. Check disk layout on each node

```bash
for node in pufi buksi pamacs; do
  echo "=== $node ==="
  ssh core@${node}.local "lsblk -o NAME,SIZE,TYPE,FSTYPE,LABEL,MODEL"
done
```

Identify which disks are available for Longhorn (not the OS disk).

### 2. Run the setup script on each node

Copy and run the script:

```bash
# For each node
scp config/longhorn/setup-node-storage.sh core@pufi.local:/tmp/
ssh core@pufi.local "sudo DISK1=/dev/sda DISK2=/dev/sdb /tmp/setup-node-storage.sh"

# Repeat for other nodes (adjust DISK1/DISK2 if different)
scp config/longhorn/setup-node-storage.sh core@buksi.local:/tmp/
ssh core@buksi.local "sudo DISK1=/dev/sda DISK2=/dev/sdb /tmp/setup-node-storage.sh"

scp config/longhorn/setup-node-storage.sh core@pamacs.local:/tmp/
ssh core@pamacs.local "sudo DISK1=/dev/sda DISK2=/dev/sdb /tmp/setup-node-storage.sh"
```

### 3. Verify mounts

```bash
for node in pufi buksi pamacs; do
  echo "=== $node ==="
  ssh core@${node}.local "df -h /var/mnt/disk1 /var/mnt/disk2"
done
```

## Deployment

Longhorn is deployed via ArgoCD from `apps/longhorn.yaml`.

After ArgoCD syncs, configure Longhorn to use both disks on each node:

```bash
for node in pufi buksi pamacs; do
  kubectl label node $node node.longhorn.io/create-default-disk=config
  kubectl annotate node $node node.longhorn.io/default-disks-config='[{"path":"/var/mnt/disk1","allowScheduling":true},{"path":"/var/mnt/disk2","allowScheduling":true}]'
done
```

## Configuration

Helm values are in `config/longhorn/values.yaml`. Key settings:

- `defaultClassReplicaCount: 3` - Each volume has 3 replicas (one per node)
- `defaultDataPath: /var/mnt/disk1` - Default storage location
- `replicaAutoBalance: best-effort` - Automatically balance replicas across nodes

## Accessing the UI

Port-forward the Longhorn frontend:

```bash
kubectl port-forward -n longhorn-system svc/longhorn-frontend 8080:80
```

Then open http://localhost:8080

