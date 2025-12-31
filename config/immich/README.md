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
│  ─────────────  │ │  ────────────   │ │  Face Detect    │ │  Library: 8     │
│  HA: 2 replicas │ │  Replicas: 1    │ │  Face Recog     │ │  buckets (HDD)  │
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

### Library Bucket Architecture

Instead of a single large library volume, we use multiple fixed-size 500Gi "bucket" PVCs.
This allows each bucket to fit on any node (all nodes have >500Gi available) while
providing 2-replica redundancy across different nodes.

| Bucket PVC | Size |
|------------|------|
| `immich-library-01` | 500Gi |
| `immich-library-02` | 500Gi |
| `immich-library-03` | 500Gi |
| `immich-library-04` | 500Gi |
| `immich-library-05` | 500Gi |
| `immich-library-06` | 500Gi |

**Total: 3TB** (easily expandable by adding more buckets)

**How it works:**
- A **mergerfs sidecar** combines all buckets into a unified view at `/usr/src/app/upload/library`
- Uses the `lfs` (least free space) policy: fills buckets one-by-one
- When bucket-01 fills up, new files go to bucket-02, and so on
- Immich sees a single directory, unaware of the underlying bucket structure

**Benefits:**
- **True node redundancy:** Each 500Gi bucket fits on any node (pamacs has 2.7TB)
- **Incremental recovery:** Lose one bucket = lose 500GB, not your entire 3TB library
- **Simple scaling:** Just add more `immich-library-XX` PVCs when needed
- **Balanced disk usage:** Data spreads across all HDDs in the cluster

### Other Storage Volumes

| Volume | Size | Class | Replicas | Purpose |
|--------|------|-------|----------|---------|
| thumbs | 100Gi | SSD | 2 | Generated thumbnails |
| upload | 50Gi | SSD | 1 | Incoming upload buffer |
| encoded-video | 500Gi | HDD | 1 | Transcoded videos (regenerable) |
| profile | 1Gi | SSD | 2 | User profile pictures |
| backups | 10Gi | SSD | 2 | Database and configuration backups |
| import | 500Gi | HDD | 1 | Bulk import staging area |
| model-cache | 10Gi | SSD | 2 | ML model cache |

## Adding More Storage Buckets

When you need more storage, add a new 500Gi bucket:

1. Add a new PVC in `pvc.yaml`:
   ```yaml
   ---
   apiVersion: v1
   kind: PersistentVolumeClaim
   metadata:
     name: immich-library-07
     namespace: immich
     labels:
       app: immich
       immich-library-bucket: "07"
   spec:
     accessModes:
       - ReadWriteOnce
     storageClassName: longhorn-hdd
     resources:
       requests:
         storage: 500Gi
   ```

2. Update `deployment.yaml` to add the new bucket to:
   - The mergerfs sidecar's command (add `:/mnt/library-buckets/07`)
   - The mergerfs sidecar's volumeMounts
   - The init-bucket-markers volumeMounts
   - The volumes section

3. Sync via ArgoCD - Immich will restart and the new bucket will be available

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

### Method 1: Bulk Import via kubectl (Recommended for Photoprism Migration)

Use the import volume to stage large photo collections:

```bash
# Copy photos to the import volume (from local machine or Photoprism export)
kubectl cp ~/Photos immich/immich-server-xxx:/import/

# Or use rsync for large transfers with progress
kubectl exec -n immich deploy/immich-server -- mkdir -p /import/photos
rsync -avP ~/Photos/ user@node:/path/to/import/

# Create an External Library in Immich:
# Go to: Administration → External Libraries → Create Library
# Import Path: /import
# Immich will scan and import all photos

# After import completes, clean up the staging area
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

#### Database Backups (Automated to Backblaze B2)

The PostgreSQL database is automatically backed up to Backblaze B2:
- **Continuous WAL archiving** - Point-in-time recovery capability
- **Daily base backups** - Full backup at 3:00 AM
- **14-day retention** - Old backups automatically cleaned up

**Prerequisites:** Create the backup credentials secret:

```bash
kubectl create secret generic cnpg-backup-credentials \
  --namespace=immich \
  --from-literal=ACCESS_KEY_ID=<your-b2-key-id> \
  --from-literal=SECRET_ACCESS_KEY=<your-b2-application-key>
```

**Monitor backups:**

```bash
# Check backup status
kubectl get backups -n immich

# Check scheduled backup
kubectl get scheduledbackups -n immich

# View backup details
kubectl describe backup -n immich

# Manual backup trigger
kubectl cnpg backup immich-db -n immich
```

#### Manual Database Backup

```bash
# Manual pg_dump (for one-off exports)
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

**Cloudflare 100MB limit:** Cloudflare Free plan has a 100MB upload limit. For larger files,
use the direct LAN service (see below).

```bash
# Check ingress allows large uploads
kubectl describe ingress immich -n immich | grep body-size

# Check upload volume has space
kubectl exec -n immich deploy/immich-server -- df -h /usr/src/app/upload/upload
```

### Uploading Large Files (>100MB)

The Cloudflare tunnel has a 100MB upload limit. For larger files, use the direct LAN service:

```bash
# Direct LAN access (bypasses Cloudflare)
# Available at: http://192.168.1.203:2283

# Configure immich CLI for LAN uploads:
immich login http://192.168.1.203:2283 <your-api-key>

# Then upload normally
immich upload --recursive /path/to/large/videos
```

The LAN service is exposed via MetalLB at `192.168.1.201:2283`. This works from any machine
on your local network (e.g., corvus uploading from `/srv/photoprism/originals`).

**Note:** You'll need to configure the mobile app separately if you want LAN uploads there too.
Most mobile videos stay under 100MB with default compression settings.

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

## Hardware Transcoding

The Odroid H3+/Ultra nodes have Intel Celeron N5105 CPUs with integrated Intel UHD Graphics (Jasper Lake).
This enables hardware-accelerated video transcoding via **Intel Quick Sync (QSV)** or **VAAPI**.

### Prerequisites

Hardware transcoding requires the **Intel GPU Device Plugin** to be installed in the cluster.
The plugin exposes Intel GPUs as schedulable Kubernetes resources (`gpu.intel.com/i915`).

```bash
# Verify the GPU plugin is running
kubectl get pods -n intel-gpu-plugin

# Verify GPUs are detected on nodes
kubectl get nodes -o=jsonpath="{range .items[*]}{.metadata.name}{'\n'}{' i915: '}{.status.allocatable.gpu\.intel\.com/i915}{'\n'}"
```

See `config/intel-gpu-plugin/README.md` for plugin documentation.

### How It Works

The Immich server deployment requests a GPU resource:

```yaml
resources:
  limits:
    gpu.intel.com/i915: 1
```

The Intel GPU Device Plugin automatically:
- Mounts `/dev/dri` devices into the container
- Sets proper SELinux contexts for device access
- Handles all permissions without privileged mode

**Supported codecs (hardware accelerated):**
- H.264 (encode/decode)
- HEVC/H.265 (encode/decode)
- VP9 (encode/decode)
- AV1 (decode only)

### Configure in Admin UI

After deploying, configure hardware transcoding in the Immich web interface:

1. Go to **Administration** → **Settings** → **Video Transcoding**
2. Set **Hardware Acceleration** to: `qsv` (Quick Sync) or `vaapi`
3. Recommended settings:
   - **Acceleration API:** `qsv` (preferred) or `vaapi`
   - **Video Codec:** `hevc` (better compression) or `h264` (more compatible)
   - **Preset:** `medium` (hardware is fast, no need for ultrafast)
   - **Target Resolution:** `1080` or `720` depending on your needs
   - **CRF:** 23-28 (lower = better quality, larger files)

### Verify GPU Access

```bash
# Check GPU is visible in the pod
kubectl exec -n immich deploy/immich-server -c immich-server -- ls -la /dev/dri

# Expected output:
# crw-rw---- 1 root video 226,   0 ... card0
# crw-rw---- 1 root video 226, 128 ... renderD128

# Check Intel GPU info (if vainfo is available)
kubectl exec -n immich deploy/immich-server -c immich-server -- vainfo 2>/dev/null || echo "vainfo not in image, but GPU should still work"
```

### Benefits

- **~10x faster** transcoding compared to CPU
- **Lower power consumption** - GPU is more efficient than CPU for video
- **Reduced CPU load** - leaves CPU free for other tasks (ML, thumbnails)
- **No privileged containers** - GPU access via device plugin is secure

## TODO

- [ ] **Import Photos:** Start importing existing photo library - see "Importing Existing Photos" section above for methods (bulk import via kubectl, Immich CLI, or web upload).

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

