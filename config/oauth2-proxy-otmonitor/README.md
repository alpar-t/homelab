# OAuth2 Proxy for OTMonitor

Protects OTMonitor with Pocket ID authentication.

## Setup

### 1. Create OIDC Client in Pocket ID

1. Go to https://auth.newjoy.ro/admin
2. Create a new OIDC client:
   - **Name:** OTMonitor
   - **Callback URL:** `https://otmonitor.newjoy.ro/oauth2/callback`
3. Copy the **Client ID** and **Client Secret**

### 2. Create the Secret

```bash
# Generate a cookie secret (32-char hex)
COOKIE_SECRET=$(openssl rand -hex 16)

kubectl create secret generic oauth2-proxy-otmonitor \
  --namespace=otmonitor \
  --from-literal=client-id="YOUR_CLIENT_ID" \
  --from-literal=client-secret="YOUR_CLIENT_SECRET" \
  --from-literal=cookie-secret="$COOKIE_SECRET"
```

### 3. Deploy

The ArgoCD application will deploy automatically once the secret exists.

## Architecture

```
Internet → Ingress → oauth2-proxy → OTMonitor (port 5800)
                          ↓
                    Pocket ID (OIDC)
```

All requests to `otmonitor.newjoy.ro` go through oauth2-proxy, which:
1. Redirects unauthenticated users to Pocket ID
2. Validates the OIDC token
3. Proxies authenticated requests to OTMonitor

