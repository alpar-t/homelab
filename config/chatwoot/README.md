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
│               oauth2-proxy-chatwoot                         │
│           (authenticates via Pocket ID)                     │
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
│  (Longhorn)   │ │           chatwoot-db (local-ssd)         │
│               │ │           2 HA instances                  │
└───────────────┘ │           + B2 backups                    │
                  └───────────────────────────────────────────┘
```

## Components

| Component | Storage | Notes |
|-----------|---------|-------|
| PostgreSQL | `local-ssd` | HA with CNPG, WAL backup to B2 |
| Redis | `longhorn-ssd` | Persistent for job queue |
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

### 2. OAuth2 Proxy Secret

Register Chatwoot in Pocket ID first, then:

```bash
kubectl create secret generic oauth2-proxy-chatwoot \
  --namespace=chatwoot \
  --from-literal=client-id=<pocket-id-client-id> \
  --from-literal=client-secret=<pocket-id-client-secret> \
  --from-literal=cookie-secret=$(openssl rand -hex 16)
```

### 3. Chatwoot Config Secret

Simple config secret for non-sensitive settings:

```bash
kubectl create secret generic chatwoot-config \
  --namespace=chatwoot \
  --from-literal=MAILER_SENDER_EMAIL="..."
```

### Auto-Generated Secrets (no action needed)

These are created automatically and referenced directly by the Helm chart:

| Secret | Created By | Contains |
|--------|-----------|----------|
| `chatwoot-db-app` | CloudNativePG | `uri` (DATABASE_URL), auto-rotates |
| `chatwoot-secrets` | secrets-job | `SECRET_KEY_BASE` |

## Deployment Order

1. **chatwoot-infra** syncs first:
   - Creates namespace
   - Deploys PostgreSQL cluster (waits for ready)
   - Deploys Redis
   - Runs secrets generation job
   - Creates storage PVC

2. **Create manual secrets** (see Prerequisites above)

3. **chatwoot** (Helm chart) syncs:
   - Deploys web and worker pods
   - Uses external PostgreSQL and Redis

4. **oauth2-proxy-chatwoot** syncs:
   - Deploys OAuth2 proxy
   - Ingress routes traffic through proxy

## SMTP Configuration

Chatwoot uses Stalwart as local SMTP relay:

- Host: `stalwart.stalwart-mail.svc.cluster.local`
- Port: `25`
- Authentication: None (trusted internal network)
- Sender: Set via `MAILER_SENDER_EMAIL` in chatwoot-config secret

## Initial Setup

After deployment, create the first admin account:

```bash
# Exec into the web pod
kubectl exec -it -n chatwoot deploy/chatwoot-web -- /bin/bash

# Create super admin
RAILS_ENV=production bundle exec rails chatwoot:setup
```

Or via Rails console:

```bash
kubectl exec -it -n chatwoot deploy/chatwoot-web -- \
  bundle exec rails runner "
    SuperAdmin.create!(
      email: 'your-email@example.com',
      password: 'your-secure-password',
      password_confirmation: 'your-secure-password',
      name: 'Admin'
    )
  "
```

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
kubectl logs -n chatwoot -l app.kubernetes.io/name=chatwoot -c chatwoot --tail=100 -f

# Worker pod
kubectl logs -n chatwoot -l app.kubernetes.io/component=worker --tail=100 -f
```

### Check job queue

```bash
kubectl exec -it -n chatwoot deploy/chatwoot-web -- \
  bundle exec rails runner "puts Sidekiq::Stats.new.inspect"
```

## Related

- [oauth2-proxy-chatwoot](../oauth2-proxy-chatwoot/) - Authentication proxy
- [local-path-provisioner](../local-path-provisioner/) - Local SSD storage for PostgreSQL
- [runbooks/migrate-postgres-to-local-storage.md](../../runbooks/migrate-postgres-to-local-storage.md) - PostgreSQL local storage setup

