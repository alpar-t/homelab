# Tandoor Recipes

A Django-based recipe management application with meal planning, shopping lists, and OIDC authentication support.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Pod: tandoor                                                │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │ nginx (sidecar) │◄───│ tandoor (app)   │                │
│  │ :80             │    │ :8080 gunicorn  │                │
│  └────────┬────────┘    └────────┬────────┘                │
│           │                      │                          │
│           ▼                      ▼                          │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │ /static, /media │    │ PostgreSQL      │                │
│  │ (PVCs)          │    │ (CloudNativePG) │                │
│  └─────────────────┘    └─────────────────┘                │
└─────────────────────────────────────────────────────────────┘
```

## Initial Setup

### 1. Deploy the Application

Apply the ArgoCD application:

```bash
kubectl apply -f apps/tandoor.yaml
```

ArgoCD will automatically:
1. Create the namespace and RBAC (sync-wave 0)
2. Deploy PostgreSQL, PVCs, and ConfigMaps (sync-wave 0)
3. Run the secrets generator job (sync-wave 1)
4. Deploy Tandoor once secrets are ready (sync-wave 2)

### 2. Configure OIDC (Optional)

After deployment, configure OIDC authentication:

1. Create an OIDC application in Pocket ID:
   - Redirect URI: `https://food.newjoy.ro/accounts/oidc/pocket-id/login/callback/`
   - Note the client ID and secret

2. Create the OIDC secret with your credentials:

```bash
kubectl create secret generic tandoor-oidc -n tandoor \
  --from-literal=socialaccount_providers.json='{
  "openid_connect": {
    "OAUTH_PKCE_ENABLED": true,
    "APPS": [
      {
        "provider_id": "pocket-id",
        "name": "Pocket ID",
        "client_id": "YOUR_CLIENT_ID",
        "secret": "YOUR_CLIENT_SECRET",
        "settings": {
          "server_url": "https://auth.newjoy.ro/.well-known/openid-configuration"
        }
      }
    ]
  }
}'
```

Replace `YOUR_CLIENT_ID` and `YOUR_CLIENT_SECRET` with your actual values.

3. The deployment will auto-restart when the secret is created/updated (via Reloader).

**Note:** The OIDC secret is optional - Tandoor will work without it, just without SSO login.

## Data Migration from Docker Compose

### Prerequisites

- Access to your Docker Compose host
- `kubectl` configured for your cluster
- Tandoor deployed and running in Kubernetes

### Step 1: Backup PostgreSQL Database

On your Docker Compose host:

```bash
# Export the database
docker exec db_recipes pg_dump -U postgres djangodb > tandoor_backup.sql
```

### Step 2: Backup Media Files

```bash
# Create a tarball of media files
tar -czvf tandoor_media.tar.gz ./recepies-media
```

### Step 3: Import PostgreSQL Database

```bash
# Copy the backup to the PostgreSQL pod
kubectl cp tandoor_backup.sql tandoor/tandoor-db-1:/tmp/

# Import into the new database
kubectl exec -it tandoor-db-1 -n tandoor -- psql -U tandoor -d tandoor -f /tmp/tandoor_backup.sql
```

**Note:** If your old database used different table names or schemas, you may need to adjust the import. Tandoor uses Django migrations, so the schema should be compatible.

### Step 4: Import Media Files

```bash
# Get the Tandoor pod name
TANDOOR_POD=$(kubectl get pods -n tandoor -l app=tandoor -o jsonpath='{.items[0].metadata.name}')

# Extract and copy media files
tar -xzf tandoor_media.tar.gz
kubectl cp recepies-media/. tandoor/$TANDOOR_POD:/opt/recipes/mediafiles/ -c tandoor
```

### Step 5: Fix Permissions

```bash
kubectl exec -it $TANDOOR_POD -n tandoor -c tandoor -- chown -R nobody:nogroup /opt/recipes/mediafiles
```

### Step 6: Verify Migration

1. Access https://food.newjoy.ro
2. Log in with your existing credentials (or OIDC)
3. Verify recipes and images are present

## Environment Variables

Key environment variables configured:

| Variable | Description |
|----------|-------------|
| `DB_ENGINE` | Database backend (PostgreSQL) |
| `POSTGRES_HOST` | Database hostname |
| `SECRET_KEY` | Django secret key (from Secret) |
| `ENABLE_ALLAUTH` | Enable social authentication |
| `SOCIALACCOUNT_PROVIDERS_FILE` | Path to OIDC config |
| `TZ` | Timezone |

## Storage

- **Media files**: `tandoor-media` PVC (10Gi on longhorn-hdd)
- **Static files**: `tandoor-staticfiles` PVC (1Gi on longhorn-ssd)
- **Database**: Managed by CloudNativePG (5Gi on longhorn-ssd)

## Troubleshooting

### Check pod status

```bash
kubectl get pods -n tandoor
kubectl logs -f deployment/tandoor -n tandoor -c tandoor
kubectl logs -f deployment/tandoor -n tandoor -c nginx
```

### Check database connectivity

```bash
kubectl exec -it deployment/tandoor -n tandoor -c tandoor -- python manage.py dbshell
```

### Run Django migrations manually

```bash
kubectl exec -it deployment/tandoor -n tandoor -c tandoor -- python manage.py migrate
```

### Reset admin password

```bash
kubectl exec -it deployment/tandoor -n tandoor -c tandoor -- python manage.py changepassword admin
```

## OIDC Notes

Tandoor uses django-allauth for social authentication. The OIDC configuration supports:

- OpenID Connect (OIDC) with PKCE
- Multiple identity providers
- Auto-linking accounts by email

When OIDC is configured, users can choose to log in with their identity provider. The first login will create a new account, or you can configure account linking via email.

