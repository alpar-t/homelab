# Cloud & Container Image Reference

This document tracks pinned container images and security practices for the cluster.

---

## Security: Never Commit Secrets

> **⚠️ Secrets must NEVER be stored in this repository.**

All credentials, API keys, and sensitive configuration must be created directly in the cluster using `kubectl create secret`. This includes:

- Database passwords
- SMTP credentials (Mailgun)
- API tokens
- TLS certificates (if not using cert-manager)
- OAuth client secrets

### Creating Secrets

Always create secrets imperatively:

```bash
kubectl create secret generic <secret-name> \
  --namespace <namespace> \
  --from-literal=key='value'
```

## Container Images

Always use specific versions with digests to ensure reproducible deployments.

### Why Pin Images?

- **Reproducibility**: Same image deployed every time
- **Security**: Digest guarantees image hasn't been tampered with  
- **Stability**: No surprise breakages from upstream changes
- **Auditability**: Clear record of what's running

---



## How to Update an Image

### 1. Find the New Version

Check Docker Hub or the project's releases page for new versions.

### 2. Get the Digest

```bash
# Pull the new version
docker pull boky/postfix:v4.5.0

# Get the digest
docker inspect --format='{{index .RepoDigests 0}}' boky/postfix:v4.5.0
# Output: boky/postfix@sha256:abc123...
```

Or query Docker Hub directly:

```bash
curl -s "https://hub.docker.com/v2/repositories/boky/postfix/tags/v4.5.0" | \
  python3 -c "import json,sys; print(json.load(sys.stdin).get('digest'))"
```

### 3. Update the Deployment

Edit the deployment file with the new version and digest:

```yaml
image: boky/postfix:v4.5.0@sha256:abc123...
``

### 5. Commit and Deploy

```bash
git add .
git commit -m "chore: update boky/postfix to v4.5.0"
git push
```

ArgoCD will automatically sync the new image.

---

## Checking Running Images

Verify what's actually running in the cluster:

```bash
# Check image for a specific deployment
kubectl get deployment -n stalwart-mail stalwart -o jsonpath='{.spec.template.spec.containers[0].image}'

# Check all images in a namespace
kubectl get pods -n stalwart-mail -o jsonpath='{range .items[*]}{.spec.containers[*].image}{"\n"}{end}'
```

---

The manifest digest (`sha256:f3f...`) automatically selects the correct architecture.

---

## Local Storage with k3s Local-Path Provisioner

k3s includes a built-in local-path-provisioner for local storage. We create a `local-ssd` StorageClass that uses this provisioner.

### Why Use Local Storage?

For applications that handle their own replication (like CloudNativePG PostgreSQL):
- **No double replication** - app manages HA, don't need Longhorn's replication too
- **Better performance** - no network overhead for storage I/O
- **Simpler** - fewer failure modes

### PostgreSQL Always Uses `local-ssd`

**Rule: All CloudNativePG PostgreSQL clusters MUST use `local-ssd`, never Longhorn.**

CloudNativePG provides:
- **Replication**: 2+ instances with streaming replication
- **Backups**: Continuous WAL archiving + daily base backups to B2
- **PITR**: Point-in-time recovery to any second within retention

Using Longhorn would add:
- ❌ Redundant replication (double the storage, no benefit)
- ❌ Network latency on every database I/O
- ❌ Additional failure modes

```yaml
# Correct - PostgreSQL with local-ssd
spec:
  storage:
    storageClass: local-ssd

# Wrong - don't use Longhorn for PostgreSQL
spec:
  storage:
    storageClass: longhorn-ssd  # ❌ Never do this
```

### StorageClasses

| StorageClass | Provisioner | Use Case |
|--------------|-------------|----------|
| `local-path` | k3s built-in | Default k3s local storage |
| `local-ssd` | k3s built-in | Alias for databases (PostgreSQL, Redis) |
| `longhorn-ssd` | Longhorn | Replicated SSD storage |
| `longhorn-hdd` | Longhorn | Replicated HDD storage (large files) |

### Storage Path

k3s stores local volumes at: `/var/lib/rancher/k3s/storage`

### Usage

```yaml
spec:
  storage:
    size: 5Gi
    storageClass: local-ssd
```

### Setup

The `local-ssd` StorageClass is deployed via ArgoCD:
- App: `apps/local-path-provisioner.yaml`
- Manifest: `config/local-path-provisioner/manifests/storageclass-local-ssd.yaml`

No additional node configuration required - k3s handles everything.

