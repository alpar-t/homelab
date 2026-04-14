# Media Stack (Arr + Emby)

Automated media management with Sonarr, Radarr, Prowlarr, qBittorrent, and Emby.

## Architecture

```
Prowlarr (indexers) → Sonarr/Radarr (search & grab) → qBittorrent (download)
                                                            │
                                        rename & hardlink → /data/media/
                                                            │
                                                         Emby (serve)
```

Split storage: SSD for active downloads (random I/O), HDD for completed + library
(sequential I/O). Hardlinks work within each HDD volume.

## Prerequisites

### 1. Create OIDC Client in Pocket ID

Create **one** OIDC client at https://auth.newjoy.ro:
- **Name**: `Media`
- **Redirect URI**: `https://media-auth.newjoy.ro/oauth2/callback`

### 2. Create Kubernetes Secret

```bash
COOKIE_SECRET=$(openssl rand -hex 16)

kubectl create secret generic oauth2-proxy-media -n media \
  --from-literal=client-id='YOUR_POCKET_ID_CLIENT_UUID' \
  --from-literal=client-secret='YOUR_CLIENT_SECRET' \
  --from-literal=cookie-secret="$COOKIE_SECRET"
```

### 3. Cloudflare Tunnel DNS

Add CNAME records pointing to your tunnel for:
- `media-auth.newjoy.ro` (oauth2-proxy callback)
- `sonarr.newjoy.ro`
- `radarr.newjoy.ro`
- `prowlarr.newjoy.ro`
- `qbit.newjoy.ro`

### 4. Router Port Forwarding

Forward port **6881 TCP+UDP** to `192.168.1.205` for incoming BitTorrent peer connections.

## Post-Deployment Configuration

### qBittorrent (qbit.newjoy.ro)

Default credentials: admin / check container logs for random password on first start.

**Download paths** (Settings → Downloads):
- Default save path: `/data/movies/downloads/complete` (overridden per category)
- Enable "Keep incomplete torrents in": `/incomplete`

**Categories** (right-click in transfer list → Categories):
- `radarr` → save path: `/data/movies/downloads/complete`
- `sonarr` → save path: `/data/tv/downloads/complete`

**Performance tuning** (Settings → Advanced):
- Disk cache: `512` MiB
- Disk IO read/write mode: `Disable OS cache` (prevents mmap bloat in containers)
- File pool size: `5000`
- Send buffer watermark: `5120` KiB
- Send buffer low watermark: `512` KiB
- Connections limit: `500` global, `200` per torrent
- Upload slots: `50` global, `8` per torrent

**Seeding** (Settings → BitTorrent):
- Set ratio limit or seed time limit based on your preference

### Prowlarr (prowlarr.newjoy.ro)

1. Add your indexers (torrent trackers)
2. Add Sonarr as an app: Settings → Apps → Sonarr
   - Prowlarr Server: `http://prowlarr.media.svc.cluster.local:9696`
   - Sonarr Server: `http://sonarr.media.svc.cluster.local:8989`
   - API Key: from Sonarr → Settings → General
3. Add Radarr as an app: same pattern with port 7878

### Sonarr (sonarr.newjoy.ro)

1. Settings → Media Management → Root Folder: `/data/media/tv`
2. Settings → Download Clients → qBittorrent:
   - Host: `qbittorrent.media.svc.cluster.local`
   - Port: `8080`
   - Category: `sonarr`

### Radarr (radarr.newjoy.ro)

1. Settings → Media Management → Root Folder: `/data/media/movies`
2. Settings → Download Clients → qBittorrent:
   - Host: `qbittorrent.media.svc.cluster.local`
   - Port: `8080`
   - Category: `radarr`

### Emby (http://192.168.1.204:8096 — LAN only)

1. Run through initial setup wizard
2. Add library: Movies → `/data/movies/media/movies`
3. Add library: TV Shows → `/data/tv/media/tv`
4. Enable hardware transcoding: Settings → Transcoding → Hardware acceleration: VAAPI
5. Enable subtitle downloads: Settings → Subtitles

## Authentication

Built-in auth is set to `External` on Sonarr, Radarr, and Prowlarr (trusts the
reverse proxy). A single oauth2-proxy instance handles OIDC via Pocket ID for all
media apps. One login sets a cookie on `.newjoy.ro` — works across all subdomains.

## Access

| App | External | LAN |
|-----|----------|-----|
| Emby | — | http://192.168.1.204:8096 |
| Sonarr | https://sonarr.newjoy.ro | — |
| Radarr | https://radarr.newjoy.ro | — |
| Prowlarr | https://prowlarr.newjoy.ro | — |
| qBittorrent | https://qbit.newjoy.ro | — |

## Storage

| PVC | Class | Size | Purpose |
|-----|-------|------|---------|
| qbit-incomplete | longhorn-ssd-noreplica (RWO) | 300Gi | Active torrent downloads (random I/O) |
| movies-data | longhorn-hdd-noreplica (RWX) | 1.5Ti | Movie downloads + library |
| tv-data | longhorn-hdd-noreplica (RWX) | 1Ti | TV downloads + library |
| emby-config | longhorn-ssd | 2Gi | Emby metadata & settings |
| sonarr-config | longhorn-ssd | 1Gi | Sonarr database & settings |
| radarr-config | longhorn-ssd | 1Gi | Radarr database & settings |
| prowlarr-config | longhorn-ssd | 1Gi | Prowlarr database & settings |
| qbittorrent-config | longhorn-ssd | 1Gi | qBittorrent settings & resume data |

Config PVCs are backed up via weekly Longhorn backup. Media volumes are excluded.
