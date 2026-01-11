# OAuth2 Proxy for Frigate

Provides OIDC authentication for Frigate NVR via Pocket ID.

## Setup

### 1. Create OIDC Client in Pocket ID

Create a new OIDC client at https://auth.newjoy.ro with:
- **Client ID**: `frigate`
- **Redirect URI**: `https://frigate.newjoy.ro/oauth2/callback`

### 2. Generate Cookie Secret

```bash
COOKIE_SECRET=$(openssl rand -hex 16)
```

### 3. Create Kubernetes Secret

```bash
kubectl create secret generic oauth2-proxy-frigate -n frigate \
  --from-literal=client-id='frigate' \
  --from-literal=client-secret='YOUR_CLIENT_SECRET' \
  --from-literal=cookie-secret='YOUR_COOKIE_SECRET'
```

## Access

Access Frigate at: https://frigate.newjoy.ro

