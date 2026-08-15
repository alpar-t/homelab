# Single-node maintenance

Use this procedure to take one FCOS node (`buksi`, `pamacs`, or `pufi`) down for
a short planned reboot or hardware intervention while the other two nodes stay
online. Whole-cluster power work uses
[`cluster-power-maintenance.md`](cluster-power-maintenance.md) instead.

CNPG databases use node-local NVMe PVCs. A short maintenance window must leave
each database pod and PVC associated with its node; draining those pods would
either block on a PodDisruptionBudget (PDB) or cause a full standby clone onto
the third node. The safe pattern is therefore: switch primaries away, cordon,
drain only non-CNPG pods, reboot, and let the same CNPG pods reuse their PVCs.

## Availability policy

- Every CNPG cluster has two instances on different nodes and CNPG-managed PDBs
  enabled.
- PDBs protect voluntary evictions. They do not prevent a power loss, kernel
  freeze, disk failure, or direct pod deletion.
- A primary on the maintenance node is switched to its healthy standby before
  shutdown.
- `kubectl drain --force` does **not** bypass a PDB. It only permits deletion of
  pods without a recognised controller. `--disable-eviction` bypasses PDBs and
  is reserved for the deliberate whole-cluster shutdown runbook.
- The System Upgrade Controller uses the same non-CNPG pod selector and upgrades
  one node at a time. Do not remove that selector from
  `config/system-upgrade-controller/plan/k3s-upgrade-plan.yaml`.

## 1. Preflight

Set the target once:

```bash
node=buksi
```

All three nodes must be Ready, all CNPG clusters must be 2/2 with a primary,
continuous archiving must be healthy, and each cluster must have a recent
completed scheduled backup:

```bash
kubectl get nodes
kubectl get clusters.postgresql.cnpg.io -A \
  -o custom-columns='NS:.metadata.namespace,CLUSTER:.metadata.name,READY:.status.readyInstances,PRIMARY:.status.currentPrimary,PHASE:.status.phase'
kubectl get backups.postgresql.cnpg.io -A \
  --sort-by=.metadata.creationTimestamp
kubectl get pdb -A
```

Record the CNPG instances and local PVCs on the target node before changing
anything:

```bash
kubectl get pods -A -l cnpg.io/cluster \
  --field-selector "spec.nodeName=$node" \
  -L cnpg.io/cluster,cnpg.io/instanceRole -o wide
kubectl get pv \
  -o custom-columns='PV:.metadata.name,CLAIM:.spec.claimRef.name,NAMESPACE:.spec.claimRef.namespace,NODE:.spec.nodeAffinity.required.nodeSelectorTerms[0].matchExpressions[0].values[0],CLASS:.spec.storageClassName' \
  | grep local-ssd
```

Stop if either database copy is already unhealthy, replication is lagging, the
newest scheduled backup failed, or both copies of any cluster appear on the same
node. Fix that first; maintenance must not begin from a degraded state.

For a hardware change, also confirm the target node's storage collector is
healthy:

```bash
kubectl -n node-config get pods \
  -l app.kubernetes.io/name=node-storage-health -o wide
```

## 2. Move database primaries away

For every pod on the target node whose `cnpg.io/instanceRole` is `primary`, find
the Ready standby on another node and promote it explicitly:

```bash
kubectl get pods -n <namespace> -l cnpg.io/cluster=<cluster> \
  -L cnpg.io/instanceRole -o wide
kubectl cnpg status -n <namespace> <cluster>
kubectl cnpg promote -n <namespace> <cluster> <standby-instance>
kubectl cnpg status -n <namespace> <cluster>
```

Wait for the promoted instance to be reported as the primary and for replication
to return to zero lag before continuing. This is a controlled switchover, not a
failover.

## 3. Protect Longhorn from needless rebuilding

For maintenance expected to finish within an hour, temporarily increase the
replica replenishment delay:

```bash
kubectl -n longhorn-system patch setting replica-replenishment-wait-interval \
  --type=merge -p '{"value":"3600"}'
kubectl -n longhorn-system get setting replica-replenishment-wait-interval
```

If the work will exceed the configured delay, allow Longhorn to rebuild rather
than keeping volumes degraded indefinitely.

## 4. Cordon and selectively drain

The selector is the important part: it drains pods that do not have the CNPG
cluster label and intentionally leaves database pods in place.

```bash
kubectl cordon "$node"
kubectl drain "$node" \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --pod-selector='!cnpg.io/cluster' \
  --timeout=15m
```

Verify that the only remaining workload pods are CNPG instances and expected
DaemonSets:

```bash
kubectl get pods -A --field-selector "spec.nodeName=$node" -o wide
```

Do not delete a CNPG pod or local PVC merely to make the drain output empty.

If an ordinary PDB blocks a non-CNPG workload, inspect it and the owning
controller:

```bash
kubectl get pdb -A
kubectl describe pdb <name> -n <namespace>
kubectl get pods -n <namespace> -o wide
```

Resolve the unavailable replica or make an explicit workload-specific decision.
Do not substitute `--force`, and do not use `--disable-eviction` during normal
single-node maintenance.

## 5. Shut down and perform the work

```bash
ssh "core@$node.local" sudo systemctl poweroff
```

Wait until the node is fully off before touching hardware. During the outage,
the affected CNPG pods are unavailable but their partners remain primary and
serving. Their local PVCs remain bound to the offline node.

## 6. Bring the node back

After boot, wait for Ready and then uncordon:

```bash
kubectl get nodes -w
kubectl uncordon "$node"
```

Confirm that the original CNPG instance and PV names on the node returned, all
clusters are again 2/2, and replication caught up:

```bash
kubectl get pods -A -l cnpg.io/cluster -o wide
kubectl get clusters.postgresql.cnpg.io -A \
  -o custom-columns='NS:.metadata.namespace,CLUSTER:.metadata.name,READY:.status.readyInstances,PRIMARY:.status.currentPrimary,PHASE:.status.phase'
kubectl cnpg status -n <namespace> <cluster>
kubectl get pv \
  -o custom-columns='PV:.metadata.name,CLAIM:.spec.claimRef.name,NAMESPACE:.spec.claimRef.namespace,NODE:.spec.nodeAffinity.required.nodeSelectorTerms[0].matchExpressions[0].values[0],CLASS:.spec.storageClassName' \
  | grep local-ssd
```

Then restore the normal Longhorn delay and verify storage and application health:

```bash
kubectl -n longhorn-system patch setting replica-replenishment-wait-interval \
  --type=merge -p '{"value":"600"}'
kubectl get volumes.longhorn.io -n longhorn-system
kubectl -n node-config get daemonset/node-storage-health
argocd app list
```

## Permanent node or NVMe loss

Do not follow the short-reboot path indefinitely when the node or its NVMe is
known to be lost.

1. Confirm the surviving CNPG instance is the healthy primary and its archived
   WAL is current.
2. Confirm the latest scheduled backup completed.
3. For one cluster at a time, delete only the failed instance pod and its local
   PVC. Never delete the surviving primary's PVC.
4. Let CNPG provision a local PVC on the third node and clone a new standby.
5. Wait for 2/2 Ready and zero lag before repairing the next cluster.

If neither local instance survives, restore a new cluster from the latest B2
base backup and archived WAL. Do not attempt an in-place restore over the failed
cluster.

## Storage-health alert acknowledgement

An increased SMART counter remains latched so a 15-minute health poll cannot
miss it. After investigating and recording the event, remove only that counter's
baseline file from `/var/lib/node-storage-health/` on the affected node. The
collector adopts the current value on its next one-minute check. Do not clear a
pending-sector, failing-health, temperature, spare, wear, or capacity alert;
those clear only when the underlying condition is fixed.
