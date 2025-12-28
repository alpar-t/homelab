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

## File Structure

```
config/owncloud/
├── helm/
│   └── values.yaml              # Helm values (for re-rendering)
├── rendered/
│   ├── secrets-job.yaml         # PreSync job to generate secrets
│   └── manifests/               # Individual resource files (89 files)
│       ├── configmap-*.yaml     # ConfigMaps
│       ├── deployment-*.yaml    # Deployments (with reloader annotations)
│       ├── service-*.yaml       # Services
│       ├── pvc-*.yaml           # PersistentVolumeClaims
│       ├── cronjob-*.yaml       # CronJobs
│       └── ingress-*.yaml       # Ingress
└── README.md
```

### Key Modified Files

| File | Modification |
|------|--------------|
| `deployment-proxy.yaml` | Pocket ID OIDC config, reloader annotation |
| `deployment-web.yaml` | Pocket ID OIDC authority, reloader annotation |
| `configmap-proxy-config.yaml` | CSP allows auth.newjoy.ro |

### Secrets Management

Secrets are **NOT** stored in git. The PreSync job (`secrets-job.yaml`) generates them:
- All passwords and API keys are randomly generated
- LDAP CA and server certificates are auto-generated
- IDP signing keys are auto-generated
- Secrets are only created if they don't exist (idempotent)

### Auto-Reload on Secret Changes

All deployments have `reloader.stakater.com/auto: "true"` annotation. When secrets change, Reloader automatically triggers rolling restarts.

## Re-rendering the Chart

When upgrading oCIS or changing base configuration:

```bash
# Clone the chart
git clone --depth 1 https://github.com/owncloud/ocis-charts.git /tmp/ocis-charts

# Render with values
helm template ocis /tmp/ocis-charts/charts/ocis \
  --namespace owncloud \
  --values config/owncloud/helm/values.yaml \
  > /tmp/ocis-rendered.yaml

# Split into individual files (use script or manually)
# Then re-apply Pocket ID modifications to:
#   - deployment-proxy.yaml
#   - deployment-web.yaml  
#   - configmap-proxy-config.yaml
```

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
5. Copy Client ID to `deployment-web.yaml` → `WEB_OIDC_CLIENT_ID`

### 3. Create Desktop/Mobile Clients

Hardcoded Client IDs (create as Public Clients):

| Client | Client ID | Callback |
|--------|-----------|----------|
| Desktop | `xdXOt13JKxym1B1QcEncf2XDkLAexMBFwiT9j6EfhhHFJhs2KM9jbjTmf8JBXE69` | `http://127.0.0.1:*` |
| iOS | `mxd5OQDk6es5LzOzRvidJNfXLUZS2oN3oUFeXPP8LpPrhx3UroJFduGEYIBOxkY1` | `oc://ios.owncloud.com` |
| Android | `e4rAsNUSIUs0lF4nbv9FmCeUkTlV9GdgTLDH1b5uie7syb90SzEVrbN7HIpmWJeD` | `oc://android.owncloud.com` |

## Troubleshooting

```bash
# Check pods
kubectl get pods -n owncloud

# Verify IDP is not running (should return nothing)
kubectl get pods -n owncloud | grep idp

# View proxy logs for auth issues
kubectl logs -n owncloud -l app=proxy -f

# Check secrets were generated
kubectl get secrets -n owncloud
```

### Fresh Deployment

If secrets are mismatched, delete everything and let ArgoCD recreate:

```bash
kubectl delete secrets -n owncloud --all
kubectl delete pvc -n owncloud --all
# Then sync ArgoCD
```

## References

- [Pocket ID oCIS Integration](https://pocket-id.org/docs/client-examples/oCIS)
- [oCIS Helm Chart](https://github.com/owncloud/ocis-charts)
