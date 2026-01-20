# Chatwoot

Customer engagement platform deployed at `chat.newjoy.ro`.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Ingress (nginx)                         │
│                   chat.newjoy.ro                            │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              Chatwoot (Helm Chart)                          │
│                                                             │
│  ┌──────────┐  ┌──────────┐                                 │
│  │   Web    │  │  Worker  │                                 │
│  └────┬─────┘  └────┬─────┘                                 │
└───────┼─────────────┼───────────────────────────────────────┘
        │             │
        ▼             ▼
┌───────────────┐ ┌───────────────────────────────────────────┐
│     Redis     │ │        PostgreSQL (CloudNativePG)         │
│  (chart's)    │ │           chatwoot-db (local-path)        │
│               │ │           2 HA instances                  │
└───────────────┘ │           + B2 backups                    │
                  └───────────────────────────────────────────┘
```

## Components

| Component | Storage | Notes |
|-----------|---------|-------|
| PostgreSQL | `local-path` | HA with CNPG, WAL backup to B2 |
| Redis | `longhorn` | Chart's built-in Redis |
| File Storage | `longhorn-ssd` | User uploads, attachments |

## Prerequisites

### 1. CNPG Backup Credentials

Required for PostgreSQL backups to Backblaze B2:

```bash
# Copy from existing namespace (e.g., immich)
kubectl get secret cnpg-backup-credentials -n immich -o yaml | \
  sed 's/namespace: immich/namespace: chatwoot/' | \
  kubectl apply -f -
```

### 2. Chatwoot Environment Secret

**Wait for these to exist first:**
- `chatwoot-secrets` (created by the secrets-job)
- `chatwoot-db-app` (created by CloudNativePG)

Then create the aggregated environment secret:

```bash
kubectl create secret generic chatwoot-env \
  --namespace=chatwoot \
  --from-literal=SECRET_KEY_BASE="$(kubectl get secret chatwoot-secrets -n chatwoot -o jsonpath='{.data.SECRET_KEY_BASE}' | base64 -d)" \
  --from-literal=DATABASE_URL="$(kubectl get secret chatwoot-db-app -n chatwoot -o jsonpath='{.data.uri}' | base64 -d)" \
  --from-literal=MAILER_SENDER_EMAIL="service@newjoy.ro"
```

> **Note:** The Chatwoot Helm chart only supports a single `extraEnvVarsSecret`, so we aggregate
> values into one secret. If CNPG rotates database credentials, re-run the command above
> (delete the old secret first with `kubectl delete secret chatwoot-env -n chatwoot`).

## Deployment Order

1. **chatwoot-infra** syncs first:
   - Creates namespace
   - Deploys PostgreSQL cluster (waits for ready)
   - Runs secrets generation job
   - Creates storage PVC
   - Creates ingress

2. **Create manual secrets** (see Prerequisites above)

3. **chatwoot** (Helm chart) syncs:
   - Deploys web and worker pods
   - Deploys Redis (chart's built-in)
   - Runs database migrations

## Initial Setup

1. After deployment, go to `https://chat.newjoy.ro`
2. Create your admin account (signup is enabled)
3. **Important:** After creating admin, disable signup:
   - Edit `config/chatwoot/helm/values.yaml`
   - Set `ENABLE_ACCOUNT_SIGNUP: "false"`
   - Commit and sync

## SMTP Configuration

Chatwoot uses Stalwart as local SMTP relay:

- Host: `stalwart.stalwart-mail.svc.cluster.local`
- Port: `25`
- Authentication: None (trusted internal network)
- Sender: Set via `MAILER_SENDER_EMAIL` in chatwoot-env secret

## Mobile App

The Chatwoot mobile app works with native email/password authentication.
Use the same credentials you created during initial setup.

## Troubleshooting

### Check PostgreSQL connection

```bash
kubectl exec -it -n chatwoot deploy/chatwoot-web -- \
  bundle exec rails runner "puts ActiveRecord::Base.connection.execute('SELECT 1').first"
```

### Check Redis connection

```bash
kubectl exec -it -n chatwoot deploy/chatwoot-web -- \
  bundle exec rails runner "puts Redis.new(url: ENV['REDIS_URL']).ping"
```

### View logs

```bash
# Web pod
kubectl logs -n chatwoot deploy/chatwoot-web --tail=100 -f

# Worker pod  
kubectl logs -n chatwoot deploy/chatwoot-worker --tail=100 -f
```

### Check job queue

```bash
kubectl exec -it -n chatwoot deploy/chatwoot-web -- \
  bundle exec rails runner "puts Sidekiq::Stats.new.inspect"
```

## Related

- [CloudNativePG](../cloudnativepg/) - PostgreSQL operator
- [Stalwart Mail](../stalwart-mail/) - SMTP relay
