# OAuth2 Proxy for OnlyOffice

Protects OnlyOffice Document Server with Pocket ID authentication.

## Why oauth2-proxy?

While WOPI tokens protect document access, adding oauth2-proxy provides:
- **Defense in depth**: Only authenticated users can access the OnlyOffice UI
- **Reduced attack surface**: Blocks unauthenticated probing of OnlyOffice endpoints
- **Consistent security**: Same SSO experience as other protected services

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           User's Browser                                 │
│  ┌─────────────────────┐                                                │
│  │ drive.newjoy.ro     │ ──── Opens document ────┐                      │
│  │ (oCIS Web UI)       │                         │                      │
│  └─────────────────────┘                         ▼                      │
│                                    ┌────────────────────────────────┐   │
│                                    │ office.newjoy.ro (iframe)     │   │
│                                    │ ← oauth2-proxy authenticates  │   │
│                                    │ ← same Pocket ID SSO session  │   │
│                                    └────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                                 │
                                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        Kubernetes Cluster                                │
│                                                                          │
│   ┌─────────────────────┐      ┌──────────────────────────────────┐    │
│   │   oauth2-proxy      │ ───► │   OnlyOffice Document Server     │    │
│   │  (authenticates)    │      │   (renders editor UI)            │    │
│   └─────────────────────┘      └──────────────────────────────────┘    │
│                                              │                          │
│                                              │ WOPI callbacks           │
│                                              │ (internal, no auth)      │
│                                              ▼                          │
│                                ┌──────────────────────────────────┐    │
│                                │ collaboration-onlyoffice (oCIS)  │    │
│                                │ (validates WOPI tokens)          │    │
│                                └──────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
```

## Prerequisites in Pocket ID

### Create OIDC Client

1. Go to Pocket ID admin → OIDC Clients → New Client
2. **Name**: OnlyOffice
3. **Callback URLs**: `https://office.newjoy.ro/oauth2/callback`
4. **Public Client**: No (confidential client)
5. Copy Client ID and Secret to create the secret below

### Create Kubernetes Secret

```bash
# Get values from Pocket ID
CLIENT_ID="<from-pocket-id>"
CLIENT_SECRET="<from-pocket-id>"
COOKIE_SECRET=$(openssl rand -hex 16)

kubectl create secret generic oauth2-proxy-onlyoffice \
  --namespace=owncloud \
  --from-literal=client-id="$CLIENT_ID" \
  --from-literal=client-secret="$CLIENT_SECRET" \
  --from-literal=cookie-secret="$COOKIE_SECRET"
```

## How it Works

1. **User opens document in oCIS** (drive.newjoy.ro)
2. **oCIS generates WOPI token** and returns iframe URL pointing to office.newjoy.ro
3. **Browser loads iframe** → oauth2-proxy checks authentication
4. **User already authenticated** via Pocket ID SSO → request passes through
5. **OnlyOffice loads** and makes WOPI callbacks to oCIS (internal, bypasses oauth2-proxy)
6. **Documents are fetched/saved** via WOPI with token validation

## Skipped Routes

The `/hosting/discovery` endpoint is skipped from auth:
- oCIS needs to query this endpoint to discover OnlyOffice capabilities
- This endpoint only returns XML describing supported file types
- No document access is possible through this endpoint

## Troubleshooting

```bash
# Check oauth2-proxy logs
kubectl logs -n owncloud -l app=oauth2-proxy-onlyoffice -f

# Verify secret exists
kubectl get secret oauth2-proxy-onlyoffice -n owncloud

# Check OnlyOffice service (should be 'documentserver' on port 80)
kubectl get svc -n owncloud | grep documentserver
```

