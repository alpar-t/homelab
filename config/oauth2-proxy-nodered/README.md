# OAuth2 Proxy for Node-RED

Provides OIDC authentication via Pocket ID for Node-RED.

## Setup

1. **Create OIDC client in Pocket ID** (https://auth.newjoy.ro):
   - Name: `Node-RED`
   - Redirect URI: `https://nodered.newjoy.ro/oauth2/callback`
   - Note the Client ID and Client Secret

2. **Create the Kubernetes secret**:
   ```bash
   # Generate a random cookie secret (must be 16, 24, or 32 bytes)
   COOKIE_SECRET=$(openssl rand -hex 16)

   # Create the secret with values from Pocket ID
   kubectl create secret generic oauth2-proxy-nodered \
     --namespace=nodered \
     --from-literal=client-id=<CLIENT_ID_FROM_POCKET_ID> \
     --from-literal=client-secret=<CLIENT_SECRET_FROM_POCKET_ID> \
     --from-literal=cookie-secret="$COOKIE_SECRET"
   ```

## Architecture

```
Internet → Ingress → OAuth2 Proxy (port 4180) → Node-RED (port 1880)
                          ↓
                    Pocket ID (OIDC)
```

## Components

- **Deployment**: 2 replicas with pod anti-affinity for HA
- **Service**: ClusterIP exposing port 4180
- **Ingress**: Routes `nodered.newjoy.ro` through the proxy

## Notes

- The oauth2-proxy handles all authentication
- After successful auth, requests are proxied to Node-RED
- Node-RED sees all users as authenticated (no user distinction)

