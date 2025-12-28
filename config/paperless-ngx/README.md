# Paperless-ngx

A document management system with OCR, automatic tagging, and full-text search.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Namespace: paperless-ngx                                                    │
│                                                                             │
│  ┌─────────────────┐    ┌─────────────────────────────────────────────┐    │
│  │ Scanner         │    │ Pod: paperless-ngx                          │    │
│  │ (Brother etc)   │    │  ┌───────────────┐  ┌───────────────────┐   │    │
│  └────────┬────────┘    │  │ ftp-server    │  │ paperless-ngx     │   │    │
│           │             │  │ :21 (MetalLB) │  │ :8000             │   │    │
│           │             │  │ 192.168.1.201 │  │                   │   │    │
│           └────────────▶│  └───────┬───────┘  └─────────┬─────────┘   │    │
│                         │          │   shared volume    │             │    │
│                         │          └────────┬───────────┘             │    │
│                         │                   ▼                         │    │
│                         │          ┌─────────────────┐                │    │
│                         │          │ consume PVC     │                │    │
│                         │          │ (scanner files) │                │    │
│                         │          └─────────────────┘                │    │
│                         └─────────────────────────────────────────────┘    │
│                                             │                              │
│         ┌───────────────────────────────────┼───────┐                     │
│         │                     │             │       │                     │
│         ▼                     ▼             ▼       ▼                     │
│  ┌─────────────┐     ┌─────────────┐  ┌──────────┐  ┌──────────┐         │
│  │ PostgreSQL  │     │ Redis       │  │ Gotenberg│  │ Tika     │         │
│  │ (CNPG)      │     │ :6379       │  │ :3000    │  │ :9998    │         │
│  └─────────────┘     └─────────────┘  └──────────┘  └──────────┘         │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

The FTP server runs as a sidecar container in the same pod as Paperless-ngx.
This allows both containers to share the same consume volume (RWO PVC) without
needing ReadWriteMany storage.

## Components

| Component | Purpose | Image |
|-----------|---------|-------|
| paperless-ngx | Main application | ghcr.io/paperless-ngx/paperless-ngx:latest |
| ftp-server (sidecar) | Scanner uploads | stilliard/pure-ftpd:latest |
| PostgreSQL | Database (via CloudNativePG) | ghcr.io/cloudnative-pg/postgresql:16 |
| Redis | Task queue / message broker | redis:7-alpine |
| Gotenberg | Document conversion (Office → PDF) | gotenberg/gotenberg:8 |
| Tika | Text extraction | apache/tika:latest |

## Initial Setup

### 1. Create OIDC Secret (Required)

Before deploying, create an OIDC application in Pocket ID:
1. Go to https://auth.newjoy.ro
2. Create a new application for Paperless
3. Set redirect URI: `https://docs.newjoy.ro/accounts/oidc/pocket-id/login/callback/`
4. Note the client ID and secret

Then create the secrets:

```bash
kubectl create namespace paperless-ngx

# OIDC configuration
kubectl create secret generic paperless-oidc -n paperless-ngx \
  --from-literal=providers='{
    "openid_connect": {
      "OAUTH_PKCE_ENABLED": true,
      "APPS": [{
        "provider_id": "pocket-id",
        "name": "Pocket ID",
        "client_id": "YOUR_CLIENT_ID",
        "secret": "YOUR_CLIENT_SECRET",
        "settings": {
          "server_url": "https://auth.newjoy.ro/.well-known/openid-configuration"
        }
      }]
    }
  }'

# Email from address
kubectl create secret generic paperless-email -n paperless-ngx \
  --from-literal=from_address="service@newjoy.ro"
```

Replace `YOUR_CLIENT_ID` and `YOUR_CLIENT_SECRET` with your actual values.

### 2. Deploy the Application

```bash
kubectl apply -f apps/paperless-ngx.yaml
```

ArgoCD will automatically:
1. Create PVCs, RBAC, Redis, Gotenberg, Tika, PostgreSQL (sync-wave 0)
2. Run secrets generator, deploy FTP server (sync-wave 1)
3. Deploy Paperless-ngx (sync-wave 2)



### 4. Get the FTP Password

The FTP password is auto-generated. Retrieve it for scanner configuration:

```bash
kubectl get secret ftp-credentials -n paperless-ngx -o jsonpath='{.data.password}' | base64 -d
```

### 5. Configure Your Scanner

Configure your scanner to upload via FTP:
- **Host**: `192.168.1.201` (MetalLB LoadBalancer IP)
- **Username**: `scanner`
- **Password**: (from step 4)
- **Directory**: `/paperless/` (files here are consumed by Paperless)

## Data Migration from MariaDB

Paperless's built-in `document_exporter` creates database-agnostic JSON files, so no SQL 
conversion is needed. The `document_importer` reads these and populates PostgreSQL directly.

### Overview

1. Export from old system (JSON + media files)
2. Deploy Kubernetes
3. Import data using `document_importer`
4. Copy media files

### Step 1: Export from Old System

On your Docker Compose host:

```bash
# Export using Paperless's built-in exporter
# This creates JSON metadata + copies all document files
docker exec paperless_ngx document_exporter /usr/src/paperless/export

# Create tarball of the export
cd /srv/paperless
tar -czvf paperless-export.tar.gz export/
```

Copy to your local machine:

```bash
scp your-server:/srv/paperless/paperless-export.tar.gz ./
```

### Step 2: Deploy Kubernetes

Follow Initial Setup steps 1-2:
1. Create the secrets (OIDC + email)
2. Deploy via ArgoCD

Wait for all pods to be ready:

```bash
kubectl get pods -n paperless-ngx -w
```

### Step 3: Import Data

```bash
# Get the Paperless pod name
PAPERLESS_POD=$(kubectl get pods -n paperless-ngx -l app=paperless-ngx -o jsonpath='{.items[0].metadata.name}')

# Copy export tarball to pod
kubectl cp paperless-export.tar.gz paperless-ngx/$PAPERLESS_POD:/tmp/ -c paperless-ngx

# Extract and import (includes both metadata and document files)
kubectl exec -it $PAPERLESS_POD -n paperless-ngx -c paperless-ngx -- bash -c '
  cd /tmp
  tar -xzvf paperless-export.tar.gz
  document_importer /tmp/export
  rm -rf /tmp/export /tmp/paperless-export.tar.gz
'
```

The importer reads the JSON metadata and copies all document files (originals + archived 
versions) into the media directory. It also rebuilds the search index automatically.

### Step 4: Verify and Continue Setup

1. Access https://docs.newjoy.ro and log in via OIDC (your old user is imported)
2. Verify documents are present and viewable
3. Continue with Initial Setup step 4 (FTP password, scanner config)

## Storage

All volumes use SSD storage for performance (your dataset is ~2.4GB):

| PVC | Size | Purpose |
|-----|------|---------|
| paperless-media | 10Gi | Original and archived documents |
| paperless-export | 5Gi | Document exports |
| paperless-consume | 2Gi | Scanner upload directory |

Note: No separate "data" PVC is needed since we use PostgreSQL. The data directory
was primarily for SQLite; with an external database, it only contains ephemeral
files like the search index which can be regenerated.

## Network

| Service | Type | Port | Purpose |
|---------|------|------|---------|
| paperless-ngx | ClusterIP | 8000 | Web interface |
| ftp-server | LoadBalancer | 21, 30000-30009 | Scanner FTP uploads |
| redis | ClusterIP | 6379 | Task queue |
| gotenberg | ClusterIP | 3000 | Document conversion |
| tika | ClusterIP | 9998 | Text extraction |

FTP server has a fixed IP (`192.168.1.201`) via MetalLB for scanner configuration stability.

## OCR Configuration

Configured for multilingual OCR:
- **Languages installed**: Romanian (ron), Hungarian (hun)
- **Default OCR**: English + Romanian + Hungarian
- **OCR Mode**: `redo` - re-OCR documents even if they have text layers

## Troubleshooting

### Check pod status

```bash
kubectl get pods -n paperless-ngx
kubectl logs -f deployment/paperless-ngx -n paperless-ngx
```

### Check database connectivity

```bash
kubectl exec -it deployment/paperless-ngx -n paperless-ngx -- python manage.py dbshell
```

### Check FTP server logs

```bash
kubectl logs -f deployment/ftp-server -n paperless-ngx
```

### Test FTP connection

```bash
# From any machine on your LAN
ftp 192.168.1.201
# Login with: scanner / <password from secret>
```

### Re-index all documents

```bash
kubectl exec -it deployment/paperless-ngx -n paperless-ngx -- document_index reindex
```

### Reset admin password

```bash
kubectl exec -it deployment/paperless-ngx -n paperless-ngx -- python manage.py changepassword admin
```

### Check consume directory

```bash
kubectl exec -it deployment/paperless-ngx -n paperless-ngx -- ls -la /usr/src/paperless/consume/paperless/
```

## Environment Variables

Key environment variables configured:

| Variable | Value | Description |
|----------|-------|-------------|
| PAPERLESS_DBENGINE | postgresql | Database backend |
| PAPERLESS_OCR_LANGUAGE | eng+ron+hun | OCR languages |
| PAPERLESS_TIKA_ENABLED | 1 | Enable Tika for text extraction |
| PAPERLESS_URL | https://docs.newjoy.ro | Public URL |
| PAPERLESS_TIME_ZONE | Europe/Bucharest | Timezone |

