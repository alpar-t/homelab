# Authentik - Identity Provider

Authentik provides SSO, OIDC, and application proxy for the homelab.

## Architecture

```
User → Cloudflare → nginx-ingress → Authentik
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
              Embedded Proxy       OIDC Apps            Dashboard
              (apps w/o auth)    (ArgoCD, etc.)      (app launcher)
```

## Access

- **URL:** https://auth.newjoy.ro
- **Initial Setup:** First user to access becomes admin

## First Time Setup

1. Access https://auth.newjoy.ro/if/flow/initial-setup/
2. Create your admin account
3. Configure applications and providers

## Protecting Apps Without Auth (Proxy Provider)

For apps like Longhorn that have no built-in auth:

1. In Authentik Admin → Applications → Create
2. Create a "Proxy Provider" with:
   - External host: `https://longhorn.newjoy.ro`
   - Mode: Forward auth (single application)
3. Create an Application linked to the provider
4. Create an Outpost with the application

Then update the ingress:
```yaml
annotations:
  nginx.ingress.kubernetes.io/auth-url: "http://authentik-outpost.authentik.svc.cluster.local:9000/outpost.goauthentik.io/auth/nginx"
  nginx.ingress.kubernetes.io/auth-signin: "https://auth.newjoy.ro/outpost.goauthentik.io/start?rd=$scheme://$host$request_uri"
  nginx.ingress.kubernetes.io/auth-response-headers: "Set-Cookie,X-authentik-username,X-authentik-groups,X-authentik-email"
  nginx.ingress.kubernetes.io/auth-snippet: |
    proxy_set_header X-Forwarded-Host $http_host;
```

## Apps With OIDC Support

For apps like ArgoCD that support OIDC:

1. In Authentik Admin → Applications → Create
2. Create an "OAuth2/OpenID Provider"
3. Configure the app to use Authentik as OIDC provider

## Components

| Component | Purpose | Storage |
|-----------|---------|---------|
| Server | Main application | None |
| Worker | Background tasks | None |
| PostgreSQL | Database | 2Gi SSD |
| Redis | Cache/Sessions | 1Gi SSD |

## Troubleshooting

```bash
# Check pods
kubectl get pods -n authentik

# Server logs
kubectl logs -n authentik -l app.kubernetes.io/name=authentik,app.kubernetes.io/component=server

# Worker logs
kubectl logs -n authentik -l app.kubernetes.io/name=authentik,app.kubernetes.io/component=worker
```

