# Immich - Self-Hosted Photo & Video Management

A high-performance, self-hosted alternative to Google Photos with ML-powered features.

## Architecture

```
                              Internet
                                  │
                                  ▼
                          Cloudflare Tunnel
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            nginx-ingress                                     │
│                       photos.newjoy.ro → immich                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
         ┌────────────────────────┴────────────────────────┐
         │                                                  │
         ▼                                                  ▼
┌─────────────────────┐                          ┌─────────────────────┐
│   Immich Server     │◄────── OIDC ───────────► │     Pocket ID       │
│  (API + Web UI)     │                          │   auth.newjoy.ro    │
└─────────────────────┘                          └─────────────────────┘
         │
         ├──────────────────┬──────────────────┬──────────────────┐
         ▼                  ▼                  ▼                  ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  PostgreSQL     │ │     Redis       │ │   Immich ML     │ │     Storage     │
│  (CloudNativePG)│ │  (Job Queue)    │ │  ────────────   │ │  ────────────   │
│  ─────────────  │ │  ────────────   │ │  Face Detect    │ │  Library: 3TB   │
│  HA: 2 replicas │ │  Replicas: 1    │ │  Face Recog     │ │  (HDD, 2 repl)  │
│  SSD: 10Gi      │ │  Memory: 256Mi  │ │  CLIP Search    │ │  Thumbs: 100Gi  │
└─────────────────┘ └─────────────────┘ │  ────────────   │ │  (SSD, 2 repl)  │
                                        │  Memory: 8Gi    │ └─────────────────┘
                                        │  (32GB node)    │
                                        └─────────────────┘
```

## Components

| Component | Purpose | Storage | Replicas |
|-----------|---------|---------|----------|
| Immich Server | API, web UI, background jobs | - | 1 |
| Immich ML | Face/object detection, CLIP search | 10Gi model cache | 1 (32GB node) |
| PostgreSQL | Metadata, albums, users | 10Gi SSD | 2 (HA) |
| Redis | Job queue, caching | - | 1 |

## Storage Layout

| Volume | Size | Class | Replicas | Purpose |
|--------|------|-------|----------|---------|
| library | 3000Gi | HDD | 2 | Original photos/videos, RAW files |
| thumbs | 100Gi | SSD | 2 | Generated thumbnails |
| upload | 50Gi | SSD | 1 | Incoming upload buffer |
| encoded-video | 500Gi | HDD | 1 | Transcoded videos (regenerable) |
| profile | 1Gi | SSD | 2 | User profile pictures |
| backups | 10Gi | SSD | 2 | Database and configuration backups |
| import | 500Gi | HDD | 1 | Bulk import staging area |
| model-cache | 10Gi | SSD | 2 | ML model cache |

## First Time Setup

### 1. Label the ML Node (Optional but Recommended)

Label your 32GB RAM node for ML workloads:

```bash
# Find your node names
kubectl get nodes

# Label the H3 Ultra (32GB) node
kubectl label node <node-name> immich.io/ml-node=true
```

### 2. Create OIDC Client in Pocket ID

1. Go to **https://auth.newjoy.ro** → Admin → OIDC Clients → Create
2. Configure:
   - **Name:** `immich`
   - **Redirect URIs:**
     - `https://photos.newjoy.ro/auth/login`
     - `https://photos.newjoy.ro/user-settings`
     - `app.immich:/` (for mobile app)
3. Copy the **Client ID** and **Client Secret**

### 3. Configure OIDC in Immich Admin UI

In Immich v2.x, OIDC is configured via the web interface:

1. First, create a local admin account at https://photos.newjoy.ro
2. Go to **Administration** → **Settings** → **OAuth Authentication**
3. Enable OAuth and configure:
   - **Issuer URL:** `https://auth.newjoy.ro`
   - **Client ID:** (from Pocket ID)
   - **Client Secret:** (from Pocket ID)
   - **Scope:** `openid profile email`
   - **Button Text:** `Login with Pocket ID`
   - **Auto Register:** Enable
   - **Mobile Redirect URI Override:** `app.immich:/`
4. Save settings

### 4. Add DNS to Cloudflare Tunnel

Add `photos.newjoy.ro` to your Cloudflare tunnel configuration.

### 5. Access Immich

- **URL:** https://photos.newjoy.ro
- **First user:** Click "Login with Pocket ID" - first user becomes admin

## Mobile App Setup

1. Download the Immich app from [App Store](https://apps.apple.com/app/immich/id1613945652) or [Play Store](https://play.google.com/store/apps/details?id=app.alextran.immich)
2. Server URL: `https://photos.newjoy.ro`
3. Login with Pocket ID
4. Enable automatic backup in app settings

## Importing Existing Photos

### Method 1: Bulk Import via kubectl (Recommended for Large Collections)

```bash
# Step 1: Copy photos to the import volume
# (Run from a machine with your photos)
kubectl cp ~/Photos/vacation-2023 immich/immich-server-xxx:/import/vacation-2023

# Or use rsync for better progress (requires kubectl exec)
kubectl exec -n immich deploy/immich-server -- mkdir -p /import/my-photos
# Then rsync via a port-forward or direct access

# Step 2: Use the Immich web UI to create an External Library
# Go to: Administration → External Libraries → Create Library
# Import Path: /import
# This will scan and import all photos

# Step 3: After import, optionally clean up the import folder
kubectl exec -n immich deploy/immich-server -- rm -rf /import/*
```

### Method 2: Immich CLI (From Your Local Machine)

```bash
# Install the CLI
npm install -g @immich/cli

# Login (creates API key)
immich login https://photos.newjoy.ro

# Upload recursively
immich upload --recursive ~/Photos
```

### Method 3: Web Upload

Use the web interface to drag-and-drop photos. Good for small batches.

## ML Processing

After import, Immich will queue photos for ML processing:
- **Face detection & recognition:** Groups photos by person
- **CLIP embeddings:** Enables smart search ("photos of dogs at the beach")
- **Object detection:** Tags objects in photos

For a 2TB library, expect ML processing to take several days. The app remains usable during processing.

Monitor progress:
```bash
# Check ML queue
kubectl logs -n immich -l app=immich-server --tail=100 | grep -i "job\|queue"

# Check ML service
kubectl logs -n immich -l app=immich-ml --tail=50
```

## Maintenance

### Check Status

```bash
# All pods
kubectl get pods -n immich

# Server logs
kubectl logs -n immich -l app=immich-server --tail=100

# ML logs
kubectl logs -n immich -l app=immich-ml --tail=100

# Database status
kubectl get cluster immich-db -n immich
```

### Storage Usage

```bash
# Check PVC usage
kubectl exec -n immich deploy/immich-server -- df -h

# Library size
kubectl exec -n immich deploy/immich-server -- du -sh /usr/src/app/upload/library
```

### Backup

Critical data to backup:
1. **PostgreSQL database** - Contains all metadata, albums, faces, etc.
2. **Library volume** - Your actual photos (irreplaceable!)

```bash
# Database backup (via CloudNativePG)
kubectl cnpg backup immich-db -n immich

# Or manual pg_dump
kubectl exec -n immich immich-db-1 -- pg_dump -U immich immich > immich-backup.sql
```

For library backup, use Longhorn snapshots + off-site backup (see main backup documentation).

## Troubleshooting

### OIDC Login Not Working

```bash
# Check OIDC secret is set correctly
kubectl get secret immich-oidc -n immich -o jsonpath='{.data.client_id}' | base64 -d

# Check server logs for OIDC errors
kubectl logs -n immich -l app=immich-server | grep -i oauth
```

### ML Service Crashing (OOM)

```bash
# Check memory usage
kubectl top pod -n immich -l app=immich-ml

# If needed, reduce workers or increase limits in ml.yaml
```

### Upload Failures

```bash
# Check ingress allows large uploads
kubectl describe ingress immich -n immich | grep body-size

# Check upload volume has space
kubectl exec -n immich deploy/immich-server -- df -h /usr/src/app/upload/upload
```

### Database Connection Issues

```bash
# Check PostgreSQL cluster status
kubectl get cluster immich-db -n immich

# Check credentials
kubectl get secret immich-db-app -n immich -o jsonpath='{.data.password}' | base64 -d
```

## Configuration

In Immich v2.x, most settings are configured via the **Admin UI** rather than environment variables:

- **OAuth/OIDC:** Administration → Settings → OAuth Authentication
- **Machine Learning:** Administration → Settings → Machine Learning
- **Storage Templates:** Administration → Settings → Storage Template
- **Transcoding:** Administration → Settings → Video Transcoding

Environment variables in `deployment.yaml` are primarily for:

| Variable | Value | Description |
|----------|-------|-------------|
| `DB_HOSTNAME` | immich-db-rw... | PostgreSQL service |
| `REDIS_HOSTNAME` | redis... | Redis service |
| `IMMICH_MACHINE_LEARNING_URL` | http://immich-ml... | ML service URL |
| `LOG_LEVEL` | log | Logging verbosity |

See [Immich Environment Variables](https://immich.app/docs/install/environment-variables) for full list.

## Upgrading

Immich releases frequently. To upgrade:

1. Check [release notes](https://github.com/immich-app/immich/releases)
2. Update image tags in `deployment.yaml` and `ml.yaml`
3. Sync via ArgoCD

```bash
# Check current version
kubectl get deploy -n immich -o jsonpath='{.items[*].spec.template.spec.containers[0].image}'

# After updating manifests, ArgoCD will sync automatically
# Or force sync:
argocd app sync immich
```

