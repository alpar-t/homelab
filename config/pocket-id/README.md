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

### Backup

1. **PostgreSQL data** - Handled by Longhorn snapshots
2. **Secrets** - Backup the encryption key:
   ```bash
   kubectl get secret pocket-id-secrets -n pocket-id -o yaml > pocket-id-secrets-backup.yaml
   ```

### Restore

1. Restore the Longhorn PVC (PostgreSQL data)
2. Restore the secret:
   ```bash
   kubectl apply -f pocket-id-secrets-backup.yaml
   ```

If starting fresh (no data to preserve):
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

