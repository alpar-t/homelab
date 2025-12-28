# ownCloud Infinite Scale

ownCloud Infinite Scale (oCIS) deployment for file sync and sharing with integrated office editing.

## Features

- **File Sync & Share**: Desktop clients for Windows, macOS, Linux; mobile apps for iOS and Android
- **Office Integration**: OnlyOffice for document, spreadsheet, and presentation editing
- **Authentication**: OIDC integration with Pocket ID (external IDP)
- **Storage**: Posix FS driver for easy migration and direct filesystem access
- **Performance**: Go-based microservices architecture (no database required!)
- **Full-text Search**: Reuses Apache Tika from paperless-ngx for content extraction

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Ingress (drive.newjoy.ro)                     │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────┐
│         oCIS            │     │   OnlyOffice DocServer  │
│   (Posix FS driver)     │────▶│   (internal service)    │
│                         │     │                         │
│  Auth: Pocket ID (OIDC) │     └─────────────────────────┘
└─────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Storage                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────┐ │
│  │ User Data   │  │   Config    │  │ Thumbnails  │  │ Search  │ │
│  │   (HDD)     │  │   (SSD)     │  │   (SSD)     │  │  (SSD)  │ │
│  │  1500Gi     │  │    10Gi     │  │    30Gi     │  │  15Gi   │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Prerequisites

### 1. Create OIDC Client in Pocket ID

Before deploying, you must create an OIDC client in Pocket ID:

1. Log in to Pocket ID admin panel at `https://auth.newjoy.ro`

2. Navigate to **OIDC Clients** → **Create New Client**

3. Configure the client with these settings:

   | Setting | Value |
   |---------|-------|
   | **Client Name** | `ownCloud` |
   | **Client ID** | (auto-generated, copy this) |
   | **Client Secret** | (auto-generated, copy this) |
   | **Redirect URIs** | `https://drive.newjoy.ro/` |
   |  | `https://drive.newjoy.ro/oidc-callback.html` |
   |  | `https://drive.newjoy.ro/oidc-silent-redirect.html` |
   | **Post Logout Redirect URIs** | `https://drive.newjoy.ro/` |
   | **Grant Types** | `authorization_code`, `refresh_token` |
   | **Scopes** | `openid`, `profile`, `email`, `offline_access` |

4. Save the client and note down the **Client ID** and **Client Secret**

### 2. Create the OIDC Secret

After creating the OIDC client, create the Kubernetes secret:

```bash
# Create namespace first
kubectl create namespace owncloud

# Create the OIDC secret with your Pocket ID client ID
# (no secret needed for public clients)
kubectl create secret generic owncloud-oidc \
  --namespace owncloud \
  --from-literal=client-id='YOUR_CLIENT_ID_FROM_POCKET_ID'
```

**Important**: Replace `YOUR_CLIENT_ID_FROM_POCKET_ID` with the actual Client ID from Pocket ID.

### 3. Create the Email Secret

Create a secret for the email sender address:

```bash
kubectl create secret generic owncloud-email \
  --namespace owncloud \
  --from-literal=from-address='service@newjoy.ro'
```

### 4. DNS Configuration

Ensure `drive.newjoy.ro` points to your ingress controller IP address.

## Deployment

The deployment is managed via ArgoCD. Once the OIDC secret is created, ArgoCD will automatically deploy:

1. **Namespace** and **PVCs** (sync-wave 0)
2. **Secrets Job** - generates internal secrets (sync-wave 1)
3. **oCIS** and **OnlyOffice** deployments (sync-wave 2)
4. **Ingress** (sync-wave 3)

## Storage Configuration

| Volume | Storage Class | Size | Purpose |
|--------|---------------|------|---------|
| `owncloud-data` | `longhorn-hdd` | 1500Gi | User files (Posix FS) |
| `owncloud-config` | `longhorn-ssd` | 10Gi | Config, metadata |
| `owncloud-thumbnails` | `longhorn-ssd` | 30Gi | Thumbnail cache |
| `owncloud-search` | `longhorn-ssd` | 15Gi | Search index |
| `onlyoffice-data` | `longhorn-ssd` | 10Gi | OnlyOffice cache |

All volumes use Longhorn with 2 replicas for redundancy.

## Migration from Nextcloud / Other Servers

The Posix FS driver allows direct file copying for migration:

### Step 1: Have Users Log In

Each user must log in via Pocket ID at least once to create their account in oCIS:

1. User visits `https://drive.newjoy.ro`
2. Redirected to Pocket ID for authentication
3. After login, oCIS auto-provisions the user account
4. A user directory is created in the storage

### Step 2: Find User Directories

```bash
# Exec into the oCIS pod
kubectl exec -it -n owncloud deploy/owncloud -- sh

# List user directories
ls -la /var/lib/ocis/storage/users/

# Each user has a directory like:
# /var/lib/ocis/storage/users/<username>/
```

### Step 3: Copy Files

**Option A: Using kubectl cp (for smaller amounts)**

```bash
# Copy files for a specific user
kubectl cp /local/path/to/user/files \
  owncloud/owncloud-pod:/var/lib/ocis/storage/users/<username>/

# Example:
kubectl cp ~/migration/alice/ \
  owncloud/owncloud-xxxx:/var/lib/ocis/storage/users/alice/
```

**Option B: Using a migration job (recommended for large data)**

Create a migration job that mounts both the source (via NFS/hostPath) and destination PVC:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: owncloud-migration
  namespace: owncloud
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: rsync
          image: instrumentisto/rsync-ssh
          command:
            - rsync
            - -avP
            - --chown=1000:1000
            - /source/
            - /dest/users/
          volumeMounts:
            - name: source
              mountPath: /source
              readOnly: true
            - name: dest
              mountPath: /dest
      volumes:
        - name: source
          # Mount your source data (NFS, hostPath, etc.)
          nfs:
            server: your-nfs-server
            path: /path/to/nextcloud/data
        - name: dest
          persistentVolumeClaim:
            claimName: owncloud-data
```

### Step 4: Fix Permissions

After copying, ensure files are owned by UID 1000 (oCIS user):

```bash
kubectl exec -it -n owncloud deploy/owncloud -- \
  chown -R 1000:1000 /var/lib/ocis/storage/users/
```

### Step 5: Trigger Rescan

oCIS with Posix FS driver uses inotify to detect changes. Files should appear automatically. If not, restart the pod:

```bash
kubectl rollout restart -n owncloud deploy/owncloud
```

## Client Applications

### Desktop Clients

Download from: https://owncloud.com/desktop-app/

- Windows
- macOS  
- Linux (AppImage, Flatpak, packages)

Configure with:
- **Server URL**: `https://drive.newjoy.ro`
- Authentication will redirect to Pocket ID

### Mobile Apps

- **iOS**: [App Store](https://apps.apple.com/app/owncloud/id1359583808)
- **Android**: [Google Play](https://play.google.com/store/apps/details?id=com.owncloud.android) or [F-Droid](https://f-droid.org/packages/com.owncloud.android/)

### WebDAV Access

For third-party apps, use WebDAV:

```
URL: https://drive.newjoy.ro/remote.php/webdav/
```

## Troubleshooting

### Check oCIS Logs

```bash
kubectl logs -n owncloud deploy/owncloud -f
```

### Check OnlyOffice Logs

```bash
kubectl logs -n owncloud deploy/onlyoffice -f
```

### OIDC Issues

If authentication fails:

1. Verify the OIDC secret has correct credentials:
   ```bash
   kubectl get secret -n owncloud owncloud-oidc -o yaml
   ```

2. Check Pocket ID client configuration (redirect URIs must match exactly)

3. Check oCIS logs for OIDC-related errors

### Files Not Appearing After Migration

1. Check file permissions (should be UID 1000):
   ```bash
   kubectl exec -n owncloud deploy/owncloud -- ls -la /var/lib/ocis/storage/users/
   ```

2. Check if inotify is working:
   ```bash
   kubectl logs -n owncloud deploy/owncloud | grep -i inotify
   ```

3. Restart the pod to trigger a full rescan:
   ```bash
   kubectl rollout restart -n owncloud deploy/owncloud
   ```

### OnlyOffice Not Working

1. Verify OnlyOffice is running:
   ```bash
   kubectl get pods -n owncloud -l app=onlyoffice
   ```

2. Check JWT secret matches between oCIS and OnlyOffice:
   ```bash
   kubectl get secret -n owncloud onlyoffice-secrets -o jsonpath='{.data.jwt-secret}' | base64 -d
   ```

3. Test OnlyOffice healthcheck:
   ```bash
   kubectl exec -n owncloud deploy/owncloud -- curl -s http://onlyoffice/healthcheck
   ```

## Secrets Reference

| Secret | Keys | Purpose |
|--------|------|---------|
| `owncloud-secrets` | `jwt-secret`, `machine-auth-api-key`, `transfer-secret`, `system-user-api-key` | Internal oCIS secrets (auto-generated) |
| `owncloud-oidc` | `client-id`, `client-secret` | Pocket ID OIDC credentials (**manual**) |
| `onlyoffice-secrets` | `jwt-secret` | OnlyOffice JWT auth (auto-generated) |

## Resources

- [oCIS Documentation](https://doc.owncloud.com/ocis/)
- [oCIS GitHub](https://github.com/owncloud/ocis)
- [OnlyOffice Documentation](https://helpcenter.onlyoffice.com/installation/docs-community-install-docker.aspx)
- [Pocket ID Documentation](https://github.com/pocket-id/pocket-id)

