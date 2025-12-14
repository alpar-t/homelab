# CloudNativePG Operator

CloudNativePG is a Kubernetes operator for managing PostgreSQL clusters with high availability, automated failover, and declarative configuration.

## Installation

Deployed via ArgoCD from `apps/cloudnativepg.yaml`. The operator installs into the `cnpg-system` namespace.

## Usage

Each application that needs PostgreSQL creates its own `Cluster` CR in its namespace. See `config/postgres/README.md` for the full architecture and per-app cluster patterns.

## Quick Reference

### Create a Database Cluster

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: myapp-db
  namespace: myapp
spec:
  instances: 2
  imageName: ghcr.io/cloudnative-pg/postgresql:16
  
  bootstrap:
    initdb:
      database: myapp
      owner: myapp
      secret:
        name: myapp-db-credentials
  
  storage:
    size: 10Gi
    storageClass: longhorn-ssd
  
  resources:
    requests:
      memory: "256Mi"
      cpu: "100m"
    limits:
      memory: "512Mi"
      cpu: "1"
```

### Create Credentials Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: myapp-db-credentials
  namespace: myapp
type: kubernetes.io/basic-auth
stringData:
  username: myapp
  password: <generate-strong-password>
```

### Connect to Database

```
postgresql://myapp:${PASSWORD}@myapp-db-rw.myapp.svc.cluster.local:5432/myapp
```

## Services Created

| Service | Purpose |
|---------|---------|
| `<cluster>-rw` | Read-write (primary) |
| `<cluster>-ro` | Read-only (replicas) |
| `<cluster>-r` | Any instance |

## Troubleshooting

```bash
# Check all clusters
kubectl get clusters -A

# Check operator logs
kubectl logs -n cnpg-system -l app.kubernetes.io/name=cloudnative-pg

# Describe specific cluster
kubectl describe cluster myapp-db -n myapp
```

## Links

- [CloudNativePG Documentation](https://cloudnative-pg.io/documentation/)
- [Helm Chart](https://github.com/cloudnative-pg/charts)

