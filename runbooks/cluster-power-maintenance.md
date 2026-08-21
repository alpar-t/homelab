# Whole-Cluster Power Maintenance

Use this procedure when all three k3s nodes (`buksi`, `pamacs`, and `pufi`)
must be powered off together. This differs from single-node maintenance: there
is nowhere to reschedule workloads, so draining is used to give applications,
CNPG databases, and mounted volumes a graceful termination period.

Do not remove power from a running node. Shut down Fedora CoreOS with
`systemctl poweroff`, then wait for the hardware to turn off completely.

## Before shutdown

Run these checks from a workstation with cluster access:

```bash
kubectl get nodes
kubectl get volumes.longhorn.io -n longhorn-system \
  -o custom-columns='NAME:.metadata.name,STATE:.status.state,ROBUSTNESS:.status.robustness,NODE:.status.currentNodeID'
kubectl get clusters.postgresql.cnpg.io -A
kubectl get pods -A | grep -v Running
```

Resolve unexpected `NotReady` nodes, faulted/degraded Longhorn volumes, or
unhealthy CNPG clusters before continuing. Confirm that recent backups exist
if the maintenance could involve storage hardware.

Pause external uptime alerts for the planned outage if appropriate.

## Gracefully stop workloads

First cordon every node. Cordoning all three before draining prevents pods
from churning between nodes when the whole cluster is about to stop.

```bash
kubectl cordon buksi
kubectl cordon pamacs
kubectl cordon pufi
```

Drain each node while the Kubernetes API and embedded etcd still have quorum:

```bash
for node in buksi pamacs pufi; do
  kubectl drain "$node" \
    --ignore-daemonsets \
    --delete-emptydir-data \
    --disable-eviction \
    --force \
    --timeout=15m
done
```

`--disable-eviction` deliberately bypasses PodDisruptionBudgets. PDBs describe
the availability required during normal operation and can never be satisfied
when every node is being stopped. Pod deletion still honors each pod's normal
termination grace period. `--force` only permits deletion of unmanaged pods;
by itself it does not bypass PDBs.

Replacement workload pods will remain `Pending` because all nodes are
cordoned. DaemonSets will remain on the nodes until the operating systems shut
down. Both are expected.

Check that drains completed and give Longhorn a moment to detach volumes:

```bash
kubectl get pods -A -o wide
kubectl get volumes.longhorn.io -n longhorn-system \
  -o custom-columns='NAME:.metadata.name,STATE:.status.state,ROBUSTNESS:.status.robustness,NODE:.status.currentNodeID'
```

Volumes should become `detached`; Longhorn reports their robustness as
`unknown` while detached, which is expected here.

Investigate workload pods stuck in `Terminating`. Do not proceed with a hard
power cut merely because a drain timed out.

## Power off the nodes

Power off `pufi`, then `pamacs`, and keep `buksi` until last because `buksi`
normally hosts the WireGuard pod. Its MetalLB VIP can move, and the cluster retains its two-of-three etcd
quorum until the second node begins shutting down.

```bash
ssh core@192.168.1.166 sudo systemctl poweroff  # pufi
ssh core@192.168.1.173 sudo systemctl poweroff  # pamacs
ssh core@192.168.1.174 sudo systemctl poweroff  # buksi
```

The `systemctl poweroff` command can return successfully before shutdown has
finished, or SSH may disconnect and return status 255. The pre-shutdown drain
service can keep a node reachable for another minute or two while local units
stop. Wait until all three machines no longer answer and are physically off
before disconnecting power.

## Start the cluster again

Restore power to all three nodes. At minimum, start two nodes close together
so embedded etcd can regain quorum; starting all three together is preferred.

Wait for the API and nodes:

```bash
kubectl get nodes --watch
```

The installed `k3s-uncordon.service` is intended to uncordon nodes after k3s
starts. Once all nodes report `Ready`, ensure none were left cordoned:

```bash
kubectl uncordon buksi
kubectl uncordon pamacs
kubectl uncordon pufi
```

It is harmless if these commands report that a node is already uncordoned.

## Post-maintenance verification

Wait for Longhorn replicas and CNPG clusters to become healthy before treating
the maintenance as complete:

```bash
kubectl get nodes
kubectl get pods -A
kubectl get volumes.longhorn.io -n longhorn-system \
  -o custom-columns='NAME:.metadata.name,STATE:.status.state,ROBUSTNESS:.status.robustness,NODE:.status.currentNodeID'
kubectl get clusters.postgresql.cnpg.io -A
```

All nodes should be `Ready`, Longhorn volumes should return to `healthy`, and
every CNPG cluster should report `Cluster in healthy state`. Resume external
uptime alerts after application checks pass.

If the API does not return after two nodes boot, follow
[recover-cluster-from-single-node.md](recover-cluster-from-single-node.md)
only after checking the k3s and etcd logs; do not immediately initiate a
single-node recovery against an otherwise intact cluster.

## Related procedures

- [node-maintenance.md](node-maintenance.md) — take down one node while the
  other two continue serving workloads.
- [recover-cluster-from-single-node.md](recover-cluster-from-single-node.md) —
  disaster recovery when etcd quorum cannot be restored.
