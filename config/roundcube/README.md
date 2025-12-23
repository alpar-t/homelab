# Roundcube Webmail

Roundcube webmail connecting to Stalwart mail server with Pocket ID SSO.

## Overview

- **URL**: https://webmail.newjoy.ro
- **Image**: `roundcube/roundcubemail:1.6.12-apache`
- **Database**: PostgreSQL (via CloudNativePG)
- **Mail Server**: Stalwart (IMAP for reading, SMTP for sending)
- **Authentication**: Pocket ID via oauth2-proxy

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│  User → Pocket ID (OIDC) → oauth2-proxy → nginx (auth-mapper)           │
│                                                     │                    │
│                                                     ▼                    │
│                         ┌───────────────────────────────────────────┐   │
│                         │            Roundcube                       │   │
│                         │    (receives Basic Auth header)            │   │
│                         │              │           │                 │   │
│                         │              ▼           ▼                 │   │
│                         │         PostgreSQL   Stalwart              │   │
│                         │        (sessions)   (IMAP/SMTP)            │   │
│                         └───────────────────────────────────────────┘   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Authentication Flow

1. User visits `webmail.newjoy.ro`
2. **oauth2-proxy** redirects to Pocket ID for login
3. After OIDC authentication, oauth2-proxy sets `X-Auth-Request-Email` header
4. **nginx auth-mapper** extracts email, looks up Stalwart password from secret
5. nginx creates `Authorization: Basic ...` header with username:password
6. **Roundcube** receives Basic Auth, uses `http_authentication` plugin to auto-login

## Setup

### 1. Create Pocket ID Application

In Pocket ID admin:

1. Create new application: **Roundcube Webmail**
2. Set redirect URI: `https://webmail.newjoy.ro/oauth2/callback`
3. Note the `client_id` and `client_secret`

### 2. Create Secrets

#### oauth2-proxy credentials

```bash
# Generate cookie secret
COOKIE_SECRET=$(openssl rand -base64 32 | tr -d '\n')

kubectl create secret generic oauth2-proxy-roundcube \
  --namespace roundcube \
  --from-literal=client-id="YOUR_POCKET_ID_CLIENT_ID" \
  --from-literal=client-secret="YOUR_POCKET_ID_CLIENT_SECRET" \
  --from-literal=cookie-secret="$COOKIE_SECRET"
```

#### User credentials (for alpar and kinga)

These map Pocket ID users to their Stalwart passwords:

```bash
kubectl create secret generic roundcube-user-credentials \
  --namespace roundcube \
  --from-literal=alpar-password="ALPAR_STALWART_PASSWORD" \
  --from-literal=kinga-password="KINGA_STALWART_PASSWORD"
```

> **Note**: The password file names must match the username part of the email.
> For `alpar@newjoy.ro`, the file is `alpar-password`.

### 3. Add DNS Record

Add a DNS record for `webmail.newjoy.ro` pointing to your ingress or Cloudflare tunnel.

### 4. Deploy

Roundcube is deployed via ArgoCD:

```bash
kubectl apply -f apps/roundcube.yaml
```

## Adding New Users

To add a new user (e.g., `newuser@newjoy.ro`):

1. Create the user in Stalwart (via admin UI or OIDC auto-create)
2. Update the `roundcube-user-credentials` secret:

```bash
kubectl patch secret roundcube-user-credentials -n roundcube \
  --type='json' \
  -p='[{"op": "add", "path": "/data/newuser-password", "value": "'$(echo -n "THEIR_PASSWORD" | base64)'"}]'
```

3. The user can now login with their Pocket ID account

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

## Troubleshooting

### Check Pod Status

```bash
kubectl get pods -n roundcube
kubectl logs -n roundcube deployment/roundcube
kubectl logs -n roundcube deployment/oauth2-proxy-roundcube -c oauth2-proxy
kubectl logs -n roundcube deployment/oauth2-proxy-roundcube -c auth-mapper
```

### Test OAuth Flow

1. Visit https://webmail.newjoy.ro
2. You should be redirected to Pocket ID
3. After login, check nginx logs for auth-mapper output

### Check Secrets

```bash
# Verify oauth2-proxy secret
kubectl get secret oauth2-proxy-roundcube -n roundcube

# Verify user credentials
kubectl get secret roundcube-user-credentials -n roundcube -o yaml
```

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
| `oauth2-proxy-roundcube` | roundcube | `client-id`, `client-secret`, `cookie-secret` | Pocket ID OIDC credentials |
| `roundcube-user-credentials` | roundcube | `alpar-password`, `kinga-password` | Stalwart passwords for SSO users |
