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

### 1. Create User Groups in Pocket ID

In Pocket ID (https://auth.newjoy.ro), create user groups for role assignment:

1. Go to **Admin** → **User Groups** → **Add Group**
2. Create these 4 groups with custom claims:

| Group Name | Friendly Name | Custom Claim Key | Custom Claim Value |
|------------|---------------|------------------|-------------------|
| `ocisAdmin` | oCIS Admin Users | `roles` | `ocisAdmin` |
| `ocisSpaceAdmin` | oCIS Space Admin Users | `roles` | `ocisSpaceAdmin` |
| `ocisUser` | oCIS User | `roles` | `ocisUser` |
| `ocisGuest` | oCIS Guest | `roles` | `ocisGuest` |

3. Assign users to appropriate groups (at minimum, add yourself to `ocisAdmin`)

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
4. Edit the client again and add **User Groups**: `ocisAdmin`, `ocisSpaceAdmin`, `ocisUser`, `ocisGuest`
5. Update `values.yaml` with the Client ID in `services.web.config.oidc.webClientID`

### 3. Create OIDC Clients for Desktop/Mobile Apps (Optional)

The ownCloud desktop and mobile clients have hardcoded Client IDs. Create these as **public clients**:

**Desktop Client:**
- Name: `ownCloud Desktop Client`
- Client ID: `xdXOt13JKxym1B1QcEncf2XDkLAexMBFwiT9j6EfhhHFJhs2KM9jbjTmf8JBXE69`
- Callback URLs: `http://127.0.0.1:*`
- Public Client: ✅

**iOS Client:**
- Name: `ownCloud iOS Client`
- Client ID: `mxd5OQDk6es5LzOzRvidJNfXLUZS2oN3oUFeXPP8LpPrhx3UroJFduGEYIBOxkY1`
- Callback URLs: `oc://ios.owncloud.com`
- Public Client: ✅

**Android Client:**
- Name: `ownCloud Android Client`
- Client ID: `e4rAsNUSIUs0lF4nbv9FmCeUkTlV9GdgTLDH1b5uie7syb90SzEVrbN7HIpmWJeD`
- Callback URLs: `oc://android.owncloud.com`
- Public Client: ✅

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
