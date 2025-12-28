# ownCloud Infinite Scale (oCIS)

Cloud file storage and collaboration platform with Pocket ID for SSO.

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
│                     oCIS (Rendered Manifests)                │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐           │
│  │  Proxy  │ │   Web   │ │ Storage │ │ Search  │           │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘           │
│       │          │           │           │                  │
│       ▼          ▼           ▼           ▼                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Internal IDM (user store)               │   │
│  │          Auto-provisioned from Pocket ID             │   │
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

## Deployment Approach: Rendered Manifests

Instead of using Helm + patches at deploy time, we **render the Helm chart locally** and commit the resulting manifests. This approach:

- **Explicit**: You see exactly what's being deployed
- **Simple**: No Helm/Kustomize magic in ArgoCD
- **Modifiable**: Easy to edit specific deployments

### File Structure

```
config/owncloud/
├── helm/
│   └── values.yaml           # Helm values (for re-rendering)
├── rendered/
│   ├── base.yaml             # All manifests (no secrets!)
│   ├── proxy-deployment.yaml # Modified for Pocket ID
│   ├── web-deployment.yaml   # Modified for Pocket ID  
│   ├── proxy-config.yaml     # CSP config with Pocket ID
│   └── secrets-job.yaml      # PreSync job to generate secrets
└── README.md
```

### Secrets Management

Secrets are **NOT** stored in git. Instead, a PreSync job (`secrets-job.yaml`) generates them on first deployment:
- All passwords and API keys are randomly generated
- LDAP CA and server certificates are auto-generated
- IDP signing keys are auto-generated
- Secrets are only created if they don't exist (idempotent)

### Re-rendering the Chart

When upgrading oCIS or changing base configuration:

```bash
# Clone the chart
git clone --depth 1 https://github.com/owncloud/ocis-charts.git /tmp/ocis-charts

# Render with values
helm template ocis /tmp/ocis-charts/charts/ocis \
  --namespace owncloud \
  --values config/owncloud/helm/values.yaml \
  > /tmp/ocis-rendered.yaml

# Extract base (excluding proxy/web deployments and proxy-config)
# Then manually update proxy-deployment.yaml, web-deployment.yaml, proxy-config.yaml
# with the Pocket ID changes marked with "=== Pocket ID OIDC Configuration ==="
```

## Modified Files for Pocket ID

### `proxy-deployment.yaml`
Added environment variables:
- `OCIS_EXCLUDE_RUN_SERVICES=idp` - Disables internal IDP
- `PROXY_OIDC_ISSUER=https://auth.newjoy.ro` - Points to Pocket ID
- `PROXY_OIDC_REWRITE_WELLKNOWN=true` - Rewrites .well-known
- `PROXY_USER_OIDC_CLAIM=preferred_username` - User claim mapping
- `PROXY_AUTOPROVISION_ACCOUNTS=true` - Auto-creates users
- `PROXY_ROLE_ASSIGNMENT_DRIVER=oidc` - Role assignment from claims

### `web-deployment.yaml`
Changed:
- `WEB_OIDC_AUTHORITY=https://auth.newjoy.ro` - Points to Pocket ID

### `proxy-config.yaml`
Added to CSP `connect-src`:
- `https://auth.newjoy.ro/`

## Prerequisites in Pocket ID

### 1. Configure User Groups

Add custom claims to your groups for role assignment:

| Group | Custom Claim Key | Custom Claim Value | oCIS Role |
|-------|------------------|-------------------|-----------|
| `advanced_apps` | `roles` | `admin` | Admin |
| `family_users` | `roles` | `user` | User |

### 2. Create OIDC Client (Web)

1. **Name**: ownCloud
2. **Callback URLs**: 
   - `https://drive.newjoy.ro/`
   - `https://drive.newjoy.ro/oidc-callback.html`
   - `https://drive.newjoy.ro/oidc-silent-redirect.html`
3. **Public Client**: Yes
4. Add your groups to the client
5. Copy Client ID to `web-deployment.yaml` → `WEB_OIDC_CLIENT_ID`

### 3. Create Desktop/Mobile Clients

Hardcoded Client IDs (create as Public Clients):

| Client | Client ID | Callback |
|--------|-----------|----------|
| Desktop | `xdXOt13JKxym1B1QcEncf2XDkLAexMBFwiT9j6EfhhHFJhs2KM9jbjTmf8JBXE69` | `http://127.0.0.1:*` |
| iOS | `mxd5OQDk6es5LzOzRvidJNfXLUZS2oN3oUFeXPP8LpPrhx3UroJFduGEYIBOxkY1` | `oc://ios.owncloud.com` |
| Android | `e4rAsNUSIUs0lF4nbv9FmCeUkTlV9GdgTLDH1b5uie7syb90SzEVrbN7HIpmWJeD` | `oc://android.owncloud.com` |

## Storage

| Component | Storage Class | Size |
|-----------|--------------|------|
| User Files | longhorn-hdd | 1.5TB |
| Search Index | longhorn-ssd | 15Gi |
| Thumbnails | longhorn-ssd | 30Gi |
| NATS | longhorn-ssd | 1Gi |
| IDM | longhorn-ssd | 1Gi |

## Troubleshooting

```bash
# Check pods
kubectl get pods -n owncloud

# Verify IDP is not running (should return nothing)
kubectl get pods -n owncloud | grep idp

# View proxy logs for auth issues
kubectl logs -n owncloud -l app=proxy -f
```

### Common Issues

1. **"Not logged in" after auth** - Check user is in a group with `roles` custom claim
2. **CSP errors** - Verify `proxy-config.yaml` has Pocket ID in `connect-src`
3. **Apps don't work** - Verify hardcoded Client IDs exist as Public Clients

## References

- [Pocket ID oCIS Integration](https://pocket-id.org/docs/client-examples/oCIS)
- [oCIS Helm Chart](https://github.com/owncloud/ocis-charts)
