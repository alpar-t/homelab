# Reloader - Auto-Restart on ConfigMap/Secret Changes

[Reloader](https://github.com/stakater/Reloader) automatically triggers rolling restarts when ConfigMaps or Secrets change.

## Why Reloader?

Kubernetes doesn't restart pods when mounted ConfigMaps/Secrets change. The pod keeps using stale data until manually restarted.

Reloader watches for changes and triggers rolling updates automatically.

## Installation

Installed via ArgoCD. See `apps/reloader.yaml`.

## Usage

Add an annotation to any Deployment, DaemonSet, or StatefulSet:

### Watch All Mounted ConfigMaps/Secrets

```yaml
metadata:
  annotations:
    reloader.stakater.com/auto: "true"
```

### Watch Specific ConfigMap

```yaml
metadata:
  annotations:
    configmap.reloader.stakater.com/reload: "my-configmap"
```

### Watch Specific Secret

```yaml
metadata:
  annotations:
    secret.reloader.stakater.com/reload: "my-secret"
```

### Watch Multiple

```yaml
metadata:
  annotations:
    configmap.reloader.stakater.com/reload: "config1,config2"
    secret.reloader.stakater.com/reload: "secret1,secret2"
```

## Current Usage

| Workload | Watches | Purpose |
|----------|---------|---------|
| Pi-hole DaemonSet | `pihole-custom-dns` | Reload local DNS entries |

## How It Works

```
1. You push ConfigMap change to Git
2. ArgoCD syncs ConfigMap to cluster
3. Reloader detects ConfigMap hash changed
4. Reloader updates annotation on the workload
5. Kubernetes performs rolling restart
6. New pods get updated ConfigMap
```

## Troubleshooting

```bash
# Check Reloader is running
kubectl get pods -n reloader

# Check Reloader logs
kubectl logs -n reloader -l app=reloader-reloader

# Verify annotation is set on workload
kubectl get daemonset pihole -n pihole -o yaml | grep -A5 annotations
```

## Related Documentation

- [Reloader GitHub](https://github.com/stakater/Reloader)
- [Helm Chart](https://github.com/stakater/Reloader/tree/master/deployments/kubernetes/chart/reloader)

