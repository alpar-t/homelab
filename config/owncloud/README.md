# ownCloud Infinite Scale (oCIS)

Cloud file storage and collaboration platform deployed via the official oCIS Helm chart.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Ingress                               │
│                   drive.newjoy.ro                            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     oCIS (Helm Chart)                        │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐           │
│  │  Proxy  │ │   Web   │ │ Storage │ │ Search  │           │
│  └────┬────┘ └─────────┘ └────┬────┘ └────┬────┘           │
│       │                       │           │                  │
│       │    ┌─────────────────┼───────────┘                  │
│       │    │                 │                               │
│       ▼    ▼                 ▼                               │
│  ┌─────────────┐       ┌──────────┐                         │
│  │    NATS     │       │  Tika    │ (shared with paperless) │
│  │  (embedded) │       │ (external)│                         │
│  └─────────────┘       └──────────┘                         │
└─────────────────────────────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│  Pocket ID  │      │  OnlyOffice │      │  Stalwart   │
│   (OIDC)    │      │  (internal) │      │   (SMTP)    │
│auth.newjoy.ro│      │             │      │             │
└─────────────┘      └─────────────┘      └─────────────┘
```

## Prerequisites

### 1. Create Pocket ID OIDC Client

In Pocket ID (https://auth.newjoy.ro), create a new OIDC client:

1. Go to **Admin** → **OIDC Clients** → **Add Client**
2. Configure:
   - **Name**: ownCloud
   - **Client ID**: `owncloud` (or auto-generated)
   - **Redirect URIs**: 
     - `https://drive.newjoy.ro/`
     - `https://drive.newjoy.ro/oidc-callback.html`
     - `https://drive.newjoy.ro/oidc-silent-redirect.html`
   - **Client Type**: Public (no secret required for web frontend)
   - **PKCE**: Enable if available
3. Save and note the Client ID

### 2. Create Required Secrets

```bash
# OIDC client configuration
kubectl create secret generic owncloud-oidc \
  --namespace owncloud \
  --from-literal=client-id=YOUR_CLIENT_ID

# Email sender (for notifications)
kubectl create secret generic owncloud-email \
  --namespace owncloud \
  --from-literal=sender=service@newjoy.ro

# Admin user (for initial setup - optional, can use OIDC user)
kubectl create secret generic owncloud-admin-secret \
  --namespace owncloud \
  --from-literal=user=admin \
  --from-literal=password=$(openssl rand -base64 32)

# Auto-generated secrets (Helm chart will create these if not present)
# JWT secret
kubectl create secret generic owncloud-jwt-secret \
  --namespace owncloud \
  --from-literal=jwt-secret=$(openssl rand -base64 32)

# Machine auth API key
kubectl create secret generic owncloud-machine-auth \
  --namespace owncloud \
  --from-literal=machine-auth-api-key=$(openssl rand -base64 32)

# Transfer secret
kubectl create secret generic owncloud-transfer-secret \
  --namespace owncloud \
  --from-literal=transfer-secret=$(openssl rand -base64 32)

# Thumbnails secret
kubectl create secret generic owncloud-thumbnails-secret \
  --namespace owncloud \
  --from-literal=thumbnails-transfer-secret=$(openssl rand -base64 32)
```

## Deployment

The deployment is managed via ArgoCD using:
- **oCIS Helm Chart** (v0.8.0) from `https://owncloud.github.io/ocis-charts`
- **OnlyOffice** deployed separately via custom manifest

## Storage

| Component | Storage Class | Size | Purpose |
|-----------|--------------|------|---------|
| User Files | longhorn-hdd | 1.5TB | Primary file storage |
| Search Index | longhorn-ssd | 15Gi | Bleve search index |
| Thumbnails | longhorn-ssd | 30Gi | Image/video thumbnails |
| IDM | longhorn-ssd | 1Gi | Identity management data |
| NATS | longhorn-ssd | 1Gi | Message queue persistence |
| Store | longhorn-ssd | 5Gi | General metadata store |
| OnlyOffice | longhorn-ssd | 10Gi | Document server data |

## Features

- **Authentication**: External OIDC via Pocket ID
- **Office Integration**: OnlyOffice Document Server (internal)
- **Full-Text Search**: Via shared Tika instance (paperless-ngx)
- **Email Notifications**: Via Stalwart mail relay

## File Migration

Since we're using the default `ocis` storage driver (not posix), files cannot be directly copied to the filesystem. Instead, use one of these methods:

### Option 1: WebDAV Upload
```bash
# Using rclone
rclone copy /path/to/files remote:drive.newjoy.ro --webdav-url=https://drive.newjoy.ro/remote.php/webdav
```

### Option 2: ownCloud Desktop Client
Use the official ownCloud desktop sync client to upload files.

### Option 3: oCIS CLI (if available)
```bash
# Check oCIS documentation for CLI import tools
```

## Troubleshooting

### Check pod status
```bash
kubectl get pods -n owncloud
```

### View oCIS logs
```bash
kubectl logs -n owncloud -l app.kubernetes.io/name=ocis -f
```

### View OnlyOffice logs
```bash
kubectl logs -n owncloud -l app=onlyoffice -f
```

### Check secrets
```bash
kubectl get secrets -n owncloud
```

## References

- [oCIS Documentation](https://doc.owncloud.com/ocis/next/)
- [oCIS Helm Chart](https://github.com/owncloud/ocis-charts)
- [OnlyOffice Integration](https://doc.owncloud.com/ocis/next/deployment/services/s-list/collaboration.html)
