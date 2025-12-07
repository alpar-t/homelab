# Authelia - Single Sign-On

Authelia provides SSO authentication for all internal services.

## Architecture

```
User → Cloudflare → ingress-nginx → Authelia (forward auth) → App
                                         ↓
                                   (if not logged in)
                                         ↓
                                   auth.newjoy.ro login page
```

## Deployment

Secrets are **auto-generated** on first deployment via a Kubernetes Job.

### 1. Push and Sync

```bash
git add -A && git commit -m "Add Authelia" && git push
# ArgoCD will:
# 1. Create namespace
# 2. Run secret generation job (if secrets don't exist)
# 3. Deploy Authelia
```

### 2. Retrieve Generated Password

A secure random password is generated automatically. Retrieve it:

```bash
kubectl get secret authelia-secrets -n authelia -o jsonpath='{.data.ADMIN_PASSWORD}' | base64 -d && echo
```

**Credentials:**
- Username: `admin`
- Password: (output from above command)

### 3. Change Password (Optional)

To set your own password:

```bash
# Install argon2 (macOS)
brew install argon2

# Generate hash for your password
PASSWORD_HASH=$(echo -n "your-actual-password" | argon2 $(openssl rand -base64 16) -id -e)

# Create updated users file
cat > users.yaml << EOF
users:
  admin:
    displayname: "Admin"
    email: torokalpar@gmail.com
    password: "$PASSWORD_HASH"
    groups:
      - admins
EOF

# Update the secret
kubectl create secret generic authelia-secrets \
  --namespace=authelia \
  --from-file=users.yaml=users.yaml \
  --dry-run=client -o yaml | kubectl apply -f -

# Clean up
rm users.yaml

# Restart Authelia to pick up changes
kubectl rollout restart deployment authelia -n authelia
```

### Manual Secret Creation (Alternative)

If you prefer to create secrets manually before deployment:

<details>
<summary>Click to expand manual steps</summary>

```bash
# Generate secrets
JWT_SECRET=$(openssl rand -base64 32)
SESSION_SECRET=$(openssl rand -base64 32)
STORAGE_ENCRYPTION_KEY=$(openssl rand -base64 32)

# Create password hash
PASSWORD_HASH=$(echo -n "yourpassword" | argon2 $(openssl rand -base64 16) -id -e)

# Create users file
cat > users.yaml << EOF
users:
  admin:
    displayname: "Admin"
    email: your-email@gmail.com
    password: "$PASSWORD_HASH"
    groups:
      - admins
EOF

# Create namespace and secret
kubectl create namespace authelia
kubectl create secret generic authelia-secrets \
  --namespace=authelia \
  --from-literal=JWT_SECRET="$JWT_SECRET" \
  --from-literal=SESSION_SECRET="$SESSION_SECRET" \
  --from-literal=STORAGE_ENCRYPTION_KEY="$STORAGE_ENCRYPTION_KEY" \
  --from-file=users.yaml=users.yaml

rm users.yaml
```

</details>

## Configure Apps to Use Authelia

Add these annotations to any Ingress you want to protect:

```yaml
metadata:
  annotations:
    nginx.ingress.kubernetes.io/auth-url: "http://authelia.authelia.svc.cluster.local/api/authz/forward-auth"
    nginx.ingress.kubernetes.io/auth-signin: "https://auth.newjoy.ro/?rd=https://$http_host$request_uri"
    nginx.ingress.kubernetes.io/auth-response-headers: "Remote-User,Remote-Groups,Remote-Email,Remote-Name"
    nginx.ingress.kubernetes.io/proxy-buffer-size: "8k"
    nginx.ingress.kubernetes.io/auth-snippet: |
      proxy_set_header Accept "";
      proxy_set_header X-Forwarded-Proto https;
      proxy_set_header X-Forwarded-Host $http_host;
      proxy_set_header X-Forwarded-Uri $request_uri;
      proxy_set_header X-Forwarded-Method $request_method;
```

**Note:** The `Accept ""` header clears the Accept header so Authelia returns 401 (which nginx handles) instead of 302 (which nginx doesn't handle). The `X-Forwarded-Proto https` is required because Cloudflare handles TLS termination.

See `config/longhorn/ingress.yaml` for an example.

## Access

Login page: https://auth.newjoy.ro

## Access Control Policies

Configured in `values.yaml`:

- `bypass` - No auth required (public)
- `one_factor` - Password only
- `two_factor` - Password + TOTP

Current rules:
- `newjoy.ro`, `www.newjoy.ro` → bypass (public)
- `*.newjoy.ro` → one_factor (protected)

## Adding Google OIDC (Optional)

To allow "Login with Google":

1. Create OAuth credentials in Google Cloud Console
2. Update `values.yaml`:

```yaml
configMap:
  identity_providers:
    oidc:
      enabled: true
      clients:
        - client_id: authelia
          client_name: Authelia
          client_secret: '$pbkdf2-sha512$...'  # hashed secret
          authorization_policy: one_factor
          redirect_uris:
            - https://auth.newjoy.ro/api/oidc/callback
```

## Troubleshooting

```bash
# Check Authelia logs
kubectl logs -n authelia deploy/authelia -f

# Check if Authelia is responding
kubectl port-forward -n authelia svc/authelia 9091:9091
curl http://localhost:9091/api/health
```

