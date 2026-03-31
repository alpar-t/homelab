# Restoring OpenCloud PosixFS Storage from Longhorn Backup

This runbook documents how to restore OpenCloud personal spaces when the posixfs storage volume is lost or corrupted.

**Last used:** 2026-03-31 — full restore from B2 backup after storage volume was replaced with an empty one.

## Overview

OpenCloud uses **posixfs** mode with two Longhorn volumes:
- **data PVC** (`opencloud-opencloud-data`, 1TB `longhorn-hdd`) → mounted at `/var/lib/opencloud` — contains NATS cache, search index, thumbnails, IDM
- **posixfs PVC** (`opencloud-opencloud-posixfs`, 1TB `longhorn-hdd`) → mounted at `/var/lib/opencloud/storage` — contains actual user files, space metadata, indexes

Space discovery depends on:
1. User directories under `/var/lib/opencloud/storage/users/{user-id}/` with `user.oc.space.*` extended attributes
2. NATS JS KV cache (on data PVC at `/var/lib/opencloud/nats/`) for ID lookups
3. Index files under `/var/lib/opencloud/storage/indexes/`

If the posixfs volume is lost, personal spaces disappear even though the service starts fine.

## Diagnosis

### 1. Check if storage volume is empty
```bash
kubectl -n opencloud exec deploy/opencloud-opencloud -c opencloud -- df -h /var/lib/opencloud/storage
kubectl -n opencloud exec deploy/opencloud-opencloud -c opencloud -- du -sh /var/lib/opencloud/storage/
```
If the volume is nearly empty (< 1MB) but should have data, the volume was replaced.

### 2. Identify the mount layout
```bash
kubectl -n opencloud exec deploy/opencloud-opencloud -c opencloud -- cat /proc/mounts | grep longhorn
```
Verify which Longhorn volume is mounted at `/var/lib/opencloud/storage`.

### 3. Find the original volume's backup
```bash
# List all 1TB backup volumes — look for ones with large backup sizes
kubectl -n longhorn-system get backupvolumes.longhorn.io -o json | python3 -c "
import json, sys
data = json.load(sys.stdin)
for item in data['items']:
    name = item['metadata']['name']
    size = int(item.get('status', {}).get('size', '0'))
    last_backup = item.get('status', {}).get('lastBackupAt', '')
    if size == 1073741824000:  # 1TB volumes
        print(f'{name}  lastBackup={last_backup}')
"

# Then list individual backups for the candidate volume to find the one with real data
kubectl -n longhorn-system get backups.longhorn.io -o json | python3 -c "
import json, sys
data = json.load(sys.stdin)
for item in data['items']:
    vol = item.get('status', {}).get('volumeName', '')
    if 'VOLUME_ID_HERE' in vol:
        name = item['metadata']['name']
        created = item.get('status', {}).get('snapshotCreatedAt', '')
        size = int(item.get('status', {}).get('size', '0'))
        print(f'{name} size={size/1024/1024/1024:.1f}GB created={created}')
"
```

**Key insight:** ext4 overhead for a 1TB volume is ~18-20GB. Backups significantly larger than that contain actual user data. Compare backup sizes over time to identify when data was present.

### 4. Verify extended attributes are intact (if volume has data)
```bash
kubectl -n opencloud exec deploy/opencloud-opencloud -c opencloud -- \
  getfattr -d -m - /var/lib/opencloud/storage/users/<user-id>
```
Look for `user.oc.space.id`, `user.oc.space.type="personal"`, `user.oc.owner.id`.

## Restore Procedure

### Step 1: Stop OpenCloud via ArgoCD

ArgoCD's self-heal will fight manual scaling. Use a Helm parameter override:
```bash
kubectl -n argocd patch application opencloud --type=json -p='[
  {"op":"add","path":"/spec/sources/1/helm/parameters","value":[{"name":"opencloud.replicas","value":"0"}]}
]'
```

Wait for the pod to terminate:
```bash
kubectl -n opencloud get pods -l app.kubernetes.io/component=opencloud -w
```

### Step 2: Create a Longhorn volume from backup

Get the backup URL:
```bash
kubectl -n longhorn-system get backups.longhorn.io <backup-name> -o jsonpath='{.status.url}'
```

Create the volume:
```yaml
apiVersion: longhorn.io/v1beta2
kind: Volume
metadata:
  name: opencloud-posixfs-restored
  namespace: longhorn-system
spec:
  size: "1073741824000"
  numberOfReplicas: 2
  fromBackup: "<backup-url>"
  frontend: blockdev
  dataLocality: disabled
  accessMode: rwo
  staleReplicaTimeout: 30
```

Monitor progress:
```bash
kubectl -n longhorn-system get engines.longhorn.io -l longhornvolume=opencloud-posixfs-restored \
  -o jsonpath='{.items[0].status.restoreStatus}' | python3 -m json.tool
```

**Expect ~3% per 20 minutes from B2** (~8 hours for 323GB). Progress only updates per-snapshot block, so 0% is normal for the first few minutes.

### Step 3: Swap the PV binding

PV `volumeHandle` is immutable — you must delete and recreate the PV, then rebind the PVC.

```bash
# 1. Delete the current PVC (ArgoCD will recreate it)
kubectl -n opencloud delete pvc opencloud-opencloud-posixfs --grace-period=0

# 2. Delete any auto-provisioned PVs (remove finalizers if stuck)
kubectl patch pv <auto-pv-name> --type=json -p='[{"op":"remove","path":"/metadata/finalizers"}]'
kubectl delete pv <auto-pv-name> --grace-period=0

# 3. Create PV pointing to restored volume (no claimRef — let PVC bind to it)
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolume
metadata:
  name: opencloud-posixfs-restored-pv
  annotations:
    pv.kubernetes.io/provisioned-by: driver.longhorn.io
spec:
  accessModes: [ReadWriteOnce]
  capacity:
    storage: 1000Gi
  csi:
    driver: driver.longhorn.io
    fsType: ext4
    volumeAttributes:
      diskSelector: hdd
      fsType: ext4
      numberOfReplicas: "2"
      staleReplicaTimeout: "30"
    volumeHandle: opencloud-posixfs-restored
  persistentVolumeReclaimPolicy: Retain
  storageClassName: longhorn-hdd
  volumeMode: Filesystem
EOF

# 4. Immediately recreate PVC bound to our PV (race ArgoCD!)
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: opencloud-opencloud-posixfs
  namespace: opencloud
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1000Gi
  storageClassName: longhorn-hdd
  volumeName: opencloud-posixfs-restored-pv
EOF
```

**If ArgoCD wins the race** and creates a PVC that binds to an auto-provisioned PV:
1. Delete the auto-provisioned PV (remove finalizers first)
2. Patch your PV with `claimRef` matching the ArgoCD-created PVC's UID
3. The PVC will go Lost → then rebind to your PV once the old PV is gone
4. If PVC stays Lost, delete it and repeat step 4 above quickly

### Step 4: Tell ArgoCD to ignore the PVC volumeName

The Helm chart creates PVCs without `volumeName` (dynamic provisioning). ArgoCD will try to patch it back. You **must** add this to the Application:

```bash
kubectl -n argocd patch application opencloud --type=merge -p '{
  "spec": {
    "ignoreDifferences": [{
      "group": "",
      "kind": "PersistentVolumeClaim",
      "name": "opencloud-opencloud-posixfs",
      "namespace": "opencloud",
      "jsonPointers": ["/spec/volumeName"]
    }]
  }
}'
```

And add `RespectIgnoreDifferences=true` to syncOptions:
```bash
kubectl -n argocd patch application opencloud --type=json \
  -p='[{"op":"add","path":"/spec/syncPolicy/syncOptions/-","value":"RespectIgnoreDifferences=true"}]'
```

**Persist these in `apps/opencloud.yaml` in git** — they're already there as of 2026-03-31.

### Step 5: Clear NATS cache and restart

The NATS KV cache on the data PVC will have stale entries. Clear it before starting:

```bash
# Remove ArgoCD replicas override to let the pod start
kubectl -n argocd patch application opencloud --type=json \
  -p='[{"op":"remove","path":"/spec/sources/1/helm/parameters"}]'

# Wait for pod to start, then clear NATS and restart
kubectl -n opencloud exec deploy/opencloud-opencloud -c opencloud -- sh -c 'rm -rf /var/lib/opencloud/nats/*'
kubectl -n opencloud delete pod -l app.kubernetes.io/component=opencloud
```

### Step 6: Verify

```bash
# Check indexes were rebuilt
kubectl -n opencloud exec deploy/opencloud-opencloud -c opencloud -- \
  find /var/lib/opencloud/storage/indexes/ -type f

# Check for errors (some assimilation errors for metadata/ and lost+found are normal)
kubectl -n opencloud logs deploy/opencloud-opencloud -c opencloud --tail=50 | grep error

# Check storage usage
kubectl -n opencloud exec deploy/opencloud-opencloud -c opencloud -- df -h /var/lib/opencloud/storage
```

Log in at https://drive.newjoy.ro and verify personal spaces are visible. Users re-syncing locally will resolve any file-level inconsistencies.

## Cleanup

After successful restore:
```bash
# Delete orphaned empty Longhorn volumes
kubectl -n longhorn-system delete volumes.longhorn.io <old-empty-volume-name>

# Restart the collaboration pod (likely in CrashLoopBackOff from extended downtime)
kubectl -n opencloud delete pod -l app.kubernetes.io/component=collaboration
```

## Pitfalls

- **ArgoCD races you on PVC creation.** The Helm chart uses dynamic provisioning, so every time the PVC is deleted, ArgoCD recreates it and Longhorn provisions a fresh empty volume. You must be fast with the `kubectl apply` of your manually-bound PVC, or use the claimRef patching approach.
- **PV `spec.csi.volumeHandle` is immutable.** You cannot patch it — you must delete and recreate the PV.
- **PV finalizers block deletion.** Always remove finalizers before deleting PVs during restore: `kubectl patch pv <name> --type=json -p='[{"op":"remove","path":"/metadata/finalizers"}]'`
- **B2 restore is slow.** Budget 8+ hours for a large volume. The Longhorn progress counter updates per-snapshot, so 0% is normal for the first few minutes.
- **NATS cache must be cleared after restore.** Otherwise the posix driver has stale ID mappings and will fail to discover spaces. Clear `/var/lib/opencloud/nats/*` and restart.
- **The `metadata/` directory errors are harmless.** During assimilation, you'll see "could not find space for path" errors for `metadata/`, `lost+found`, `indexes/` etc. These directories don't have space xattrs and that's expected. Wait for the errors to settle (~1-2 minutes).
