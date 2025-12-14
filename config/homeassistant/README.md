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

- MetalLB installed — see `config/metallb/README.md`
- CloudNativePG operator installed — see `config/cloudnativepg/README.md`
- Pi-hole DNS entry for `ha-db.local` → `192.168.1.200` — see `config/pihole/manifests/custom-dns-configmap.yaml`

## Manifests

| File | Purpose |
|------|---------|
| `manifests/namespace.yaml` | Creates `homeassistant` namespace |
| `manifests/postgres-cluster.yaml` | CloudNativePG Cluster (PostgreSQL 16, single instance) |
| `manifests/postgres-service.yaml` | MetalLB LoadBalancer on `192.168.1.200:5432` |

Deployed via ArgoCD: `apps/homeassistant-db.yaml`

## Credentials

CloudNativePG auto-generates credentials — nothing is stored in the repo.

After deployment, retrieve the password:

```bash
# Get the auto-generated password
kubectl get secret homeassistant-db-app -n homeassistant \
  -o jsonpath='{.data.password}' | base64 -d

# Or get the full connection URI (for in-cluster use)
kubectl get secret homeassistant-db-app -n homeassistant \
  -o jsonpath='{.data.uri}' | base64 -d
```

Secrets created by the operator:
- `homeassistant-db-app` — application user (ha_recorder)
- `homeassistant-db-superuser` — postgres superuser

## Home Assistant Configuration

On your Home Assistant Green, edit `configuration.yaml`:

```yaml
recorder:
  db_url: postgresql://ha_recorder:YOUR_PASSWORD@ha-db.local:5432/homeassistant
  purge_keep_days: 30
  commit_interval: 1
  
  # Optional: Exclude noisy entities
  exclude:
    domains:
      - automation
      - updater
    entity_globs:
      - sensor.weather_*
    entities:
      - sun.sun
```

Replace `YOUR_PASSWORD` with the password from `homeassistant-db-app` secret.

## Verification

```bash
# Check LoadBalancer IP
kubectl get svc -n homeassistant homeassistant-db-external
# EXTERNAL-IP should be 192.168.1.200

# Check cluster status
kubectl get cluster -n homeassistant

# Check pod is running
kubectl get pods -n homeassistant
```

From Home Assistant or any LAN device:

```bash
# Test DNS
ping ha-db.local

# Test connection
psql -h ha-db.local -U ha_recorder -d homeassistant
```

## Troubleshooting

### LoadBalancer Stuck in Pending

```bash
kubectl get ipaddresspool -n metallb-system
kubectl get l2advertisement -n metallb-system
kubectl logs -n metallb-system -l app=metallb
```

### Connection Refused

```bash
# Check pod
kubectl get pods -n homeassistant -l cnpg.io/cluster=homeassistant-db

# Test from within cluster
kubectl run -it --rm psql-test --image=postgres:16 --restart=Never -- \
  psql -h homeassistant-db-rw -U ha_recorder -d homeassistant
```

### Home Assistant Can't Connect

1. `ping ha-db.local` — DNS working?
2. `nc -zv ha-db.local 5432` — port open?
3. Check password is correct
4. Check HA logs: `ha core logs | grep -i recorder`

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Single instance | HA recorder isn't critical; if DB is down, HA continues without history |
| 20Gi storage | Room for 30+ days of history; adjust based on entity count |
| Auto-generated credentials | No secrets in repo; operator manages lifecycle |
| MetalLB L2 | Simple LAN exposure; no ingress needed for TCP |

## Related

- [Home Assistant Recorder](https://www.home-assistant.io/integrations/recorder/)
- [CloudNativePG Documentation](https://cloudnative-pg.io/documentation/)
