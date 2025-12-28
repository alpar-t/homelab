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
         │                    │                    │
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│  Pocket ID  │      │   LLDAP     │      │  OnlyOffice │
│   (OIDC)    │      │   (LDAP)    │      │  (internal) │
│auth.newjoy.ro│      │ User Store  │      │             │
└─────────────┘      └─────────────┘      └─────────────┘
       │                    │
       │   Authentication   │   User Storage
       └────────────────────┘
```

### Authentication Flow

1. User visits `drive.newjoy.ro`
2. oCIS redirects to Pocket ID (`auth.newjoy.ro`) for authentication
3. User authenticates with Pocket ID (passkey, password, etc.)
4. Pocket ID returns OIDC token with user claims and group memberships
5. oCIS auto-provisions user in LLDAP if first login
6. oCIS assigns role based on `roles` claim from Pocket ID groups
7. User is logged in to oCIS

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

### 4. LLDAP (User Storage Backend)

LLDAP is deployed automatically in the same namespace. It provides the LDAP backend that oCIS requires for user storage when using external OIDC authentication.

- **Service**: `lldap:3890` (LDAP)
- **Web UI**: Port 17170 (for user management)
- **Storage**: Persistent (1Gi on longhorn-ssd)

> **Important**: LLDAP doesn't support LDAP modify operations, so autoprovisioning is disabled.
> Users must be manually created in LLDAP before they can log in via Pocket ID.

#### Creating Users in LLDAP

1. Port forward to the LLDAP web UI:
   ```bash
   kubectl port-forward -n owncloud svc/lldap 17170:17170
   ```

2. Get the admin password:
   ```bash
   kubectl get secret -n owncloud lldap-secrets -o jsonpath='{.data.LLDAP_LDAP_USER_PASS}' | base64 -d
   ```

3. Open http://localhost:17170 and login with `admin` / `<password>`

4. Create a new user with:
   - **User ID**: Must match the `preferred_username` from Pocket ID
   - **Email**: Must match the email in Pocket ID
   - **Display Name**: User's display name

5. The user can now log in via Pocket ID

### 5. Secrets (Auto-generated)

All secrets are auto-generated on first deployment:
- **LLDAP secrets**: Generated by `lldap-secrets-init` PreSync job
- **oCIS secrets**: Auto-generated by Helm chart

## Deployment

The deployment is managed via a single ArgoCD application (`owncloud`) that includes:
- **LLDAP** - Lightweight LDAP server for user storage (manifests)
- **oCIS Helm Chart** from `https://github.com/owncloud/ocis-charts`
- **OnlyOffice** deployed separately via custom manifest

## Storage

| Component | Storage Class | Size | Purpose |
|-----------|--------------|------|---------|
| User Files | longhorn-hdd | 1.5TB | Primary file storage |
| Search Index | longhorn-ssd | 15Gi | Bleve search index |
| Thumbnails | longhorn-ssd | 30Gi | Image/video thumbnails |
| NATS | longhorn-ssd | 1Gi | Message queue persistence |
| OnlyOffice | longhorn-ssd | 10Gi | Document server data |
| LLDAP | longhorn-ssd | 1Gi | User database (persistent, manual user creation) |

## Features

- **Authentication**: External OIDC via Pocket ID
- **User Storage**: LLDAP (manual user creation required)
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

### View LLDAP logs
```bash
kubectl logs -n lldap -l app=lldap -f
```

### View OnlyOffice logs
```bash
kubectl logs -n owncloud -l app=onlyoffice -f
```

### Check secrets
```bash
kubectl get secrets -n owncloud
```

### Access LLDAP Web UI
```bash
# Port forward to local machine
kubectl port-forward -n owncloud svc/lldap 17170:17170

# Get admin password
kubectl get secret -n owncloud lldap-secrets -o jsonpath='{.data.LLDAP_LDAP_USER_PASS}' | base64 -d

# Open http://localhost:17170 and login with admin/<password>
```

### Test LDAP Connection
```bash
# Check if oCIS can reach LLDAP
kubectl exec -n owncloud -it deploy/proxy -- nc -zv lldap 3890
```

### Common Issues

1. **"Not logged in" after Pocket ID auth**
   - **Most common cause**: User doesn't exist in LLDAP. Create the user manually (see "Creating Users in LLDAP" above)
   - Check that user is in `advanced_apps` or `family_users` group in Pocket ID
   - Verify custom claims are set on groups (key: `roles`, value: group name)
   - Check oCIS proxy logs for role assignment errors

2. **LDAP connection errors**
   - Verify LLDAP pod is running: `kubectl get pods -n owncloud -l app=lldap`
   - Check LDAP bind secret exists: `kubectl get secret -n owncloud lldap-secrets`
   - Verify password matches LLDAP admin password

3. **User not found / cannot login**
   - Autoprovisioning is disabled due to LLDAP limitations
   - Users must be manually created in LLDAP before first login
   - The LLDAP username must match the `preferred_username` claim from Pocket ID

## References

- [oCIS Documentation](https://doc.owncloud.com/ocis/next/)
- [oCIS Helm Chart](https://github.com/owncloud/ocis-charts)
- [LLDAP Documentation](https://github.com/lldap/lldap)
- [Pocket ID oCIS Integration](https://pocket-id.org/docs/client-examples/oCIS)
- [OnlyOffice Integration](https://doc.owncloud.com/ocis/next/deployment/services/s-list/collaboration.html)
