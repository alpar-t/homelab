# Roundcube Webmail

Roundcube webmail with Pocket ID SSO, connecting to Stalwart mail server.

## Overview

- **URL**: https://webmail.newjoy.ro
- **Image**: `roundcube/roundcubemail:1.6.12-apache`
- **Database**: PostgreSQL (via CloudNativePG)
- **Mail Server**: Stalwart (IMAP/SMTP with OAUTHBEARER)
- **Authentication**: Pocket ID via OAuth2

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│  User → webmail.newjoy.ro → Roundcube                                   │
│                                │                                         │
│                    ┌───────────┴───────────┐                            │
│                    │                       │                            │
│                    ▼                       ▼                            │
│              Pocket ID              Stalwart                            │
│           (OAuth2 login)         (IMAP/SMTP)                           │
│                    │                   ▲                                │
│                    │                   │                                │
│                    └───────────────────┘                                │
│                      OAUTHBEARER token                                  │
│                                                                          │
│  Storage: PostgreSQL (sessions/settings)                                │
└─────────────────────────────────────────────────────────────────────────┘
```

### Authentication Flow

1. User visits `webmail.newjoy.ro`
2. Roundcube redirects to Pocket ID for OAuth2 login
3. User authenticates with Pocket ID
4. Pocket ID returns access token to Roundcube
5. Roundcube connects to Stalwart IMAP/SMTP using **OAUTHBEARER** with the token
6. Stalwart validates the token against Pocket ID

## Setup

### 1. Create Pocket ID Application

In Pocket ID admin:

1. Create new application: **Roundcube Webmail**
2. Set redirect URI: `https://webmail.newjoy.ro/index.php/login/oauth`
3. Note the `client_id` and `client_secret`

### 2. Create Secret

```bash
kubectl create secret generic oauth2-proxy-roundcube \
  --namespace roundcube \
  --from-literal=client-id="YOUR_POCKET_ID_CLIENT_ID" \
  --from-literal=client-secret="YOUR_POCKET_ID_CLIENT_SECRET" \
  --from-literal=cookie-secret="$(openssl rand -hex 16)"  # Not used by Roundcube, but kept for compatibility
```

### 3. Add DNS Record

Add a DNS record for `webmail.newjoy.ro` pointing to your ingress or Cloudflare tunnel.

### 4. Deploy

Roundcube is deployed via ArgoCD:

```bash
kubectl apply -f apps/roundcube.yaml
```

## Mobile Access

Mobile email apps connect directly to Stalwart (not through Roundcube):

| Setting | Value |
|---------|-------|
| **IMAP Server** | `mail.newjoy.ro` |
| **IMAP Port** | `993` (SSL) |
| **SMTP Server** | `mail.newjoy.ro` |
| **SMTP Port** | `587` (STARTTLS) |
| **Username** | Your Stalwart username (e.g., `alpar`) |
| **Password** | Your Stalwart password |

> **Note**: Mobile apps use password authentication. OAuth2/OAUTHBEARER is only for webmail.

## Troubleshooting

### Check Pod Status

```bash
kubectl get pods -n roundcube
kubectl logs -n roundcube deployment/roundcube
```

### Check OAuth Configuration

Verify the OAuth secret exists:

```bash
kubectl get secret roundcube-oauth -n roundcube
```

### OAuth Callback Error

If you get an error on the OAuth callback, check:
1. Redirect URI in Pocket ID matches: `https://webmail.newjoy.ro/index.php/login/oauth`
2. The secret has correct `client-id` and `client-secret`

### IMAP Connection Issues

Test Stalwart connection from inside the pod:

```bash
kubectl exec -n roundcube deployment/roundcube -- \
  nc -zv stalwart.stalwart-mail.svc.cluster.local 143
```

## Secrets Reference

| Secret Name | Namespace | Keys | Purpose |
|-------------|-----------|------|---------|
| `roundcube-db-app` | roundcube | `username`, `password` | PostgreSQL (auto-created by CloudNativePG) |
| `oauth2-proxy-roundcube` | roundcube | `client-id`, `client-secret`, `cookie-secret` | Pocket ID OAuth2 credentials |
