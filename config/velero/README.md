# Velero - Kubernetes Resource Backup

Velero backs up Kubernetes resources (Secrets, CRDs, ConfigMaps) to Backblaze B2.

## What Gets Backed Up

| Category | Examples | Why Not in Git |
|----------|----------|----------------|
| **Secrets** | oauth2-proxy credentials, OIDC clients, DB passwords | Security - never committed |
| **CRDs** | Longhorn Volumes, CNPG Clusters, RecurringJobs | Created by operators/users |
| **Operator State** | CNPG-generated secrets, Longhorn settings | Auto-generated at runtime |

## What Does NOT Get Backed Up

| Category | Why | Backed Up By |
|----------|-----|--------------|
| PVC data | Too large, inefficient | Longhorn → B2 |
| PostgreSQL data | Need point-in-time recovery | CNPG WAL → B2 |
| Deployments/Services | Declarative in Git | ArgoCD |

## Backup Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Backup Strategy                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Secrets, CRDs ──────► Velero ──────► B2 (velero-backup)   │
│                        Daily 4 AM    30 day retention       │
│                                                             │
│  Volume Data ────────► Longhorn ────► B2 (longhorn-backup) │
│                        Daily 2 AM    21 day retention       │
│                                                             │
│  PostgreSQL ─────────► CNPG ────────► B2 (cnpg/)           │
│                        Continuous    30 day retention       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Prerequisites

### 1. Create B2 Bucket

Create a new bucket in Backblaze B2 for Velero backups:
- Bucket name: `homelab-velero-backup`
- Region: `eu-central-003` (same as Longhorn)
- Privacy: Private

You can reuse the same application key as Longhorn, or create a dedicated one.

### 2. Create the Secret

Copy credentials from the existing Longhorn backup secret:

```bash
# Create namespace first
kubectl create namespace velero

# Extract B2 credentials from Longhorn and create Velero secret
kubectl get secret backblaze-backup-credentials -n longhorn-system -o json | \
  jq -r '.data.AWS_ACCESS_KEY_ID | @base64d' | \
  xargs -I{} sh -c 'KEY_ID="{}"; \
    kubectl get secret backblaze-backup-credentials -n longhorn-system -o json | \
    jq -r ".data.AWS_SECRET_ACCESS_KEY | @base64d" | \
    xargs -I@ kubectl create secret generic velero-b2-credentials \
      --namespace velero \
      --from-literal=cloud="[default]
aws_access_key_id=$KEY_ID
aws_secret_access_key=@"'
```

Or use this simpler one-liner:

```bash
kubectl create namespace velero

kubectl create secret generic velero-b2-credentials \
  --namespace velero \
  --from-literal=cloud="[default]
aws_access_key_id=$(kubectl get secret backblaze-backup-credentials -n longhorn-system -o jsonpath='{.data.AWS_ACCESS_KEY_ID}' | base64 -d)
aws_secret_access_key=$(kubectl get secret backblaze-backup-credentials -n longhorn-system -o jsonpath='{.data.AWS_SECRET_ACCESS_KEY}' | base64 -d)"
```

### 3. Verify Secret

```bash
kubectl get secret velero-b2-credentials -n velero -o jsonpath='{.data.cloud}' | base64 -d
```

Should output:
```
[default]
aws_access_key_id=00xxxxxxxxxxxxx
aws_secret_access_key=Kxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

## Deployment

Velero is deployed via ArgoCD from `apps/velero.yaml`.

After ArgoCD syncs:

```bash
# Check Velero is running
kubectl get pods -n velero

# Check backup location is valid
velero backup-location get

# View scheduled backups
velero schedule get
```

## Manual Backup

Trigger a backup immediately:

```bash
# Backup everything (except volumes)
velero backup create manual-backup-$(date +%Y%m%d-%H%M)

# Backup specific namespace
velero backup create pocket-id-backup --include-namespaces pocket-id
```

## Restore

### List Available Backups

```bash
velero backup get
```

### Restore Specific Secret

```bash
velero restore create --from-backup daily-resources-20241231040000 \
  --include-namespaces stalwart-mail \
  --include-resources secrets
```

### Restore Entire Namespace

```bash
velero restore create --from-backup daily-resources-20241231040000 \
  --include-namespaces pocket-id
```

### Full Cluster Restore

After fresh k3s install:

```bash
# 1. Install Velero CLI
brew install velero

# 2. Create namespace and secret (manually - bootstrap problem)
kubectl create namespace velero
kubectl create secret generic velero-b2-credentials --namespace velero \
  --from-literal=cloud="[default]
aws_access_key_id=<your-key>
aws_secret_access_key=<your-secret>"

# 3. Install Velero (one-time bootstrap)
velero install \
  --provider aws \
  --plugins velero/velero-plugin-for-aws:v1.10.1 \
  --bucket homelab-velero-backup \
  --secret-file <(kubectl get secret velero-b2-credentials -n velero -o jsonpath='{.data.cloud}' | base64 -d) \
  --backup-location-config region=eu-central-003,s3ForcePathStyle=true,s3Url=https://s3.eu-central-003.backblazeb2.com \
  --use-volume-snapshots=false

# 4. List backups from B2
velero backup get

# 5. Restore everything
velero restore create --from-backup <latest-backup>

# 6. Let ArgoCD take over from Git
kubectl apply -f root-application.yaml
```

## Troubleshooting

### Backup Location Shows "Unavailable"

```bash
# Check Velero logs
kubectl logs -n velero deployment/velero

# Common issues:
# - Wrong bucket name
# - Invalid credentials
# - Region mismatch
```

### Backup Failed

```bash
# Describe the backup
velero backup describe <backup-name> --details

# Check for partial failures
velero backup logs <backup-name>
```

### Secret Format Issues

Velero expects AWS credentials file format, not individual keys:

```
# CORRECT
[default]
aws_access_key_id=xxx
aws_secret_access_key=xxx

# WRONG (Longhorn format)
AWS_ACCESS_KEY_ID=xxx
AWS_SECRET_ACCESS_KEY=xxx
```

## What's Protected

After setup, these critical resources are backed up daily:

| Namespace | Secrets | CRDs |
|-----------|---------|------|
| `longhorn-system` | `backblaze-backup-credentials` | BackupTarget, RecurringJob |
| `pocket-id` | `cnpg-backup-credentials`, `pocket-id-*` | CNPG Cluster |
| `homeassistant` | `cnpg-backup-credentials` | CNPG Cluster, ScheduledBackup |
| `stalwart-mail` | 5 secrets (OIDC, Migadu, etc.) | - |
| `pihole` | `oauth2-proxy-pihole` | - |
| `omada-controller` | `oauth2-proxy-omada` | - |
| `kube-system` | - | MetalLB IPAddressPool |

## Cost

Velero backups are tiny (just YAML):
- ~50-100 MB per backup (compressed)
- 30 backups × 100 MB = 3 GB
- **~$0.02/month** on B2

