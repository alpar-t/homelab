# Longhorn minor-version upgrades

Upgrade Longhorn through every supported minor release and let Argo CD apply
only one chart-version commit at a time. Keep workloads running during normal
V1 engine migration. Do not cordon or drain nodes, and do not delete Longhorn
data, replicas, engine images, or CRDs as an upgrade or recovery step.

The 2026-08 maintenance path is:

```text
1.8.1 -> 1.9.2 -> 1.10.2 -> 1.11.3
```

Longhorn 1.10.2 must temporarily use
`longhornio/backing-image-manager:v1.10.2-hotfix-1@sha256:e56fcc01c6e60b380d83dc13bb15174d1d21d06491721bc9e83b0f50863a6388`.
Remove that override with the 1.11.3 hop so the chart uses its native image.

## Safety invariants

- Keep the V1 data engine, existing storage classes, replica defaults, B2
  exclusions, and `longhorn-system/longhorn-storage-network` unchanged.
- Disable only the Helm pre-upgrade Job with
  `preUpgradeChecker.jobEnabled: false`. Keep
  `preUpgradeChecker.upgradeVersionCheck: true`.
- Keep `concurrentAutomaticEngineUpgradePerNodeLimit: 3` for all releases.
- Never advance while any volume still uses the previous engine image.
- System backups in this procedure use `volumeBackupPolicy: disabled`. They
  preserve Longhorn metadata without backing up the 28 deliberately excluded
  multi-terabyte volumes.
- Retain every system-backup checkpoint until the maintenance window and its
  follow-up observation period are complete.

## Known Argo CD normalization

Before this upgrade, the `longhorn` Application is `Healthy` but `OutOfSync`
only for these seven CRDs:

```text
engineimages.longhorn.io
engines.longhorn.io
instancemanagers.longhorn.io
nodes.longhorn.io
replicas.longhorn.io
settings.longhorn.io
volumes.longhorn.io
```

A hard refresh confirmed that this was persistent CRD normalization, not stale
Argo cache. After the 1.11.3 upgrade, the exception set became the five CRDs
that use Longhorn's conversion webhook:

```text
backingimages.longhorn.io
backuptargets.longhorn.io
engineimages.longhorn.io
nodes.longhorn.io
volumes.longhorn.io
```

The only expected declarative difference is `/spec/conversion`: the chart
renders `strategy: None`, then Longhorn owns and replaces that block with its
live Webhook configuration. The Application ignores exactly that path so CRD
schemas remain fully reconciled while runtime conversion state is preserved.
The Application must otherwise be `Synced/Healthy`. A hard refresh
recalculates drift and is safe; do not use force or replace merely to clear
normalization.

The Application uses client-side apply for this chart and ignores only the
runtime-owned conversion block. Do not re-enable
`ServerSideApply=true`: on both the 1.10.2 and 1.11.3 hops it produced an
invalid partial conversion block and prevented five CRDs from upgrading.

The enabled 1.8.1 Helm pre/post-upgrade hooks were observed rerunning because
of drift. The values disable the pre-upgrade Job as Longhorn's chart recommends
for Argo CD. The manager's version check remains enabled.

Inspect the exception set with:

```bash
kubectl -n argocd annotate application longhorn \
  argocd.argoproj.io/refresh=hard --overwrite
kubectl -n argocd get application longhorn \
  -o jsonpath='{range .status.resources[?(@.status!="Synced")]}{.group}{"\t"}{.kind}{"\t"}{.name}{"\n"}{end}'
```

## Preflight

Record a UTC start time and the current Git revision:

```bash
date -u +%Y-%m-%dT%H:%M:%SZ
git fetch origin
git rev-parse origin/main
```

Require the root Application to be `Synced/Healthy`, the Longhorn Application
to be `Healthy` with only the seven CRDs above out of sync, and the storage
Application to be `Synced/Healthy`:

```bash
kubectl -n argocd get applications.argoproj.io \
  homelab longhorn longhorn-storage \
  -o custom-columns='NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,OP:.status.operationState.phase'
```

Require all three Kubernetes nodes to be Ready and schedulable:

```bash
kubectl get nodes \
  -o custom-columns='NAME:.metadata.name,READY:.status.conditions[-1].status,UNSCHEDULABLE:.spec.unschedulable,VERSION:.status.nodeInfo.kubeletVersion'
```

Require every Longhorn node and every configured disk to have scheduling
enabled and both `Ready=True` and `Schedulable=True`:

```bash
kubectl -n longhorn-system get nodes.longhorn.io -o json | jq -r '
  .items[] as $node |
  ($node.spec.disks | to_entries[]) as $disk |
  [$node.metadata.name, $disk.key, $disk.value.path,
   ($node.spec.allowScheduling|tostring),
   ($disk.value.allowScheduling|tostring),
   ([$node.status.conditions[]|select(.type=="Ready")|.status]|first),
   ([$node.status.conditions[]|select(.type=="Schedulable")|.status]|first),
   ([$node.status.diskStatus[$disk.key].conditions[]|select(.type=="Ready")|.status]|first),
   ([$node.status.diskStatus[$disk.key].conditions[]|select(.type=="Schedulable")|.status]|first)] | @tsv'
```

Capture the volume count as the window's baseline. Require every volume to be
`attached`, `healthy`, on data engine `v1`, and on the current release image.
The 2026-08-05 preflight began with 65 volumes. A concurrent Vikunja deployment
temporarily raised this to 68. The later concurrent Sure-to-Actual Budget
replacement established the final steady baseline of 66 volumes: 65
attached/healthy and one deliberately detached Actual Budget MCP cache volume
(`pvc-67c77524-8571-4660-a032-009df921a179`). The smoke-test PVC temporarily
raised the total to 67.

```bash
kubectl -n longhorn-system get volumes.longhorn.io -o json | jq '{
  count:(.items|length),
  default:([.items[]|select(.metadata.labels["recurring-job-group.longhorn.io/default"]=="enabled")]|length),
  excluded:([.items[]|select(.metadata.labels["recurring-job-group.longhorn.io/excluded"]=="enabled")]|length),
  bad:[.items[]|select(.status.state!="attached" or
                       .status.robustness!="healthy" or
                       .spec.dataEngine!="v1")|
       {name:.metadata.name,state:.status.state,
        robustness:.status.robustness,dataEngine:.spec.dataEngine,
        image:.status.currentImage}]
}'
```

Require all CNPG clusters to have every requested instance Ready and no other
workload pod to be Pending, Failed, or Unknown:

```bash
kubectl get clusters.postgresql.cnpg.io -A -o json | jq '
  [.items[]|{namespace:.metadata.namespace,name:.metadata.name,
             desired:.spec.instances,ready:.status.readyInstances,
             phase:.status.phase}]'
kubectl get pods -A -o json | jq '
  [.items[]|select(.status.phase!="Running" and .status.phase!="Succeeded")|
   {namespace:.metadata.namespace,name:.metadata.name,phase:.status.phase}]'
```

Require the B2 target to be available and recently synchronized, no failed
backing image, no active backup/rebuild job, and no failed replica:

```bash
kubectl -n longhorn-system get backuptargets.longhorn.io default \
  -o custom-columns='NAME:.metadata.name,AVAILABLE:.status.available,LAST_SYNC:.status.lastSyncedAt,OWNER:.status.ownerID'
kubectl -n longhorn-system get backingimages.longhorn.io -o json | jq '
  [.items[]|select(any(.status.diskFileStatusMap[]?; .!="ready"))|
   {name:.metadata.name,status:.status.diskFileStatusMap}]'
kubectl -n longhorn-system get backups.longhorn.io -o json | jq '
  [.items[]|select(.status.state != null and .status.state != "" and
                   .status.state != "Completed")|
   {name:.metadata.name,volume:.status.volumeName,
    state:.status.state,progress:.status.progress}]'
kubectl -n longhorn-system get replicas.longhorn.io -o json | jq '
  [.items[]|select(.status.currentState!="running" or
                   ((.status.failedAt//"")!=""))|
   {name:.metadata.name,volume:.spec.volumeName,
    state:.status.currentState,failedAt:.status.failedAt}]'
kubectl -n longhorn-system get jobs -o json | jq '
  [.items[]|select((.status.active//0)>0)|
   {name:.metadata.name,active:.status.active,start:.status.startTime}]'
```

Confirm each pre-existing default-group volume has a completed
`weekly-backup` from the most recent Tuesday run and the critical volume has a
completed `critical-daily-backup` from the current day. The three Vikunja
volumes were created after that weekly run; require its initial CNPG B2 backup
to complete before continuing. Do not add or back up any excluded volume.

```bash
kubectl -n longhorn-system get backups.longhorn.io -o json | jq -r '
  [.items[]|select(.status.state=="Completed")|
   {volume:.status.volumeName,job:.status.labels.RecurringJob,
    created:.status.backupCreatedAt}] |
  group_by(.volume)[] | max_by(.created) |
  [.volume,.job,.created] | @tsv'
kubectl -n longhorn-system get backups.longhorn.io \
  -l backup-volume=pvc-3a76b82c-00d9-4e5b-896e-9ff67a346221 \
  -o custom-columns='NAME:.metadata.name,STATE:.status.state,JOB:.status.labels.RecurringJob,CREATED:.status.backupCreatedAt'
kubectl -n vikunja get backups.postgresql.cnpg.io \
  --sort-by=.metadata.creationTimestamp
```

## Render and verify every hop

Download the official charts and render each with the planned values before
the first commit. Verify that each rendered workload and default-image setting
resolves to an existing Linux `amd64` image. For digest-pinned references,
check both that the tag resolves to the pinned digest and that the digest has
an `amd64` manifest.

```bash
helm repo add longhorn https://charts.longhorn.io
helm repo update
for version in 1.9.2 1.10.2 1.11.3; do
  helm pull longhorn/longhorn --version "$version" --destination /tmp
done

helm template longhorn /tmp/longhorn-1.9.2.tgz \
  --namespace longhorn-system --kube-version 1.34.6 \
  -f config/longhorn/values.yaml > /tmp/longhorn-1.9.2.yaml
helm template longhorn /tmp/longhorn-1.10.2.tgz \
  --namespace longhorn-system --kube-version 1.34.6 \
  -f config/longhorn/values.yaml \
  --set-string 'image.longhorn.backingImageManager.tag=v1.10.2-hotfix-1@sha256:e56fcc01c6e60b380d83dc13bb15174d1d21d06491721bc9e83b0f50863a6388' \
  > /tmp/longhorn-1.10.2.yaml
helm template longhorn /tmp/longhorn-1.11.3.tgz \
  --namespace longhorn-system --kube-version 1.34.6 \
  -f config/longhorn/values.yaml > /tmp/longhorn-1.11.3.yaml
```

The 1.10.2 render must contain exactly this temporary override:

```text
docker.io/longhornio/backing-image-manager:v1.10.2-hotfix-1@sha256:e56fcc01c6e60b380d83dc13bb15174d1d21d06491721bc9e83b0f50863a6388
```

## Create a metadata checkpoint

Use a unique name containing the current release and UTC timestamp. Create the
resource from a local temporary file, then wait until `Ready`. A `Ready` system
backup is the gate; `Error` or a timeout stops the upgrade.

```yaml
apiVersion: longhorn.io/v1beta2
kind: SystemBackup
metadata:
  name: pre-longhorn-1-9-2-YYYYMMDD-hhmmss
  namespace: longhorn-system
spec:
  volumeBackupPolicy: disabled
```

```bash
kubectl create -f /tmp/longhorn-system-backup.yaml
kubectl -n longhorn-system wait \
  --for=jsonpath='{.status.state}'=Ready \
  systembackup.longhorn.io/pre-longhorn-1-9-2-YYYYMMDD-hhmmss \
  --timeout=10m
kubectl -n longhorn-system get systembackup.longhorn.io \
  pre-longhorn-1-9-2-YYYYMMDD-hhmmss -o yaml
```

Repeat this metadata-only checkpoint after 1.9.2, after 1.10.2, and after the
final 1.11.3 validation. Retain all four resources.

## Push one minor release

Edit only `apps/longhorn.yaml` and the release-specific values, inspect the
diff, commit, and push directly to `main`:

```bash
git diff --check
git diff -- apps/longhorn.yaml config/longhorn/values.yaml \
  AGENTS.md runbooks/longhorn-upgrade.md
git add apps/longhorn.yaml config/longhorn/values.yaml \
  AGENTS.md runbooks/longhorn-upgrade.md
git commit -m 'Upgrade Longhorn to 1.9.2'
git push origin main
```

Use equivalent single-hop commits for 1.10.2 and 1.11.3. Never combine two
chart target versions in one commit.

## Reconciliation and engine gate

After each push, wait for the root app to reach the pushed revision and for
the Longhorn app to complete its operation. With `/spec/conversion` ignored,
require the Application to be `Synced/Healthy` and the exception list to be
empty:

```bash
kubectl -n argocd annotate application homelab \
  argocd.argoproj.io/refresh=hard --overwrite
kubectl -n argocd annotate application longhorn \
  argocd.argoproj.io/refresh=hard --overwrite
kubectl -n argocd get applications.argoproj.io homelab longhorn \
  -o custom-columns='NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,REVISION:.status.sync.revision,OP:.status.operationState.phase'
kubectl -n argocd get application longhorn \
  -o jsonpath='{range .status.resources[?(@.status!="Synced")]}{.group}{"\t"}{.kind}{"\t"}{.name}{"\n"}{end}'
```

Require the post-upgrade Job to complete, the two version settings to match the
target, and automatic engine-upgrade concurrency to remain three:

```bash
kubectl -n longhorn-system wait --for=condition=complete \
  job/longhorn-post-upgrade --timeout=10m
kubectl -n longhorn-system get settings.longhorn.io \
  current-longhorn-version default-engine-image \
  concurrent-automatic-engine-upgrade-per-node-limit \
  -o custom-columns='NAME:.metadata.name,VALUE:.value'
```

Do not advance until every volume reports the target engine and remains
attached/healthy:

```bash
TARGET_ENGINE=longhornio/longhorn-engine:v1.9.2
kubectl -n longhorn-system get volumes.longhorn.io -o json | jq \
  --arg target "$TARGET_ENGINE" '{
    count:(.items|length),
    pending:[.items[]|select(.status.currentImage!=$target or
                             .status.state!="attached" or
                             .status.robustness!="healthy")|
             {name:.metadata.name,image:.status.currentImage,
              state:.status.state,robustness:.status.robustness}]
  }'
```

Change `TARGET_ENGINE` to `v1.10.2` and `v1.11.3` for later hops. Also require
all Longhorn manager, CSI, driver-deployer, UI, and instance-manager workloads
to be Ready; all instance managers must still have the storage Multus network:

```bash
kubectl -n longhorn-system get daemonset,deployment,pod -o wide
kubectl -n longhorn-system get pods \
  -l longhorn.io/component=instance-manager -o json | jq -r '
  .items[] | [.metadata.name,.status.phase,
    (.metadata.annotations["k8s.v1.cni.cncf.io/network-status"]//"")] | @tsv'
```

Repeat the Longhorn node/disk, CNPG, workload-pod, backup-target, replica, and
active-job checks from preflight. Review fresh warnings and faults before
advancing:

```bash
kubectl -n longhorn-system get events --sort-by=.lastTimestamp | tail -n 100
kubectl -n longhorn-system logs -l app=longhorn-manager \
  --since=15m --tail=2000 | grep -Ei \
  'error|fault|failed|panic|rebuild|upgrade' || true
```

## Persistent storage smoke test

After 1.9.2, create a temporary default-class PVC and pod. Keep the PVC through
both later hops. The pod can be deleted and recreated to force a detach/remount.

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: longhorn-upgrade-smoke
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: data
  namespace: longhorn-upgrade-smoke
spec:
  storageClassName: longhorn
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 128Mi
---
apiVersion: v1
kind: Pod
metadata:
  name: smoke
  namespace: longhorn-upgrade-smoke
spec:
  restartPolicy: Never
  containers:
    - name: smoke
      image: docker.io/library/busybox:1.37@sha256:9db7b59979c38555a39def84a31fb98b5296952f9e3afd4f6f11f05b07adfab0
      command: ["sh", "-c", "sleep 86400"]
      volumeMounts:
        - name: data
          mountPath: /data
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: data
```

Write and record a unique marker:

```bash
SMOKE_MARKER="longhorn-upgrade-$(date -u +%Y%m%dT%H%M%SZ)"
kubectl -n longhorn-upgrade-smoke exec smoke -- \
  sh -c 'printf "%s\n" "$1" > /data/marker && sync' sh "$SMOKE_MARKER"
kubectl -n longhorn-upgrade-smoke exec smoke -- cat /data/marker
```

After each hop, recreate only the pod from the same manifest and verify the
exact marker. Do not recreate the PVC:

```bash
kubectl -n longhorn-upgrade-smoke delete pod smoke --wait=true
kubectl apply -f /tmp/longhorn-upgrade-smoke.yaml
kubectl -n longhorn-upgrade-smoke wait --for=condition=Ready pod/smoke \
  --timeout=5m
kubectl -n longhorn-upgrade-smoke exec smoke -- cat /data/marker
```

After final validation, delete the namespace and require the volume count to
return from 67 to the 66-volume execution baseline:

```bash
kubectl delete namespace longhorn-upgrade-smoke --wait=true
kubectl -n longhorn-system get volumes.longhorn.io \
  -o jsonpath='{.items[*].metadata.name}' | wc -w
```

## Argo CRD apply recovery

Do not enable server-side apply for the Longhorn Application. During the
1.10.2 and 1.11.3 upgrades, Argo's server-side apply retained an invalid
partial conversion-webhook configuration on these five CRDs:

```text
backingimages.longhorn.io
backuptargets.longhorn.io
engineimages.longhorn.io
nodes.longhorn.io
volumes.longhorn.io
```

The new manager then failed strict decoding because it was running against a
mixed old/new CRD set. If this recurs, first confirm
`current-longhorn-version` still reports the previous release and that every
volume remains healthy. Render the exact target chart and values, server-dry-
run only the five affected official CRDs, then apply those same objects with
ordinary client-side apply:

```bash
TARGET_VERSION=1.11.3
helm template longhorn /tmp/longhorn-${TARGET_VERSION}.tgz \
  --namespace longhorn-system \
  --kube-version "$(kubectl version -o json | jq -r '.serverVersion.gitVersion' | sed 's/^v//')" \
  -f config/longhorn/values.yaml \
  | yq 'select(.kind == "CustomResourceDefinition" and
      (.metadata.name == "volumes.longhorn.io" or
       .metadata.name == "nodes.longhorn.io" or
       .metadata.name == "backingimages.longhorn.io" or
       .metadata.name == "backuptargets.longhorn.io" or
       .metadata.name == "engineimages.longhorn.io"))' \
  | kubectl apply --dry-run=server -f -

# Repeat the identical pipeline without --dry-run only after all five pass.
```

Do not patch Volume or Node custom resources to work around strict-decoding
errors. Once the official CRDs are live, recreate only the failed
`longhorn-manager` pods so their DaemonSet retries the migration. Verify the
new manager version before allowing engine upgrades to continue.

## Stop and recover forward

Stop immediately on any faulted or degraded volume, failed CRD migration,
unhealthy CNPG cluster, unavailable backup target, failed engine upgrade,
failed storage-network attachment, or non-transient CSI/manager crash loop.

A Git revert is acceptable only before the new manager successfully completes
its version migration. Check `current-longhorn-version` first:

```bash
kubectl -n longhorn-system get setting current-longhorn-version \
  -o jsonpath='{.value}{"\n"}'
```

Once it reports the new release, Longhorn downgrade is unsupported. Freeze at
that release, do not push the next hop, and collect evidence:

```bash
kubectl -n longhorn-system logs -l app=longhorn-manager \
  --since=30m --all-containers --prefix > /tmp/longhorn-manager.log
kubectl -n longhorn-system get pods,events -o wide > /tmp/longhorn-state.txt
kubectl -n longhorn-system get volumes.longhorn.io,engines.longhorn.io,replicas.longhorn.io \
  -o yaml > /tmp/longhorn-storage-state.yaml
```

Generate a Longhorn support bundle from the UI or supported release tooling,
then repair forward on the same release. Keep workloads running unless a
specific damaged volume requires isolation.

## 2026-08 execution record

| Stage | UTC time | Result | Notes |
| --- | --- | --- | --- |
| Preflight started | 2026-08-05 05:31 | Passed with recorded exception | Began with 65 volumes and nine CNPG clusters. |
| Concurrent Vikunja rollout | 2026-08-05 05:43 | Accepted exception | Baseline became 68 attached/healthy volumes and ten 2/2 CNPG clusters. Initial Vikunja CNPG backup reported `walArchivingFailing`; the owner accepted this because the service was new and had no data to lose. |
| Chart render and image audit | 2026-08-05 05:59 | Passed | All three charts rendered for Kubernetes 1.34.6; every resolved image existed for Linux/amd64; the hotfix tag matched the pinned digest. |
| Pre-1.9.2 system backup | 2026-08-05 06:16 | Ready | `pre-longhorn-1-9-2-20260805-061330`, metadata only, source version v1.8.1. |
| 1.9.2 commit | 2026-08-05 06:18 | Pushed | `63e2b11`; Argo ran from 06:20:32 to 06:21:55. All engines reached 1.9.2 by 06:30 with every attached volume healthy. |
| Smoke test created | 2026-08-05 06:30 | Passed | Marker `longhorn-upgrade-20260805T063000Z` written to an explicit `longhorn` StorageClass PVC. It survived every later pod recreation and engine migration. |
| Post-1.9.2 system backup | 2026-08-05 07:32 | Ready | `post-longhorn-1-9-2-20260805-072247`, metadata only, source version v1.9.2. |
| Concurrent Sure-to-Actual replacement | 2026-08-05 06:22-07:32 | Accepted | Final steady baseline became 66 volumes and nine CNPG clusters. The Actual Budget MCP cache is deliberately detached; all other 65 steady volumes are attached/healthy. A transient snapshot-purge startup failure on the new Actual data volume recovered without recurrence. |
| 1.10.2 commit | 2026-08-05 07:46 | Pushed | `e1a7f00`, including the pinned backing-image-manager hotfix. |
| 1.10.2 CRD migration | 2026-08-05 08:08-09:17 | Repaired forward | Argo server-side apply failed five conversion CRDs, then managers rejected the mixed schema. `current-longhorn-version` remained v1.9.2. The exact official 1.10.2 CRDs passed server dry-run and were client-side applied; only the failed manager pods were recreated. Migration then reported v1.10.2. No Volume or Node CR was edited. |
| 1.10.2 engine migration | 2026-08-05 09:21-09:57 | Passed after one scheduling intervention | The new buksi instance manager initially needed 480m with only 355m request headroom. The stateless Browser pod was restarted and rescheduled to pamacs, freeing enough CPU without changing Longhorn CPU settings or stopping storage workloads. All 67 then-present volumes reached 1.10.2 healthy; the marker survived remount. |
| Post-1.10.2 system backup | 2026-08-05 10:03 | Ready | `post-longhorn-1-10-2-20260805-100213`, metadata only, source version v1.10.2. |
| 1.11.3 commit | 2026-08-05 10:08 | Pushed | `9f9980c`; removed the hotfix override and selected the chart-native `backing-image-manager:v1.11.3`. |
| 1.11.3 CRD migration | 2026-08-05 10:18-10:20 | Repaired forward | The same five Argo server-side-apply failures recurred while `current-longhorn-version` still reported v1.10.2. Applied the exact official 1.11.3 CRDs after server dry-run and recreated only failed manager pods. Manager migration then completed. |
| 1.11.3 engine migration | 2026-08-05 10:22-10:32 | Passed | All 67 then-present V1 engines reached 1.11.3. Transient instance-manager startup and connection messages cleared; no faulted/degraded volume or failed rebuild remained. |
| Argo apply fix | 2026-08-05 10:40-15:05 | Passed | `c45b693` removed `ServerSideApply=true`; the final documentation commit broadened the ignore pointer from only the CA bundle to the exact runtime-owned `/spec/conversion` block. CRD schemas remain reconciled and Argo no longer treats Longhorn's live Webhook configuration as schema drift. The official 1.11.3 post-upgrade Job logged `Manager upgrade complete` and `PassedUpgradeCheck`. |
| Final smoke cleanup | 2026-08-05 14:20 | Passed | The marker survived the final remount. The temporary namespace/PVC was deleted and the count returned from 67 to 66. |
| Final validation | 2026-08-05 14:25 | Passed | Longhorn v1.11.3; 66/66 V1 engines on v1.11.3; 65 attached/healthy plus the intentional detached cache; all three nodes/disks schedulable; managers, CSI, and instance managers Ready with storage networking; nine CNPG clusters 2/2; all workload pods Running/Ready or Completed; B2 available; all three Argo applications Synced/Healthy after ignoring only Longhorn's runtime-owned conversion block. |
| Final system backup | 2026-08-05 14:25 | Ready | `final-longhorn-1-11-3-20260805-142452`, metadata only, source version v1.11.3. All four checkpoints retained. |

Warnings retained for follow-up: stale backup-volume metadata for excluded,
healthy Stalwart volume `pvc-ac6c05a6-a6c0-4557-b364-672dfead8c8d` references a
missing B2 `volume.cfg`; no backup or volume data was deleted. Longhorn 1.11.3
also logs an hourly inability to identify the filesystem device behind buksi's
`/var/lib/longhorn-ssd`; the Longhorn node and that disk remain `Ready` and
`Schedulable`, and no fresh warning event, degraded replica, or workload impact
was present at closure.
