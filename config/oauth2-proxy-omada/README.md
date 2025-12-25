# oauth2-proxy for Omada Controller

Provides OIDC authentication for Omada Controller web UI via Pocket-ID.

## Architecture

```
User → nginx-ingress → oauth2-proxy → Omada Controller
              ↓
         Pocket-ID (OIDC)
```

**Note:** This creates double authentication:
1. First: Pocket-ID passkey authentication
2. Second: Omada Controller local admin login

This is expected since Omada doesn't support OIDC natively (only SAML).

## Access

- **URL:** https://wifi.newjoy.ro
- **Auth:** Via Pocket-ID passkey

## One-Time Setup

### 1. Create OIDC Client in Pocket-ID

1. Go to https://auth.newjoy.ro
2. Navigate to **Admin → OIDC Clients → Create**
3. Configure:
   - **Name:** `Omada Controller`
   - **Redirect URIs:** `https://wifi.newjoy.ro/oauth2/callback`
   - **Icon:** (optional) Upload Omada/TP-Link logo for dashboard
4. Click **Create**
5. Copy the **Client ID** and **Client Secret**

### 2. Create Kubernetes Secret

```bash
# Generate a random cookie secret (must be 16, 24, or 32 bytes)
COOKIE_SECRET=$(openssl rand -hex 16)

# Create the secret with values from Pocket-ID
kubectl create secret generic oauth2-proxy-omada \
  --namespace=omada-controller \
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
kubectl get secret oauth2-proxy-omada -n omada-controller -o yaml > oauth2-proxy-omada-backup.yaml

# Restore
kubectl apply -f oauth2-proxy-omada-backup.yaml
```

Or regenerate by creating a new OIDC client in Pocket-ID.

## Troubleshooting

```bash
# Check pods
kubectl get pods -n omada-controller -l app=oauth2-proxy-omada

# View logs
kubectl logs -n omada-controller -l app=oauth2-proxy-omada

# Test authentication flow
curl -I https://wifi.newjoy.ro
# Should redirect to auth.newjoy.ro for login
```

## Configuration

Key oauth2-proxy settings:

| Setting | Value | Description |
|---------|-------|-------------|
| `--provider` | oidc | OpenID Connect provider |
| `--oidc-issuer-url` | https://auth.newjoy.ro | Pocket-ID URL |
| `--upstream` | http://omada-controller:80 | Omada Controller service |
| `--cookie-secure` | true | HTTPS-only cookies |
| `--email-domain` | * | Allow all email domains |

