# oauth2-proxy for Longhorn

Provides authentication for Longhorn UI via Pocket-ID OIDC.

## Architecture

```
User → nginx-ingress → oauth2-proxy → Longhorn UI
              ↓
         Pocket-ID (OIDC)
```

## Access

- **URL:** https://longhorn.newjoy.ro
- **Auth:** Via Pocket-ID passkey

## One-Time Setup

### 1. Create OIDC Client in Pocket-ID

1. Go to https://auth.newjoy.ro
2. Navigate to **Admin → OIDC Clients → Create**
3. Configure:
   - **Name:** `Longhorn`
   - **Redirect URIs:** `https://longhorn.newjoy.ro/oauth2/callback`
   - **Icon:** (optional) Upload Longhorn logo for dashboard
4. Click **Create**
5. Copy the **Client ID** and **Client Secret**

### 2. Create Kubernetes Secret

```bash
# Generate a random cookie secret
COOKIE_SECRET=$(openssl rand -base64 32 | tr -d '\n')

# Create the secret with values from Pocket-ID
kubectl create secret generic oauth2-proxy-longhorn \
  --namespace=longhorn-system \
  --from-literal=client-id=<CLIENT_ID_FROM_POCKET_ID> \
  --from-literal=client-secret=<CLIENT_SECRET_FROM_POCKET_ID> \
  --from-literal=cookie-secret="$COOKIE_SECRET"
```

### 3. Sync via ArgoCD

The oauth2-proxy deployment will be synced automatically by ArgoCD.

## Disaster Recovery

If restoring from backup, ensure you restore the secret or recreate it:

```bash
# Backup
kubectl get secret oauth2-proxy-longhorn -n longhorn-system -o yaml > oauth2-proxy-longhorn-backup.yaml

# Restore
kubectl apply -f oauth2-proxy-longhorn-backup.yaml
```

Or regenerate by creating a new OIDC client in Pocket-ID.

## Troubleshooting

```bash
# Check pods
kubectl get pods -n longhorn-system -l app=oauth2-proxy-longhorn

# View logs
kubectl logs -n longhorn-system -l app=oauth2-proxy-longhorn

# Test authentication flow
curl -I https://longhorn.newjoy.ro
# Should redirect to auth.newjoy.ro for login
```

## Configuration

Key oauth2-proxy settings:

| Setting | Value | Description |
|---------|-------|-------------|
| `--provider` | oidc | OpenID Connect provider |
| `--oidc-issuer-url` | https://auth.newjoy.ro | Pocket-ID URL |
| `--upstream` | http://longhorn-frontend:80 | Longhorn service |
| `--cookie-secure` | true | HTTPS-only cookies |
| `--email-domain` | * | Allow all email domains |

