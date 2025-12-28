# ownCloud Infinite Scale (oCIS)

Cloud file storage and collaboration platform deployed via the official oCIS Helm chart with Pocket ID for SSO.

Based on: [Pocket ID oCIS Integration](https://pocket-id.org/docs/client-examples/oCIS)

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
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘           │
│       │          │           │           │                  │
│       │    ┌─────┴───────────┼───────────┘                  │
│       │    │                 │                               │
│       ▼    ▼                 ▼                               │
│  ┌─────────────┐       ┌──────────┐                         │
│  │  Internal   │       │  Tika    │ (shared with paperless) │
│  │    IDM      │       │ (external)│                         │
│  │ (user store)│       └──────────┘                         │
│  └─────────────┘                                             │
└─────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│  Pocket ID  │      │   NATS      │      │  OnlyOffice │
│   (OIDC)    │      │ (messaging) │      │  (internal) │
│auth.newjoy.ro│     └─────────────┘      │             │
└─────────────┘                           └─────────────┘
```

### Key Design

- **Authentication**: Pocket ID (external OIDC)
- **User Storage**: Internal IDM with auto-provisioning
- **Internal IDP**: Disabled via `OCIS_EXCLUDE_RUN_SERVICES=idp`

## Prerequisites

### 1. Configure Pocket ID User Groups

Add custom claims to your existing groups for role assignment:

| Group | Custom Claim Key | Custom Claim Value | oCIS Role |
|-------|------------------|-------------------|-----------|
| `advanced_apps` | `roles` | `admin` | Admin |
| `family_users` | `roles` | `user` | User |

Steps:
1. Go to https://auth.newjoy.ro → **User Groups**
2. Click **...** → **Edit** on each group
3. Add custom claim: key=`roles`, value=`admin` or `user`

### 2. Create Pocket ID OIDC Client (Web)

1. Go to **Admin** → **OIDC Clients** → **Add OIDC Client**
2. Configure:
   - **Name**: ownCloud
   - **Callback URLs**: 
     - `https://drive.newjoy.ro/`
     - `https://drive.newjoy.ro/oidc-callback.html`
     - `https://drive.newjoy.ro/oidc-silent-redirect.html`
   - **Public Client**: ✅ Yes
3. Save and copy the **Client ID**
4. Edit the client and add groups: `advanced_apps`, `family_users`
5. Update `values.yaml` with the Client ID in `services.web.config.oidc.webClientID`

### 3. Create OIDC Clients for Desktop/Mobile Apps

The ownCloud clients have hardcoded Client IDs. Create these as **Public Clients**:

| Client | Name | Client ID | Callback URLs |
|--------|------|-----------|---------------|
| Desktop | ownCloud Desktop | `xdXOt13JKxym1B1QcEncf2XDkLAexMBFwiT9j6EfhhHFJhs2KM9jbjTmf8JBXE69` | `http://127.0.0.1:*` |
| iOS | ownCloud iOS | `mxd5OQDk6es5LzOzRvidJNfXLUZS2oN3oUFeXPP8LpPrhx3UroJFduGEYIBOxkY1` | `oc://ios.owncloud.com` |
| Android | ownCloud Android | `e4rAsNUSIUs0lF4nbv9FmCeUkTlV9GdgTLDH1b5uie7syb90SzEVrbN7HIpmWJeD` | `oc://android.owncloud.com` |

Add your groups to each client.

## Configuration Files

### `helm/values.yaml`
Standard oCIS Helm chart values with:
- `externalUserManagement.enabled: false` (keeps internal IDM)
- Web client ID from Pocket ID
- Storage configuration

### `manifests/external-oidc.yaml`
Patches the Helm chart output with:
- `OCIS_EXCLUDE_RUN_SERVICES=idp` - disables internal IDP
- `OCIS_OIDC_ISSUER=https://auth.newjoy.ro` - points to Pocket ID
- `PROXY_AUTOPROVISION_ACCOUNTS=true` - auto-creates users
- `PROXY_ROLE_ASSIGNMENT_DRIVER=oidc` - assigns roles from OIDC claims
- CSP configuration allowing Pocket ID

## Deployment

ArgoCD application with:
- oCIS Helm chart from `https://github.com/owncloud/ocis-charts`
- External OIDC patches from `manifests/`
- Server-Side Apply for strategic merge patching

## Storage

| Component | Storage Class | Size | Purpose |
|-----------|--------------|------|---------|
| User Files | longhorn-hdd | 1.5TB | Primary file storage |
| Search Index | longhorn-ssd | 15Gi | Bleve search index |
| Thumbnails | longhorn-ssd | 30Gi | Image/video thumbnails |
| NATS | longhorn-ssd | 1Gi | Message queue persistence |
| IDM | longhorn-ssd | 1Gi | Internal user database |

## Troubleshooting

### Check pod status
```bash
kubectl get pods -n owncloud
```

### Verify IDP is excluded
```bash
kubectl get pods -n owncloud | grep idp
# Should return nothing - IDP is not running
```

### View proxy logs (auth issues)
```bash
kubectl logs -n owncloud -l app=proxy -f
```

### Common Issues

1. **"Not logged in" after Pocket ID auth**
   - Verify user is in `advanced_apps` or `family_users` group
   - Check custom claims on groups (key: `roles`, value: `admin` or `user`)
   - Check proxy logs for role assignment

2. **CSP errors in browser console**
   - Verify `ocis-csp-config` ConfigMap has correct Pocket ID URL

3. **Desktop/mobile apps don't work**
   - Verify OIDC clients with exact hardcoded Client IDs exist
   - Ensure clients are marked as Public

## References

- [oCIS Documentation](https://doc.owncloud.com/ocis/next/)
- [oCIS Helm Chart](https://github.com/owncloud/ocis-charts)
- [Pocket ID oCIS Integration](https://pocket-id.org/docs/client-examples/oCIS)
