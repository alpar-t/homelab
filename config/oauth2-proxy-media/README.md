# OAuth2 Proxy for Media Stack

Unified OIDC authentication for all media apps (Sonarr, Radarr, Prowlarr, qBittorrent)
via Pocket ID. Uses `auth_request` mode — nginx validates each request against this proxy,
then routes directly to backends.

## Setup

### 1. Create OIDC Client in Pocket ID

Create a new OIDC client at https://auth.newjoy.ro with:
- **Client ID**: `media`
- **Redirect URI**: `https://media-auth.newjoy.ro/oauth2/callback`

### 2. Generate Cookie Secret

```bash
COOKIE_SECRET=$(openssl rand -hex 16)
```

### 3. Create Kubernetes Secret

```bash
kubectl create secret generic oauth2-proxy-media -n media \
  --from-literal=client-id='YOUR_POCKET_ID_CLIENT_UUID' \
  --from-literal=client-secret='YOUR_CLIENT_SECRET' \
  --from-literal=cookie-secret='YOUR_COOKIE_SECRET'
```

## How It Works

One login at any `*.newjoy.ro` media app sets a cookie on `.newjoy.ro`,
granting access to all media apps without re-authenticating.
