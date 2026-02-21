# OpenCloud

Cloud file storage and collaboration platform with Pocket ID for SSO.

OpenCloud is a community fork of ownCloud Infinite Scale (oCIS).

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Ingress                               │
│              drive.newjoy.ro / office.newjoy.ro              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     OpenCloud (Helm Chart)                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              OpenCloud Pod                           │   │
│  │    (file sync, sharing, web UI)                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                              │                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │           Collaboration Service (WOPI)               │   │
│  │    (bridges OpenCloud ↔ OnlyOffice)                 │   │
│  └─────────────────────────────────────────────────────┘   │
│                              │                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              OnlyOffice Document Server              │   │
│  │    (document editing: Word, Excel, PowerPoint)      │   │
│  └─────────────────────────────────────────────────────┘   │
│                              │                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              PosixFS Storage (longhorn-hdd)          │   │
│  │                      3TB PVC                         │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────┐
│  Pocket ID  │
│   (OIDC)    │
│auth.newjoy.ro│
└─────────────┘
```

## Deployment

Uses the [OpenCloud Community Helm Chart](https://github.com/opencloud-eu/helm).

Key configuration:
- **External OIDC**: Pocket ID at `auth.newjoy.ro`
- **Storage**: PosixFS with Longhorn HDD (3TB)
- **Keycloak**: Disabled (using Pocket ID instead)
- **MinIO/S3**: Disabled (using PosixFS for simplicity)
- **OnlyOffice**: Built-in (managed by the Helm chart)
- **Collaboration**: WOPI service for document editing

## External OIDC (Pocket ID) Configuration

When `global.oidc.issuer` is set, the Helm chart automatically configures:
- `PROXY_AUTOPROVISION_ACCOUNTS=true` (creates LDAP users on first OIDC login)
- `PROXY_OIDC_REWRITE_WELLKNOWN=true` (exposes IDP discovery via OpenCloud URL)
- `PROXY_ROLE_ASSIGNMENT_DRIVER=oidc` (assigns roles based on OIDC claims)
- `GRAPH_USERNAME_MATCH=none` (allows any username characters)
- `GRAPH_ASSIGN_DEFAULT_USER_ROLE=false` (no fallback, roles come from OIDC only)

The built-in `idp` service is excluded (`excludeServices: ["idp"]`) since Pocket ID
handles authentication. The internal `idm` (LDAP) service must remain running as the
writable backend for auto-provisioned accounts.

### Custom Role Mapping

The chart's `oidc` driver uses a hardcoded default mapping that expects claim values
like `opencloudAdmin`/`opencloudUser`. This mapping can only be changed via a
`proxy.yaml` config file -- there are no env vars for it, and the chart doesn't
expose a values key.

A PreSync Job (`manifests/proxy-config-job.yaml`) writes a custom `proxy.yaml` to the
config PVC that accepts both Pocket ID's standard claim values (`admin`, `user`) and
OpenCloud's defaults (`opencloudAdmin`, `opencloudUser`):

| Claim Value | OpenCloud Role |
|---|---|
| `admin` or `opencloudAdmin` | Admin |
| `opencloudSpaceAdmin` | Space Admin |
| `user` or `opencloudUser` | User |
| `guest` or `opencloudGuest` | Guest |

## Prerequisites in Pocket ID

### 1. Create Role Groups

Create groups with a `roles` custom claim in Pocket ID. Thanks to the custom role
mapping, you can use simple claim values:

| Group Name | Custom Claim Key | Custom Claim Value | OpenCloud Role |
|---|---|---|---|
| (your choice) | `roles` | `admin` | Full admin access |
| (your choice) | `roles` | `user` | Standard user |

At minimum, create groups for `admin` and `user` roles. Then:
1. Assign admin users to the admin group
2. Assign regular users to the user group
3. Edit the OpenCloud OIDC client and add these groups so claims are included in tokens

If a user is in multiple groups, the first matching role wins
(admin > spaceadmin > user > guest).

### 2. Create OIDC Client (Web)

1. **Name**: OpenCloud
2. **Callback URLs**:
   - `https://drive.newjoy.ro/`
   - `https://drive.newjoy.ro/oidc-callback.html`
   - `https://drive.newjoy.ro/oidc-silent-redirect.html`
3. **Public Client**: Yes (OpenCloud uses authorization code flow with PKCE)
4. **Groups**: Add the role groups created above
5. Copy Client ID to the ArgoCD Application values (`global.oidc.clientId`)

### 2. Create Desktop/Mobile Clients

OpenCloud has its own native apps with hardcoded Client IDs. Create as **Public Clients**:

| App | Client ID | Callback URL |
|-----|-----------|--------------|
| Desktop | `OpenCloudDesktop` | `http://127.0.0.1` |
| iOS | `OpenCloudIOS` | `oc://ios.opencloud.eu` |
| Android | `OpenCloudAndroid` | `oc://android.opencloud.eu` |

### Download Apps

- **Desktop**: [GitHub Releases](https://github.com/opencloud-eu/desktop/releases)
- **iOS**: App Store (search "OpenCloud")
- **Android**: Play Store (search "OpenCloud")

## Secrets

Secrets are generated by a PreSync job (`manifests/secrets-job.yaml`):
- `opencloud-admin`: Admin password (auto-generated)

## Components

| Component | Purpose |
|-----------|---------|
| OpenCloud | Main file sync & sharing server |
| Collaboration | WOPI server bridging OpenCloud ↔ OnlyOffice |
| OnlyOffice | Document editing (Word, Excel, PowerPoint, embedded PostgreSQL) |

## Troubleshooting

```bash
# Check all pods
kubectl get pods -n opencloud

# View OpenCloud logs
kubectl logs -n opencloud -l app.kubernetes.io/name=opencloud -f

# View OnlyOffice logs
kubectl logs -n opencloud -l app.kubernetes.io/component=onlyoffice -f

# View Collaboration service logs
kubectl logs -n opencloud -l app.kubernetes.io/component=collaboration -f

# Check secrets were generated
kubectl get secrets -n opencloud
```

### Fresh Deployment

If secrets are mismatched, delete everything and let ArgoCD recreate:

```bash
kubectl delete secrets -n opencloud --all
kubectl delete pvc -n opencloud --all
# Then sync ArgoCD
```

## Migration from ownCloud

Since data is not being migrated, simply:
1. Sync files to local machine using ownCloud desktop client
2. Delete ownCloud from ArgoCD
3. Deploy OpenCloud
4. Download and install OpenCloud desktop client
5. Configure to sync to `drive.newjoy.ro`
6. Wait for files to re-upload

## References

- [OpenCloud Helm Charts](https://github.com/opencloud-eu/helm)
- [OpenCloud Documentation](https://docs.opencloud.eu/)
- [External IDP Configuration](https://docs.opencloud.eu/docs/admin/configuration/authentication-and-user-management/external-idp) -- required env vars and role assignment
- [Proxy Environment Variables](https://docs.opencloud.eu/docs/dev/server/services/proxy/environment-variables) -- full list of PROXY_* settings
- [Pocket ID oCIS Client Example](https://pocket-id.org/docs/client-examples/oCIS) -- Pocket ID groups and OIDC role mapping setup
- [Pocket ID Documentation](https://pocket-id.org/docs/)
- [OpenCloud Desktop Releases](https://github.com/opencloud-eu/desktop/releases)
