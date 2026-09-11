# Frigate disposable media disk

Use this runbook for the deliberately quarantined 3 TB HDD on `pamacs`. It may
store Frigate recordings only. The recordings are disposable; a failure of this
disk must not endanger another Longhorn volume or be mistaken for healthy
storage.

## Decision and topology

On 2026-09-11, the old WD Purple disk was retained temporarily for disposable
Frigate footage while the failing 8 TB disk was prioritized for warranty
replacement.

| Layer | Identity |
|---|---|
| Linux device | `/dev/sdb` |
| Drive | `WDC WD30PURX-64P6ZY0`, serial `WD-WMC4N0J6E7EE` |
| Host mount | `/var/mnt/disk1` |
| Longhorn node/disk | `pamacs/default-disk-701c6aa6cab3fae9` |
| Allowed volume | `frigate/frigate-media` |
| Longhorn volume | `pvc-c41c623f-0a27-42c3-8065-d013ee86aae5` |
| Desired capacity | `2Ti` |

The volume has one replica by design. `frigate-config` is a separate replicated
SSD volume, so losing the media disk loses recordings rather than Frigate's
configuration and database.

At the decision point the disk had 105 pending sectors, a failed SMART read
self-test, and inconsistent historical SMART counters. Its generic Longhorn
health condition still said Ready because filesystem availability does not
prove physical media health. The node-storage-health pod therefore remains
intentionally NotReady while this disk is installed; do not clear or baseline
the pending-sector alert.

The old remote backup from 2026-04-28 is not part of the recovery plan. The
volume uses `longhorn-hdd-noreplica` and the `excluded` recurring-job marker, so
current recordings are intentionally not backed up.

## Isolation invariants

Keep all of these true:

- Longhorn disk scheduling is disabled on `/var/mnt/disk1`.
- Its only disk tag is `frigate-disposable`, not the generic `hdd` tag.
- Its only replica belongs to `frigate-media`.
- `frigate-media` remains single-replica and excluded from recurring backups.
- The PVC is `2Ti`, not the disk's entire nominal capacity. This preserves the
  Longhorn minimum-free-space requirement and working headroom.
- No important data, database, configuration, or second workload is placed on
  this disk.

Check the disk policy and its replicas:

```bash
kubectl -n longhorn-system get node.longhorn.io pamacs -o json | jq '
  .spec.disks["default-disk-701c6aa6cab3fae9"]'

kubectl -n longhorn-system get replicas.longhorn.io -o json | jq -r '
  .items[]
  | select(.spec.nodeID == "pamacs" and .spec.diskPath == "/var/mnt/disk1")
  | [.spec.volumeName, .metadata.name, .spec.active] | @tsv'
```

Expected disk policy:

```json
{
  "allowScheduling": false,
  "evictionRequested": false,
  "path": "/var/mnt/disk1",
  "tags": ["frigate-disposable"]
}
```

## Apply or restore the quarantine

Resolve the disk by its path and serial before changing anything. Device letters
can change after hardware maintenance.

```bash
kubectl -n node-config logs \
  -l app.kubernetes.io/name=node-storage-health --tail=20 --prefix=true

kubectl -n longhorn-system patch node.longhorn.io pamacs --type=json -p='[
  {"op":"replace","path":"/spec/disks/default-disk-701c6aa6cab3fae9/allowScheduling","value":false},
  {"op":"replace","path":"/spec/disks/default-disk-701c6aa6cab3fae9/tags","value":["frigate-disposable"]}
]'
```

This does not stop or move the existing replica. It prevents new scheduling and
removes the disk from every StorageClass that selects `hdd`.

The PVC manifest is the source of truth for the `2Ti` request. After the Git
change is available to Argo CD, or for the initial controlled expansion, apply:

```bash
kubectl -n frigate patch pvc frigate-media --type=merge \
  -p '{"spec":{"resources":{"requests":{"storage":"2Ti"}}}}'
```

Watch until both requested and filesystem capacities have expanded:

```bash
kubectl -n frigate get pvc frigate-media -w
kubectl -n frigate exec deployment/frigate -- df -h /media/frigate
kubectl -n frigate get pod -l app.kubernetes.io/name=frigate
```

If the PVC condition is `FileSystemResizePending` and its message asks for a
pod restart, delete only the current Frigate pod. The Deployment recreates it
and kubelet grows ext4 while mounting the expanded Longhorn volume:

```bash
kubectl -n frigate delete pod -l app.kubernetes.io/name=frigate
kubectl -n frigate rollout status deployment/frigate --timeout=5m
kubectl -n frigate get pvc frigate-media
kubectl -n frigate exec deployment/frigate -- df -h /media/frigate
```

Do not try to shrink the PVC later; Kubernetes volume claims cannot be shrunk.

## Monitoring and retirement boundary

Continuing to use the disk accepts loss of recordings, not loss of the node.
Remove or power down the disk if any of these occur:

- kernel `I/O error`, ATA reset, link reset, or filesystem error;
- Frigate or another process remains blocked in uninterruptible I/O;
- the disk causes kubelet, Longhorn, or `pamacs` responsiveness problems;
- SMART can no longer be read reliably or the drive repeatedly disconnects;
- temperature becomes unsafe, the filesystem turns read-only, or the mount
  disappears.

Inspect without starting another self-test:

```bash
kubectl -n node-config logs \
  -l app.kubernetes.io/name=node-storage-health --tail=20 --prefix=true

ssh core@pamacs.local \
  'sudo journalctl -k --since "24 hours ago" --no-pager' \
  | grep -Ei 'ata[0-9]|sd[a-z]|I/O error|medium error|EXT4-fs.*(error|warning)|resetting link'
```

Do not wait for complete mechanical failure: a disposable disk may still stall
the entire SATA path or node before it stops working.

## After disk failure or retirement

Frigate may block or restart when the sole media replica disappears. Preserve
`frigate-config`; only the media PVC is disposable. Remove the failed Longhorn
disk and recreate or restore `frigate-media` on healthy storage according to the
capacity available at that time. Never delete `frigate-config` as part of media
recovery.

When the disk is physically removed, delete or update this quarantine entry and
restore the `node-storage-health` expectation for `pamacs`. Do not transfer the
`frigate-disposable` policy to a replacement disk unless the same risk decision
is made explicitly.
