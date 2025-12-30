# Pocket-ID - Identity Provider

Pocket-ID is a passkey-first OIDC provider for the homelab. It replaces Authentik with a simpler, lighter-weight solution.

## Architecture

```
User → Cloudflare → nginx-ingress → Pocket-ID
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
              oauth2-proxy         OIDC Apps            Dashboard
            (Longhorn, Pi-hole)  (ArgoCD, etc.)      (app launcher)
                    │
                    ▼
              Backend Apps
```

## Components

| Component | Purpose | Storage |
|-----------|---------|---------|
| Pocket-ID | OIDC Provider (2 replicas) | None (stateless) |
| PostgreSQL | Database (2 instances HA) | 1Gi SSD |

## Access

- **URL:** https://auth.newjoy.ro
- **Initial Setup:** First user to register becomes admin

## First Time Setup

1. Navigate to https://auth.newjoy.ro/setup
2. Register your passkey (this becomes the admin account)
3. Configure your profile

## Creating OIDC Clients

For each app that needs authentication (Longhorn, Pi-hole, ArgoCD, etc.):

1. Go to **Admin → OIDC Clients → Create**
2. Configure:
   - **Name:** e.g., `longhorn`
   - **Redirect URIs:** e.g., `https://longhorn.newjoy.ro/oauth2/callback`
3. Copy the **Client ID** and **Client Secret**
4. Store in Kubernetes secret (see per-app README)

## Protecting Apps Without Auth (via oauth2-proxy)

Apps like Longhorn and Pi-hole have no built-in authentication. We use oauth2-proxy to add authentication:

```
User → nginx-ingress → oauth2-proxy → Backend App
                            ↓
                       Pocket-ID (OIDC)
```

See:
- `config/oauth2-proxy-longhorn/README.md`
- `config/oauth2-proxy-pihole/README.md`

## Apps With Native OIDC

For apps like ArgoCD that support OIDC natively, configure them directly:

```yaml
# Example ArgoCD OIDC config
oidc.config: |
  name: Pocket-ID
  issuer: https://auth.newjoy.ro
  clientID: <from-pocket-id>
  clientSecret: $oidc.pocket-id.clientSecret
  requestedScopes: ["openid", "profile", "email"]
```

## Disaster Recovery

### Backup Strategy

Database backups use **CloudNativePG-native backups** to Backblaze B2:

| Layer | What | Frequency | Retention |
|-------|------|-----------|-----------|
| WAL Archiving | Continuous transaction logs | Real-time | 30 days |
| Base Backup | Full database snapshot | Daily 3 AM | 30 days |
| Secrets | Encryption keys | Manual export | Keep safe! |

**Why CNPG backups instead of Longhorn?**
- Application-consistent (not just crash-consistent)
- Point-in-time recovery to any second
- pg_dump detects corruption during backup
- More storage-efficient (compressed, incremental WAL)

### Prerequisites: Create Backup Credentials

Before deploying, create the B2 credentials secret:

```bash
kubectl create secret generic cnpg-backup-credentials \
  --namespace=pocket-id \
  --from-literal=ACCESS_KEY_ID=<your-b2-key-id> \
  --from-literal=SECRET_ACCESS_KEY=<your-b2-application-key>
```

Use the same credentials as Longhorn backups (from `backblaze-backup-credentials`).

### Backup Secrets

The encryption key must be backed up separately:

```bash
kubectl get secret pocket-id-secrets -n pocket-id -o yaml > pocket-id-secrets-backup.yaml
```

### Verify Backups

```bash
# Check backup status
kubectl get backups -n pocket-id

# Check cluster backup status
kubectl get cluster pocket-id-db -n pocket-id -o jsonpath='{.status.firstRecoverabilityPoint}'

# List available backups
kubectl cnpg backup list pocket-id-db -n pocket-id
```

### Restore: Point-in-Time Recovery (PITR)

To restore to a specific point in time, create a new cluster with recovery configuration:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: pocket-id-db-restored
  namespace: pocket-id
spec:
  instances: 2
  imageName: ghcr.io/cloudnative-pg/postgresql:16
  
  bootstrap:
    recovery:
      source: pocket-id-db
      # Recover to specific point in time
      recoveryTarget:
        targetTime: "2024-01-15 10:30:00.000000+00"
  
  externalClusters:
    - name: pocket-id-db
      barmanObjectStore:
        destinationPath: "s3://homelab-longhorn-backup/cnpg/pocket-id-db"
        endpointURL: "https://s3.eu-central-003.backblazeb2.com"
        s3Credentials:
          accessKeyId:
            name: cnpg-backup-credentials
            key: ACCESS_KEY_ID
          secretAccessKey:
            name: cnpg-backup-credentials
            key: SECRET_ACCESS_KEY
        wal:
          maxParallel: 2
  
  storage:
    size: 1Gi
    storageClass: longhorn-ssd
```

### Restore: Latest State

For quick recovery to the latest state, omit `recoveryTarget`:

```yaml
bootstrap:
  recovery:
    source: pocket-id-db
```

### Restore: After Total Cluster Loss

1. Recreate the namespace and credentials secret
2. Apply the recovery cluster manifest above
3. Restore the `pocket-id-secrets` secret
4. Update Pocket-ID deployment to use the restored database

### Starting Fresh (No Data)

```bash
kubectl delete pvc -n pocket-id -l cnpg.io/cluster=pocket-id-db
kubectl delete secret pocket-id-secrets -n pocket-id
# Then resync - new secrets will be generated
```

## Troubleshooting

```bash
# Check pods
kubectl get pods -n pocket-id

# Pocket-ID logs
kubectl logs -n pocket-id -l app=pocket-id

# Database status
kubectl get cluster pocket-id-db -n pocket-id

# Database logs
kubectl logs -n pocket-id -l cnpg.io/cluster=pocket-id-db
```

## Environment Variables

Key configuration (see [full docs](https://pocket-id.org/docs/configuration/environment-variables)):

| Variable | Value | Description |
|----------|-------|-------------|
| `APP_URL` | https://auth.newjoy.ro | Public URL |
| `DB_PROVIDER` | postgres | Database type |
| `TRUST_PROXY` | true | Behind reverse proxy |
| `APP_DASHBOARD_ENABLED` | true | Show app launcher |

