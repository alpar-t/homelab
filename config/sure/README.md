# Sure

[Sure](https://github.com/we-promise/sure) is the self-hosted personal finance
application at <https://finance.newjoy.ro>.

## Architecture

- One Pod containing the Rails web process and Sidekiq worker
- A 5Gi `longhorn-ssd` RWO volume shared by both containers for Active Storage
- A two-instance CloudNativePG PostgreSQL cluster
- A persistent single-instance Redis, pending the cluster-wide Redis Operator
  evaluation tracked in `Plan.md`
- Pocket ID OIDC as the required login path
- CNPG continuous WAL archiving and daily base backups to Backblaze B2

The web and worker processes deliberately share one Pod. Sure defaults Active
Storage to local disk and both processes need `/rails/storage`. Longhorn RWX
would normally allow separate Deployments, but the FCOS nodes do not have the
required `nfs-utils` client. Keep the Deployment at one replica unless storage
is moved to S3 or the nodes gain NFS client support.

## Pocket ID

The `sure-oidc-client` ArgoCD Sync hook uses the shared Pocket ID provisioner to
create:

- Client ID: `sure`
- Callback: `https://finance.newjoy.ro/auth/openid_connect/callback`
- Kubernetes Secret: `sure/sure-oidc`

Prerequisites:

- `pocket-id/pocket-id-api-key` exists
- The shared `oidc-provisioner` ServiceAccount, RBAC, and ConfigMap are healthy

Sure is configured as OIDC-first:

- Local login is disabled for ordinary users.
- JIT creation and linking is enabled for verified Pocket ID email addresses.
- A local password remains available only to `super_admin` users as an
  emergency IdP-outage path.

After the first Pocket ID login, promote the owner once:

```bash
kubectl exec -n sure deployment/sure -c web -- \
  bin/rails runner 'User.find_by!(email: "YOUR_EMAIL").update!(role: :super_admin)'
```

## Required backup credentials

Create the namespace-local CNPG B2 credential before the first ArgoCD sync.
CNPG validates the referenced Secret while reconciling the database Cluster:

```bash
kubectl create secret generic cnpg-backup-credentials \
  --namespace=sure \
  --from-literal=ACCESS_KEY_ID="$(kubectl get secret backblaze-backup-credentials -n longhorn-system -o jsonpath='{.data.AWS_ACCESS_KEY_ID}' | base64 -d)" \
  --from-literal=SECRET_ACCESS_KEY="$(kubectl get secret backblaze-backup-credentials -n longhorn-system -o jsonpath='{.data.AWS_SECRET_ACCESS_KEY}' | base64 -d)"
```

The database uses continuous WAL archiving, daily base backups at 03:45, and a
30-day retention policy. The Active Storage PVC is in Longhorn's `critical`
recurring-job group. Redis and CNPG PVCs are excluded from Longhorn backups
because Redis is rebuildable and PostgreSQL has application-aware CNPG backups.

The Longhorn exclusion hook may run before a brand-new Sure PVC has bound when
the root app creates both child apps concurrently. After the first successful
Sure sync, re-sync `longhorn-storage` once and verify the Sure database and
Redis volumes carry the `excluded` recurring-job-group marker.

## Secrets

The `sure-secrets` Sync hook creates the following once and never overwrites
them:

- Rails `SECRET_KEY_BASE`
- Active Record encryption keys and derivation salt
- Redis password and complete `REDIS_URL`

Back up `sure-secrets` and `sure-oidc` outside the cluster. Losing the Rails or
Active Record encryption keys can make encrypted application data unreadable.

## MCP

Sure's built-in `/mcp` endpoint is present in the application, but no static MCP
token is configured and Baloo is not connected during this deployment phase.

## Verification

```bash
kubectl get pods,pvc -n sure
kubectl get cluster.postgresql.cnpg.io,scheduledbackup.postgresql.cnpg.io -n sure
kubectl logs -n sure deployment/sure -c web
kubectl logs -n sure deployment/sure -c worker
curl -I https://finance.newjoy.ro/up
```
