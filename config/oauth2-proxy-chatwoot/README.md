# OAuth2 Proxy for Chatwoot

Provides OIDC authentication for Chatwoot via Pocket ID.

## Why OAuth2 Proxy?

Chatwoot's built-in OIDC support is enterprise-only. Since we're running the community edition, we use oauth2-proxy to add authentication in front of the application.

## How It Works

```
User → chat.newjoy.ro → Ingress → OAuth2 Proxy → Chatwoot
                              ↓
                         Pocket ID (auth.newjoy.ro)
```

1. User accesses chat.newjoy.ro
2. OAuth2 proxy checks for valid session
3. If no session, redirects to Pocket ID for login
4. After authentication, user is proxied to Chatwoot

## Skipped Routes

The following routes bypass authentication:

- `/api/v1/widget/*` - Customer-facing chat widget API
- `/webhooks/*` - Incoming webhooks from integrations
- `/cable` - WebSocket endpoint (uses its own auth)

## Prerequisites

### 1. Register Chatwoot as OIDC Client in Pocket ID

In Pocket ID (https://auth.newjoy.ro):
1. Go to OIDC Clients
2. Create new client:
   - Name: `Chatwoot`
   - Redirect URI: `https://chat.newjoy.ro/oauth2/callback`
3. Note the Client ID and Client Secret

### 2. Create the OAuth2 Proxy Secret

```bash
kubectl create secret generic oauth2-proxy-chatwoot \
  --namespace=chatwoot \
  --from-literal=client-id=<pocket-id-client-id> \
  --from-literal=client-secret=<pocket-id-client-secret> \
  --from-literal=cookie-secret=$(openssl rand -hex 16)
```

## Related

- [config/chatwoot/README.md](../chatwoot/README.md) - Main Chatwoot documentation
- [config/pocket-id/](../pocket-id/) - Identity provider configuration

