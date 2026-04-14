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

Configure in this order — each step depends on the previous.

### Step 1: qBittorrent (qbit.newjoy.ro)

**First login:** username `admin`, password from container logs:
```bash
kubectl logs -n media deployment/qbittorrent | grep "temporary password"
```

**Download paths** (Settings → Downloads):
- Default save path: `/data/movies/downloads/complete`
- Enable "Keep incomplete torrents in": `/incomplete`

**Categories** (right-click in transfer list → Categories → Add category):
- `radarr` → save path: `/data/movies/downloads/complete`
- `sonarr` → save path: `/data/tv/downloads/complete`

**Connection** (Settings → Connection):
- Listening port: `6881` (already exposed via MetalLB at 192.168.1.205)
- Enable UPnP: **off** (MetalLB handles this)

**Speed** (Settings → Speed):
- Set upload limit if your ISP has asymmetric bandwidth

**BitTorrent** (Settings → BitTorrent):
- Enable DHT, PeX, and Local Peer Discovery
- Set seed ratio limit (e.g., 2.0) or seed time limit based on preference
- When ratio is reached: Pause torrent (Sonarr/Radarr handle cleanup)

**Performance tuning** (Settings → Advanced):
- Disk cache: `512` MiB
- Disk IO read/write mode: `Disable OS cache` (critical — prevents mmap memory bloat)
- File pool size: `5000`
- Send buffer watermark: `5120` KiB
- Send buffer low watermark: `512` KiB
- Connections limit: `500` global, `200` per torrent
- Upload slots: `50` global, `8` per torrent
- Resolve peer countries: **off** (saves CPU)

**Web UI** (Settings → Web UI):
- Change the default password

### Step 2: Prowlarr (prowlarr.newjoy.ro)

1. Add your torrent indexers: Indexers → Add Indexer
2. Note the Prowlarr API key: Settings → General → API Key
3. Add Sonarr: Settings → Apps → Add → Sonarr
   - Sync Level: Full Sync
   - Prowlarr Server: `http://prowlarr.media.svc.cluster.local:9696`
   - Sonarr Server: `http://sonarr.media.svc.cluster.local:8989`
   - API Key: from Sonarr (Step 3 below)
4. Add Radarr: Settings → Apps → Add → Radarr
   - Sync Level: Full Sync
   - Prowlarr Server: `http://prowlarr.media.svc.cluster.local:9696`
   - Radarr Server: `http://radarr.media.svc.cluster.local:7878`
   - API Key: from Radarr (Step 4 below)

### Step 3: Sonarr (sonarr.newjoy.ro)

**API Key:** Settings → General → API Key (copy this for Prowlarr)

**Root folder:** Settings → Media Management → Add Root Folder → `/data/media/tv`

**Quality profile for 4K HDR:** Settings → Profiles → Edit or create:
- Name: `4K HDR`
- Upgrade until: Bluray-2160p Remux
- Qualities (top = preferred): Bluray-2160p Remux > Bluray-2160p > WEB 2160p > Bluray-1080p Remux
- Custom Formats: add `HDR10`, `DTS-HD MA`, `TrueHD Atmos`, `DTS-X` and score them positively

**Download client:** Settings → Download Clients → Add → qBittorrent:
- Host: `qbittorrent.media.svc.cluster.local`
- Port: `8080`
- Category: `sonarr`
- Remove Completed: **on** (removes from qBit after import)

**Naming:** Settings → Media Management:
- Rename Episodes: **on**
- Standard format: `{Series TitleYear} - S{season:00}E{episode:00} - {Episode CleanTitle} [{Quality Full}]{[MediaInfo VideoDynamicRangeType]}`
- Season folder: `Season {season:00}`

### Step 4: Radarr (radarr.newjoy.ro)

**API Key:** Settings → General → API Key (copy this for Prowlarr)

**Root folder:** Settings → Media Management → Add Root Folder → `/data/media/movies`

**Quality profile for 4K HDR:** Settings → Profiles → Edit or create:
- Name: `4K HDR`
- Upgrade until: Remux-2160p
- Qualities: Remux-2160p > Bluray-2160p > WEB 2160p > Remux-1080p
- Custom Formats: add `HDR10`, `HDR10+`, `Dolby Vision`, `DTS-HD MA`, `TrueHD Atmos`, `DTS-X`
  and score them positively to prefer best audio/video

**Download client:** Settings → Download Clients → Add → qBittorrent:
- Host: `qbittorrent.media.svc.cluster.local`
- Port: `8080`
- Category: `radarr`
- Remove Completed: **on**

**Naming:** Settings → Media Management:
- Rename Movies: **on**
- Standard format: `{Movie CleanTitle} ({Release Year}) [{Quality Full}]{[MediaInfo VideoDynamicRangeType]}{[MediaInfo AudioCodec]}`

### Step 5: Connect Prowlarr to Sonarr/Radarr

Go back to Prowlarr and enter the API keys you copied in Steps 3 and 4.
After saving, Prowlarr will sync your indexers to both apps automatically.
Verify: check Sonarr/Radarr → Settings → Indexers — they should show up.

### Step 6: Emby (http://192.168.1.204:8096 — LAN only)

**Initial setup wizard:**
1. Set language and create admin account
2. Add libraries:
   - Movies → `/data/movies/media/movies`
   - TV Shows → `/data/tv/media/tv`

**Emby Premiere:** Settings → Emby Premiere
- Enter your Premiere key to unlock hardware transcoding and other features
- Without Premiere, hardware transcoding is disabled

**Hardware transcoding:** Settings → Server → Transcoding
- Hardware acceleration: **VAAPI** (Intel QSV)
- Hardware decoding: **enable all codecs** (H.264, HEVC, VP9, AV1)
- Enable hardware encoding: **on**
- Enable tone mapping: **on** (converts HDR→SDR when client doesn't support HDR)
- Preferred tone mapping mode: **VPP** (uses Intel GPU, much faster than software)
- Allow encoding in HEVC: **on** (smaller transcoded files)

**Playback:** Settings → Server → Playback
- Internet streaming bitrate limit: **unlimited** (or match your upload speed)
- LAN streaming bitrate limit: **unlimited**

**Subtitles:** Settings → Server → Subtitles
- Subtitle download languages: your preferred languages
- Open Subtitles: add your account credentials

**Scheduled tasks:** Settings → Server → Scheduled Tasks
- Library scan: set to run every few hours or daily
- Chapter image extraction: can be CPU intensive, schedule overnight

**Network:** Settings → Server → Network
- Secure connections: **Not required** (LAN only, no TLS needed)

**4K HDR direct play tips:**
- Prefer direct play over transcoding — set clients to original quality
- If a client doesn't support HDR, Emby will tone-map via GPU (requires Premiere)
- For 7.1 audio passthrough, use a client that supports it (e.g., Emby Theater, Kodi, Shield TV)

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
