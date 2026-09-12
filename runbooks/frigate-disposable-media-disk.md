# Pamacs HDD quarantine and replacement

Use this runbook for the deliberately quarantined 3 TB HDD on `pamacs` and the
coordinated warranty replacement of its failing 8 TB HDD. The 3 TB disk may
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

The separate failing 8 TB disk is `WDC WD8005FFBX`, serial `WD-AM0BLRST`, at
`/var/mnt/disk2` (`pamacs/disk2`, tag `hdd`). It stores ordinary replicated
Longhorn volumes and is the disk to return under warranty. Never confuse it
with the quarantined Frigate disk at `/var/mnt/disk1`.

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

## Replace the 8 TB disk with one pamacs shutdown

Use this sequence once the replacement drive is physically on hand. Drain the
old 8 TB Longhorn replicas and sanitize that drive while `pamacs` is still
running, then shut the node down once to exchange the hardware. Leave each
volume's desired replica count unchanged at two: while the old disk is being
sanitized, affected volumes may run temporarily with one replica; after the new
`hdd` disk is schedulable, Longhorn can recreate the missing replicas
automatically.

This is an explicitly accepted degraded window, not normal operation. A backup
does not make a single live replica healthy, and some large media volumes may be
intentionally excluded from remote backup. Do not assume every affected volume
has a backup. Record those exceptions and accept them explicitly before deleting
any replica.

### 1. Preflight and record the rollback boundary

Follow the preflight and CNPG-primary steps in
[`node-maintenance.md`](node-maintenance.md). All nodes, Longhorn volumes, CNPG
clusters, and backup targets must be healthy before deliberately reducing HDD
redundancy.

Resolve the drive by model and serial every time; `/dev/sdX` letters can change:

```bash
ssh core@pamacs.local \
  'lsblk -d -o NAME,SIZE,MODEL,SERIAL && ls -l /dev/disk/by-id/'

kubectl -n longhorn-system get node.longhorn.io pamacs -o json | jq \
  '.spec.disks.disk2'

kubectl -n longhorn-system get replicas.longhorn.io -o json | jq -r '
  .items[]
  | select(.spec.nodeID == "pamacs"
      and .spec.diskPath == "/var/mnt/disk2"
      and (.spec.failedAt // "") == "")
  | [.spec.volumeName, .metadata.name, .status.currentState] | @tsv'
```

For every volume returned, confirm there is a `running` replica on `buksi` or
`pufi`. Stop if a volume has no healthy off-node replica:

```bash
kubectl -n longhorn-system get replicas.longhorn.io -o json | jq -r '
  .items[]
  | select((.spec.failedAt // "") == "")
  | [.spec.volumeName, .spec.nodeID, .spec.diskPath,
     .metadata.name, .status.currentState] | @tsv' | sort
```

Check the newest completed backup for each affected volume. The output must be
reviewed volume by volume; an absent row means there is no Longhorn backup:

```bash
kubectl -n longhorn-system get backups.longhorn.io -o json | jq -r '
  [.items[]
   | select(.status.state == "Completed")
   | {volume: .status.volumeName,
      created: .status.backupCreatedAt,
      name: .metadata.name}]
  | sort_by(.volume, .created)
  | group_by(.volume)
  | .[][-1]
  | [.volume, .created, .name] | @tsv' | sort
```

Also save the affected volume, PVC, replica, and backup inventories outside the
old disk. The active Longhorn inventory is the authoritative checklist on the
day of replacement; do not rely on the count recorded in an older incident.

### 2. Remove only the old 8 TB replicas

Disable new scheduling on `disk2` first:

```bash
kubectl -n longhorn-system patch node.longhorn.io pamacs --type=json -p='[
  {"op":"replace","path":"/spec/disks/disk2/allowScheduling","value":false}
]'
```

For each replica in the recorded `/var/mnt/disk2` inventory, re-check its
off-node peer immediately before deleting it, then delete only that exact
`pamacs` replica:

```bash
kubectl -n longhorn-system delete replica.longhorn.io <pamacs-disk2-replica>
```

Proceed one volume at a time. Keep `spec.numberOfReplicas: 2`; Longhorn will try
to rebuild, and it is fine if available capacity lets some volumes recover
before the new disk is installed. For every deletion, confirm the volume stays
attached and becomes `degraded`, never `faulted`.

Do not touch `/var/mnt/disk1` or the `frigate-media` replica. Before wiping,
there must be no replica left on disk2:

```bash
kubectl -n longhorn-system get replicas.longhorn.io -o json | jq -r '
  .items[]
  | select(.spec.nodeID == "pamacs" and .spec.diskPath == "/var/mnt/disk2")
  | [.spec.volumeName, .metadata.name, .spec.failedAt] | @tsv'
```

Remove the now-empty disk from the Longhorn node definition and stop its mount:

```bash
kubectl -n longhorn-system patch node.longhorn.io pamacs --type=json -p='[
  {"op":"remove","path":"/spec/disks/disk2"}
]'

ssh core@pamacs.local \
  'sudo systemctl stop var-mnt-disk2.mount; findmnt /var/mnt/disk2 || true'
```

### 3. Sanitize the old drive in place

Capture SMART output before and after sanitization. A full-device overwrite does
not erase SMART attributes or self-test history, although writing pending
sectors can cause the drive to remap them and change the pending/reallocated
counters. The failing drive may also return an I/O error before the pass
finishes; record that result rather than repeatedly stressing a drive that is
destabilizing the SATA link or node.

Select the sanitization method only after resolving the stable
`/dev/disk/by-id/` path for serial `WD-AM0BLRST` and checking the drive's
reported capabilities. A single full-device overwrite is the conservative
default for this CMR HDD. Do not issue ATA security-password or secure-erase
commands from memory: a failed security erase can leave a password set on the
RMA drive. Triple-check that the chosen target is neither the root NVMe nor the
3 TB Frigate disk.

No workload may use `/var/mnt/disk2` during the pass. If the wipe produces ATA
resets, uninterruptible I/O, or node instability, stop it and move directly to
the shutdown and swap; cluster availability takes priority over completing the
wipe.

### 4. Shut down once and exchange the drives

Complete the cordon and selective-drain steps in
[`node-maintenance.md`](node-maintenance.md), then power off:

```bash
ssh core@pamacs.local sudo systemctl poweroff
```

Wait until `pamacs` is fully off. Remove only the sanitized 8 TB drive and fit
the replacement. Leave the quarantined 3 TB Frigate drive connected. Boot
`pamacs`, confirm the old serial is absent and the new serial/model/size are
correct, then run SMART checks on the new drive before formatting it.

### 5. Prepare the replacement and let Longhorn rebuild

The existing `var-mnt-disk2.mount` unit mounts the filesystem label
`longhorn-disk2`. Resolve the new drive by its stable by-id path, unmount it if
anything auto-mounted it, then format only that verified replacement as ext4
with the existing label:

```bash
ssh core@pamacs.local
sudo wipefs -a /dev/disk/by-id/<new-drive>
sudo mkfs.ext4 -F -L longhorn-disk2 /dev/disk/by-id/<new-drive>
sudo systemctl start var-mnt-disk2.mount
findmnt /var/mnt/disk2
```

Do not run `config/longhorn/setup-node-storage.sh` for this one-disk replacement:
when given a single disk it assigns that disk to `disk1`, which would conflict
with the retained Frigate disk.

After confirming `/var/mnt/disk2` is the new empty filesystem, add it back to
Longhorn with the ordinary `hdd` tag:

```bash
kubectl -n longhorn-system patch node.longhorn.io pamacs --type=json -p='[
  {"op":"add","path":"/spec/disks/disk2","value":{
    "allowScheduling":true,
    "diskDriver":"",
    "diskType":"filesystem",
    "evictionRequested":false,
    "path":"/var/mnt/disk2",
    "storageReserved":0,
    "tags":["hdd"]
  }}
]'
```

Longhorn should create missing replicas without changing the PVCs. Wait until
every affected volume is `healthy` with two running replicas on distinct nodes;
then finish the bring-up and uncordon steps in `node-maintenance.md`. Verify the
new disk's SMART state, Longhorn capacity, application health, and current
backups. The node-storage-health DaemonSet may remain NotReady because the
separate 3 TB Frigate disk is still deliberately degraded; confirm any remaining
alert names that disk and serial, not the replacement.

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
