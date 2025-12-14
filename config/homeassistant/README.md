# Home Assistant - PostgreSQL Integration

External PostgreSQL database for Home Assistant Green recorder/history.

## Overview

Home Assistant runs on a separate device (Home Assistant Green) outside the Kubernetes cluster. 
We expose a PostgreSQL database from the cluster for Home Assistant to use for its recorder integration.

```
┌─────────────────────┐         ┌──────────────────────────────────────┐
│  Home Assistant     │         │       Kubernetes Cluster             │
│  Green              │         │                                      │
│                     │  LAN    │   ┌─────────────────────────────┐    │
│  recorder:          │ ──────► │   │  homeassistant-db (PG)     │    │
│    db_url: pg://... │  :5432  │   │  via MetalLB LoadBalancer  │    │
│                     │         │   └─────────────────────────────┘    │
└─────────────────────┘         └──────────────────────────────────────┘
```

## Prerequisites

- MetalLB installed in the cluster — see `config/metallb/README.md`
- CloudNativePG operator installed — see `config/postgres/README.md`
- Local DNS entry for `ha-db.local` — see `config/pihole/README.md`

## Database Setup

### PostgreSQL Cluster

```yaml
# config/homeassistant/manifests/postgres-cluster.yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: homeassistant-db
  namespace: homeassistant
spec:
  instances: 1  # Single instance is fine for recorder
  
  imageName: ghcr.io/cloudnative-pg/postgresql:16
  
  bootstrap:
    initdb:
      database: homeassistant
      owner: ha_recorder
      secret:
        name: homeassistant-db-credentials
  
  storage:
    size: 20Gi  # History can grow; adjust based on retention
    storageClass: longhorn-ssd
  
  resources:
    requests:
      memory: "256Mi"
      cpu: "100m"
    limits:
      memory: "512Mi"
      cpu: "1"
```

### External Service (LoadBalancer)

```yaml
# config/homeassistant/manifests/postgres-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: homeassistant-db-external
  namespace: homeassistant
  annotations:
    # Request a specific IP (optional, but recommended for stability)
    metallb.universe.tf/loadBalancerIPs: 192.168.1.200
spec:
  type: LoadBalancer
  selector:
    cnpg.io/cluster: homeassistant-db
    role: primary
  ports:
  - name: postgresql
    port: 5432
    targetPort: 5432
```

### Credentials (Auto-Generated)

CloudNativePG automatically generates credentials and stores them in a Secret.
No credentials are checked into the repository.

After the cluster is created, retrieve the password:

```bash
# Get the auto-generated password
kubectl get secret homeassistant-db-app -n homeassistant \
  -o jsonpath='{.data.password}' | base64 -d

# Or get the full connection URI
kubectl get secret homeassistant-db-app -n homeassistant \
  -o jsonpath='{.data.uri}' | base64 -d
```

The operator creates these secrets:
- `homeassistant-db-app` — application user credentials (ha_recorder)
- `homeassistant-db-superuser` — postgres superuser (for admin tasks)

## Home Assistant Configuration

On your Home Assistant Green, edit `configuration.yaml`:

```yaml
recorder:
  # PostgreSQL connection string (using local DNS name)
  # Get password with: kubectl get secret homeassistant-db-app -n homeassistant -o jsonpath='{.data.password}' | base64 -d
  db_url: postgresql://ha_recorder:YOUR_PASSWORD@ha-db.local:5432/homeassistant
  
  # Optional: Tune retention
  purge_keep_days: 30
  commit_interval: 1
  
  # Optional: Exclude noisy entities to reduce database size
  exclude:
    domains:
      - automation
      - updater
    entity_globs:
      - sensor.weather_*
    entities:
      - sun.sun
```

Replace `YOUR_PASSWORD` with the password from the `homeassistant-db-app` secret.

The `ha-db.local` hostname is resolved via Pi-hole local DNS (see `config/pihole/manifests/custom-dns-configmap.yaml`).

## Verification

### Check the LoadBalancer IP

```bash
kubectl get svc -n homeassistant homeassistant-db-external
# Should show EXTERNAL-IP as 192.168.1.200 (or your chosen IP)
```

### Test DNS Resolution

From Home Assistant or any device on your network:

```bash
ping ha-db.local
# Should resolve to 192.168.1.200
```

### Test Connection from Home Assistant

SSH to Home Assistant or use the Terminal add-on:

```bash
# Install postgresql client (if needed)
apk add postgresql-client

# Test connection using DNS name
psql -h ha-db.local -U ha_recorder -d homeassistant
```

### Check Home Assistant Logs

After restarting Home Assistant:

```bash
ha core logs | grep -i recorder
# Should show successful connection, no errors
```

## Security Considerations

| Concern | Status |
|---------|--------|
| Network exposure | Database only accessible on LAN (MetalLB L2) |
| Authentication | Password required, no anonymous access |
| User permissions | `ha_recorder` only has access to `homeassistant` database |
| Encryption | Not configured (optional: enable SSL in CloudNativePG) |

For a home network, password auth is typically sufficient. If you want SSL:

```yaml
# Add to Cluster spec
spec:
  # ... other config ...
  postgresql:
    pg_hba:
    - hostssl all all 0.0.0.0/0 scram-sha-256
```

## Sizing Recommendations

| Setting | Recommendation | Notes |
|---------|----------------|-------|
| **PVC size** | 20Gi | Adjust based on retention and entity count |
| **purge_keep_days** | 30 | Longer = more disk, more RAM for queries |
| **commit_interval** | 1 (default) | Lower = more writes, higher = potential data loss |
| **Instances** | 1 | HA recorder doesn't need database HA |

### Why Single Instance?

Home Assistant recorder is not critical infrastructure:
- If database is down, HA continues running (just no history recording)
- Longhorn provides storage redundancy
- Simpler, less resource usage

## Troubleshooting

### Service Stuck in Pending

```bash
kubectl get svc -n homeassistant
# If EXTERNAL-IP is <pending>:
# 1. Check MetalLB is installed
# 2. Check IPAddressPool exists and has available IPs
# 3. Check L2Advertisement exists

kubectl get ipaddresspool -n metallb-system
kubectl get l2advertisement -n metallb-system
kubectl logs -n metallb-system -l app=metallb
```

### Connection Refused

```bash
# Check pod is running
kubectl get pods -n homeassistant -l cnpg.io/cluster=homeassistant-db

# Check service selector matches pod labels
kubectl get pods -n homeassistant --show-labels

# Test from within cluster
kubectl run -it --rm psql-test --image=postgres:16 --restart=Never -- \
  psql -h homeassistant-db-rw -U ha_recorder -d homeassistant
```

### Home Assistant Can't Connect

1. Verify DNS resolves: `ping ha-db.local`
2. Verify port is open: `nc -zv ha-db.local 5432`
3. Check password is correct
4. Check Home Assistant logs for specific error

## Related Documentation

- [Home Assistant Recorder](https://www.home-assistant.io/integrations/recorder/)
- [CloudNativePG Documentation](https://cloudnative-pg.io/documentation/)
- [MetalLB Documentation](https://metallb.io/)

