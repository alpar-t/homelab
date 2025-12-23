# Roundcube Webmail

Roundcube webmail connecting to Stalwart mail server.

## Overview

- **URL**: https://webmail.newjoy.ro
- **Image**: `roundcube/roundcubemail:1.6.12-apache`
- **Database**: PostgreSQL (via CloudNativePG)
- **Mail Server**: Stalwart (IMAP for reading, SMTP for sending)

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                      │
│  User → webmail.newjoy.ro → Roundcube → Stalwart IMAP/SMTP          │
│                                │                                     │
│                                ▼                                     │
│                           PostgreSQL                                 │
│                        (sessions, settings)                          │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Setup

### 1. Add DNS Record

Add a DNS record for `webmail.newjoy.ro` pointing to your ingress or Cloudflare tunnel.

### 2. Deploy

Roundcube is deployed via ArgoCD:

```bash
kubectl apply -f apps/roundcube.yaml
```

The PostgreSQL database is automatically created by CloudNativePG.

### 3. Login

Visit https://webmail.newjoy.ro and login with your Stalwart credentials:

- **Username**: Your full email address (e.g., `alpar@newjoy.ro`)
- **Password**: Your Stalwart account password

## Mobile Access

Mobile email apps connect to Stalwart:

| Setting | Value |
|---------|-------|
| **IMAP Server** | `mail.newjoy.ro` |
| **IMAP Port** | `993` (SSL) |
| **SMTP Server** | `mail.newjoy.ro` |
| **SMTP Port** | `587` (STARTTLS) |
| **Username** | Your full email address |
| **Password** | Your Stalwart password |

## Troubleshooting

### Check Pod Status

```bash
kubectl get pods -n roundcube
kubectl logs -n roundcube deployment/roundcube
```

### Check PostgreSQL

```bash
kubectl get cluster roundcube-db -n roundcube
```

### IMAP Connection Issues

Test Stalwart connection from inside the pod:

```bash
kubectl exec -n roundcube deployment/roundcube -- \
  openssl s_client -connect stalwart.stalwart-mail.svc.cluster.local:993
```

### Database Issues

Check database credentials:

```bash
kubectl get secret roundcube-db-app -n roundcube -o yaml
```

## Future: Pocket ID Integration

This setup uses direct Stalwart login. A future enhancement could add Pocket ID SSO by:

1. Adding oauth2-proxy as a sidecar
2. Creating a small auth proxy that maps email → password from secrets
3. Injecting Authorization headers for Roundcube's `http_authentication` plugin

For now, users login with their Stalwart password (same password used for mobile apps).

## Secrets

| Secret Name | Namespace | Keys | Purpose |
|-------------|-----------|------|---------|
| `roundcube-db-app` | roundcube | `username`, `password` | PostgreSQL (auto-created by CloudNativePG) |

No manual secrets needed - the database credentials are auto-generated.
