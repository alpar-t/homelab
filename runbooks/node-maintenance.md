# Node Maintenance

This runbook documents how to safely take a node offline for hardware maintenance (e.g., adding a HDD, replacing components).

## Scenario

- **Cluster**: 3-node k3s HA with embedded etcd (pufi, buksi, pamacs)
- **Problem**: Need to take a node offline temporarily for maintenance
- **Goal**: Safely drain pods and prevent Longhorn from unnecessary replica rebuilding

---

## Prerequisites

- `kubectl` access to the cluster
- SSH access to the node (for physical maintenance)
- Sufficient capacity on remaining nodes for pod scheduling

---

## Step 1: Increase Longhorn Rebuild Delay

Longhorn waits 600 seconds (10 minutes) by default before rebuilding replicas when a node goes offline. Increase this to avoid unnecessary data movement during short maintenance windows:

```bash
# Set to 1 hour (3600 seconds)
kubectl -n longhorn-system patch setting replica-replenishment-wait-interval --type=merge -p '{"value": "3600"}'
```

Verify the setting:
```bash
kubectl -n longhorn-system get setting replica-replenishment-wait-interval
```

---

## Step 2: Cordon and Drain the Node

Cordon prevents new pods from being scheduled, drain evicts existing pods:

```bash
# Replace <node-name> with actual node (e.g., pamacs, buksi, pufi)
kubectl cordon <node-name>
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data
```

**Flags explained:**
- `--ignore-daemonsets`: DaemonSet pods (Longhorn, etc.) can't be evicted and will restart when node returns
- `--delete-emptydir-data`: Allow eviction of pods using emptyDir volumes

Verify pods have been evicted:
```bash
kubectl get pods -A -o wide | grep <node-name>
# Should only show DaemonSet pods
```

---

## Step 3: Perform Maintenance

Now it's safe to:
- Shut down the node
- Add/replace hardware
- Perform any physical maintenance

---

## Step 4: Bring Node Back Online

After the node boots back up:

```bash
# Uncordon to allow pod scheduling again
kubectl uncordon <node-name>

# Verify node is Ready
kubectl get nodes
```

---

## Step 5: Restore Longhorn Settings

```bash
# Restore default 10-minute rebuild delay
kubectl -n longhorn-system patch setting replica-replenishment-wait-interval --type=merge -p '{"value": "600"}'
```

Verify Longhorn volumes are healthy:
```bash
kubectl get volumes.longhorn.io -n longhorn-system
```

---

## Quick Reference

Copy-paste commands for common nodes:

### pamacs

```bash
# Before maintenance
kubectl -n longhorn-system patch setting replica-replenishment-wait-interval --type=merge -p '{"value": "3600"}'
kubectl cordon pamacs
kubectl drain pamacs --ignore-daemonsets --delete-emptydir-data

# After maintenance
kubectl uncordon pamacs
kubectl -n longhorn-system patch setting replica-replenishment-wait-interval --type=merge -p '{"value": "600"}'
```

### buksi

```bash
# Before maintenance
kubectl -n longhorn-system patch setting replica-replenishment-wait-interval --type=merge -p '{"value": "3600"}'
kubectl cordon buksi
kubectl drain buksi --ignore-daemonsets --delete-emptydir-data

# After maintenance
kubectl uncordon buksi
kubectl -n longhorn-system patch setting replica-replenishment-wait-interval --type=merge -p '{"value": "600"}'
```

### pufi

```bash
# Before maintenance
kubectl -n longhorn-system patch setting replica-replenishment-wait-interval --type=merge -p '{"value": "3600"}'
kubectl cordon pufi
kubectl drain pufi --ignore-daemonsets --delete-emptydir-data

# After maintenance
kubectl uncordon pufi
kubectl -n longhorn-system patch setting replica-replenishment-wait-interval --type=merge -p '{"value": "600"}'
```

---

## Troubleshooting

### Drain fails with PodDisruptionBudget errors

Some pods may have PDBs that prevent eviction. Options:
```bash
# Force drain (use with caution)
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data --force

# Or delete the blocking pod manually
kubectl delete pod <pod-name> -n <namespace>
```

### Drain hangs on a specific pod

Check what's blocking:
```bash
kubectl get pods -A -o wide | grep <node-name>
kubectl describe pod <pod-name> -n <namespace>
```

### Longhorn volumes degraded after maintenance

Check volume and replica status:
```bash
kubectl get volumes.longhorn.io -n longhorn-system
kubectl get replicas.longhorn.io -n longhorn-system -o wide
```

Replicas should automatically rebuild after the node returns. If not, check Longhorn manager logs:
```bash
kubectl logs -n longhorn-system -l app=longhorn-manager --tail=100
```

---

## Related

- [config/longhorn/values.yaml](../config/longhorn/values.yaml) - Longhorn Helm values
- [configure-longhorn-disk-tags.md](./configure-longhorn-disk-tags.md) - Disk tagging for SSD/HDD classes
- [recover-cluster-from-single-node.md](./recover-cluster-from-single-node.md) - Full cluster recovery

