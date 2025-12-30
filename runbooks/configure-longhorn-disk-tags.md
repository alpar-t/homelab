# Configure Longhorn Disk Tags

This runbook documents how to configure Longhorn disk tags for SSD and HDD storage classes after cluster recovery or node rebuild.

## Scenario

- **Problem**: `longhorn-ssd` or `longhorn-hdd` StorageClass fails to provision volumes
- **Error**: `specified disk tag ssd does not exist` or `specified disk tag hdd does not exist`
- **Cause**: Node was rebuilt/reinstalled and lost its Longhorn disk configuration

---

## Prerequisites

- SSH access to cluster nodes
- kubectl configured with cluster access
- Longhorn installed and running

---

## Step 1: Check Current Disk Configuration

View current disk tags on all nodes:

```bash
kubectl get nodes.longhorn.io -n longhorn-system -o json | \
    jq -r '.items[] | "\(.metadata.name):", (.spec.disks | to_entries[] | "  \(.key): \(.value.path) tags=\(.value.tags // [])")'
```

Expected output shows disks with appropriate tags:
```
buksi:
  default-disk-xxx: /var/mnt/disk1 tags=["hdd"]
  ssd-disk: /var/lib/longhorn-ssd tags=["ssd"]
pamacs:
  default-disk-xxx: /var/mnt/disk1 tags=["hdd"]
  ssd-disk: /var/lib/longhorn-ssd tags=["ssd"]
```

---

## Step 2: Create SSD Directories on Nodes

The SSD storage uses `/var/lib/longhorn-ssd` on each node's boot SSD. Create this directory:

```bash
# Check which nodes are missing the directory
for node in buksi pamacs pufi; do
    echo "=== $node ==="
    ssh core@$node.local "ls -la /var/lib/longhorn-ssd 2>/dev/null || echo 'Directory does not exist'"
done

# Create missing directories
ssh core@<node>.local "sudo mkdir -p /var/lib/longhorn-ssd"
```

---

## Step 3: Run the Tagging Script

Use the provided script to configure disk tags:

```bash
cd /path/to/homepbp
bash config/longhorn/tag-disks.sh
```

This script will:
1. Tag all `/var/mnt/*` disks as `hdd`
2. Add `/var/lib/longhorn-ssd` disk with `ssd` tag on each node

---

## Step 4: Verify Disk Status

Check that all disks are ready and schedulable:

```bash
# Check SSD disks
kubectl get nodes.longhorn.io -n longhorn-system -o json | \
    jq -r '.items[] | "\(.metadata.name): ssd-disk ready=\(.status.diskStatus["ssd-disk"].conditions[] | select(.type=="Ready") | .status)"'

# Expected output:
# buksi: ssd-disk ready=True
# pamacs: ssd-disk ready=True
# pufi: ssd-disk ready=True
```

If a disk shows `ready=False`, check:
1. Directory exists on the node
2. Directory has correct permissions (root:root)
3. Sufficient disk space available

---

## Manual Tagging (Alternative)

If you need to manually tag a specific disk:

### Tag existing disk as HDD:
```bash
kubectl -n longhorn-system patch nodes.longhorn.io <node-name> --type=json \
    -p='[{"op": "replace", "path": "/spec/disks/<disk-name>/tags", "value": ["hdd"]}]'
```

### Add new SSD disk:
```bash
kubectl -n longhorn-system patch nodes.longhorn.io <node-name> --type=merge -p='{
    "spec": {
        "disks": {
            "ssd-disk": {
                "allowScheduling": true,
                "evictionRequested": false,
                "path": "/var/lib/longhorn-ssd",
                "storageReserved": 0,
                "tags": ["ssd"]
            }
        }
    }
}'
```

---

## Storage Classes

The cluster uses two storage classes with disk selectors:

| StorageClass | Disk Tag | Replicas | Use Case |
|--------------|----------|----------|----------|
| `longhorn-ssd` | `ssd` | 2 | Databases, critical apps |
| `longhorn-hdd` | `hdd` | 3 | Media, backups, bulk storage |

These are defined in:
- `config/longhorn/storageclass-ssd.yaml`
- `config/longhorn/storageclass-hdd.yaml`

---

## Troubleshooting

### Disk not showing up after tagging

1. Check Longhorn manager logs:
   ```bash
   kubectl logs -n longhorn-system -l app=longhorn-manager --tail=50
   ```

2. Verify the node resource:
   ```bash
   kubectl get nodes.longhorn.io -n longhorn-system <node-name> -o yaml
   ```

### PVC stuck in Pending

1. Check if disk tag matches storage class:
   ```bash
   kubectl describe pvc <pvc-name> -n <namespace>
   ```

2. Look for scheduling errors:
   ```bash
   kubectl get volumes -n longhorn-system -o json | jq '.items[] | select(.status.state != "attached") | {name: .metadata.name, state: .status.state, robustness: .status.robustness}'
   ```

---

## Related

- [Longhorn Storage README](../config/longhorn/README.md)
- [Recover Cluster from Single Node](./recover-cluster-from-single-node.md)
- [Recover Longhorn Orphaned Volume](./recover-longhorn-orphaned-volume.md)

