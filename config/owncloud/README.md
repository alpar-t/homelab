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

### 1. Configure Pocket ID User Groups

We use existing Pocket ID groups for oCIS role assignment. Add custom claims to these groups:

| Group | Custom Claim Key | Custom Claim Value | oCIS Role |
|-------|------------------|-------------------|-----------|
| `advanced_apps` | `roles` | `advanced_apps` | Admin |
| `family_users` | `roles` | `family_users` | User |

To add custom claims:
1. Go to https://auth.newjoy.ro → **User Groups**
2. Click **...** → **Edit** on each group
3. Add the custom claim key `roles` with the group name as the value

### 2. Create Pocket ID OIDC Client (Web)

1. Go to **Admin** → **OIDC Clients** → **Add Client**
2. Configure:
   - **Name**: ownCloud
   - **Callback URLs**: 
     - `https://drive.newjoy.ro/`
     - `https://drive.newjoy.ro/oidc-callback.html`
     - `https://drive.newjoy.ro/oidc-silent-redirect.html`
   - **Public Client**: ✅ Enabled
3. Save and copy the generated **Client ID**
4. Edit the client again and add **User Groups**: `advanced_apps`, `family_users`
5. Update `values.yaml` with the Client ID in `services.web.config.oidc.webClientID`

### 3. Create OIDC Clients for Desktop/Mobile Apps

The ownCloud desktop and mobile clients have **hardcoded Client IDs** that cannot be changed. You must create OIDC clients in Pocket ID with these exact Client IDs for the apps to work with external OIDC providers.

> **Note**: Since Pocket ID doesn't support hardcoded client secrets, all clients must be configured as **Public Clients** with PKCE enabled (which the ownCloud apps support).

Create these clients in Pocket ID (**Admin** → **OIDC Clients** → **Add Client**):

| Client | Name | Client ID | Callback URLs | Public |
|--------|------|-----------|---------------|--------|
| Desktop | ownCloud Desktop | `xdXOt13JKxym1B1QcEncf2XDkLAexMBFwiT9j6EfhhHFJhs2KM9jbjTmf8JBXE69` | `http://127.0.0.1:*` | ✅ |
| iOS | ownCloud iOS | `mxd5OQDk6es5LzOzRvidJNfXLUZS2oN3oUFeXPP8LpPrhx3UroJFduGEYIBOxkY1` | `oc://ios.owncloud.com` | ✅ |
| Android | ownCloud Android | `e4rAsNUSIUs0lF4nbv9FmCeUkTlV9GdgTLDH1b5uie7syb90SzEVrbN7HIpmWJeD` | `oc://android.owncloud.com` | ✅ |

For each client, also add the **User Groups**: `advanced_apps`, `family_users`

Reference: [Pocket ID oCIS Client Examples](https://pocket-id.org/docs/client-examples/oCIS)

### 2. Create Required Secrets

The oCIS Helm chart can auto-generate most secrets if not provided. Only create these if you want to manage them yourself:

```bash
# Create namespace first
kubectl create namespace owncloud

# Admin user (for initial setup - optional with external OIDC)
kubectl create secret generic owncloud-admin-secret \
  --namespace owncloud \
  --from-literal=user=admin \
  --from-literal=password=$(openssl rand -base64 32)

# Optional: Pre-create secrets (Helm chart will auto-generate if not present)
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
