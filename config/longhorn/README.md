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

Copy and run the script. It auto-discovers available disks (skips root device and mounted disks):

```bash
# Copy script to all nodes
for node in pufi buksi pamacs; do
  scp config/longhorn/setup-node-storage.sh core@${node}.local:/tmp/
done

# Run with auto-discovery (recommended):
ssh -t core@pufi.local "sudo /tmp/setup-node-storage.sh"

# Or specify disks manually:
ssh -t core@pufi.local "sudo DISK1=/dev/sda DISK2=/dev/sdb /tmp/setup-node-storage.sh"
```

The script will show discovered disks and ask for confirmation before formatting.

### 3. Verify mounts

```bash
for node in pufi buksi pamacs; do
  echo "=== $node ==="
  ssh core@${node}.local "df -h /var/mnt/disk1 /var/mnt/disk2"
done
```

## Deployment

Longhorn is deployed via ArgoCD from `apps/longhorn.yaml`.

After ArgoCD syncs, configure Longhorn to use the disks on each node:

```bash
# For nodes with two disks:
kubectl label node <node> node.longhorn.io/create-default-disk=config
kubectl annotate node <node> node.longhorn.io/default-disks-config='[{"path":"/var/mnt/disk1","allowScheduling":true},{"path":"/var/mnt/disk2","allowScheduling":true}]'

# For nodes with one disk:
kubectl label node <node> node.longhorn.io/create-default-disk=config
kubectl annotate node <node> node.longhorn.io/default-disks-config='[{"path":"/var/mnt/disk1","allowScheduling":true}]'
```

## Configuration

Helm values are in `config/longhorn/values.yaml`. Key settings:

- `defaultClassReplicaCount: 3` - Each volume has 3 replicas (one per node)
- `defaultDataPath: /var/mnt/disk1` - Default storage location
- `replicaAutoBalance: best-effort` - Automatically balance replicas across nodes
- `storageNetwork: longhorn-system/longhorn-storage-network` - Dedicated network for replica traffic

## Storage Network

Longhorn uses a dedicated storage network (`enp1s0` / 192.168.42.0/24) for replica traffic, keeping it separate from the management network (`enp2s0` / 192.168.1.0/24).

**IP Assignment:** Uses `whereabouts` IPAM (range: 192.168.42.20-190) for cluster-wide IP coordination.

### Why whereabouts?

| IPAM Type | How it works | Problem |
|-----------|--------------|---------|
| DHCP | External server assigns IPs | Lease expiration causes pod failures |
| host-local | Each node assigns from same range | Different nodes can assign same IP → conflict |
| **whereabouts** | Stores allocations in K8s CRDs | ✓ Cluster-wide coordination, no conflicts |

This requires:
1. **Multus CNI** - Installed via `apps/multus.yaml`
2. **Whereabouts** - Installed via `apps/whereabouts.yaml`
3. **NetworkAttachmentDefinition** - Defined in `config/longhorn/manifests/storage-network.yaml`

### How it works

- Multus enables pods to have multiple network interfaces
- Longhorn's instance-manager pods get an additional interface on the storage network
- Replica synchronization traffic flows through this dedicated network
- Management/API traffic continues to use the default cluster network

### Verifying storage network is working

Check that instance-manager pods have the storage network annotation:

```bash
kubectl get pods -n longhorn-system -l longhorn.io/component=instance-manager -o jsonpath='{range .items[*]}{.metadata.name}: {.metadata.annotations.k8s\.v1\.cni\.cncf\.io/networks}{"\n"}{end}'
```

Check traffic on the storage interface (should show significant RX/TX):

```bash
for node in pufi buksi pamacs; do
  echo "=== $node ==="
  ssh core@${node}.local "ip -s link show enp1s0 | head -8"
done
```

### Troubleshooting

If instance-manager pods fail to start after enabling storage network:

```bash
# Check pod events
kubectl describe pods -n longhorn-system -l longhorn.io/component=instance-manager

# Verify Multus is running
kubectl get pods -n kube-system -l app=multus

# Verify NetworkAttachmentDefinition exists
kubectl get net-attach-def -n longhorn-system
```

References:
- [Longhorn Storage Network docs](https://longhorn.io/docs/1.10.1/advanced-resources/deploy/storage-network/)
- [Multus CNI](https://github.com/k8snetworkplumbingwg/multus-cni)

## Backups

Longhorn backs up all volumes to Backblaze B2. Backup configuration is in `config/longhorn/manifests/`.

### Backup Schedule

| Job | Schedule | Retention | Applies To |
|-----|----------|-----------|------------|
| `weekly-backup` | Sunday 3:00 AM | 8 weeks | **ALL volumes** (automatic) |
| `critical-daily-backup` | Daily 2:00 AM | 21 days | Volumes with `critical` label |

### Mark a Volume as Critical

To enable daily backups for important volumes (databases, etc.):

```bash
# Find the Longhorn volume name from the PVC
VOLUME=$(kubectl get pv -o jsonpath='{.items[?(@.spec.claimRef.name=="<pvc-name>")].spec.csi.volumeHandle}')

# Add the critical label to the Longhorn volume
kubectl -n longhorn-system label volume/$VOLUME recurring-job-group.longhorn.io/critical=enabled
```

### Exclude a Volume from Backups (GitOps)

To exclude a volume from weekly backups, add it to `config/longhorn/manifests/backup-exclusions.yaml`:

```yaml
data:
  excluded-pvcs: |
    frigate/frigate-media
    some-namespace/some-pvc-name
```

The Job runs as an ArgoCD PostSync hook and applies the label `recurring-job.longhorn.io/weekly-backup=disabled` to the Longhorn volumes.

**Currently excluded:**
- `frigate/frigate-media` - large recordings, not critical

**Note:** PVC labels don't propagate to Longhorn Volume objects, which is why we use a Job.

### Verify Backups Are Running

```bash
# Check recurring jobs exist
kubectl get recurringjobs -n longhorn-system

# Check backup status for all volumes
kubectl get backups -n longhorn-system

# Check recent backup activity in Longhorn manager logs
kubectl logs -n longhorn-system -l app=longhorn-manager --tail=100 | grep -i backup

# List volumes and their recurring job labels
kubectl get volumes -n longhorn-system -o custom-columns='NAME:.metadata.name,DEFAULT:.metadata.labels.recurring-job\.longhorn\.io/default,CRITICAL:.metadata.labels.recurring-job-group\.longhorn\.io/critical'
```

### Troubleshooting Backups

If backups aren't running:

1. **Check backup target is configured:**
   ```bash
   kubectl get backuptargets -n longhorn-system
   kubectl describe backuptarget default -n longhorn-system
   ```

2. **Check backup credentials secret exists:**
   ```bash
   kubectl get secret backblaze-backup-credentials -n longhorn-system
   ```

3. **Check recurring job status:**
   ```bash
   kubectl describe recurringjob weekly-backup -n longhorn-system
   kubectl describe recurringjob critical-daily-backup -n longhorn-system
   ```

4. **Force a manual backup to test:**
   ```bash
   # Create a one-off backup
   kubectl -n longhorn-system create job --from=recurringjob/weekly-backup test-backup-$(date +%s)
   ```

5. **Check Longhorn UI:** Navigate to Backup → check if backups appear and their status

## Accessing the UI

### Via Pocket-ID SSO (production)

Access at **https://longhorn.newjoy.ro** (protected by oauth2-proxy + Pocket-ID).

See `config/oauth2-proxy-longhorn/README.md` for setup instructions.

### Via Port-Forward (local/debugging)

```bash
kubectl port-forward -n longhorn-system svc/longhorn-frontend 8080:80
```

Then open http://localhost:8080
