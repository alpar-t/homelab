# Headscale - Self-Hosted VPN

Headscale is a self-hosted implementation of the Tailscale control server. It provides secure VPN access to your homelab from anywhere without opening inbound ports.

## Architecture

```
                     Internet
                        │
                        ▼
              ┌─────────────────┐
              │ Cloudflare CDN  │
              └────────┬────────┘
                       │
              ┌────────▼────────┐
              │Cloudflare Tunnel│  (outbound only, no inbound ports)
              └────────┬────────┘
                       │
              ┌────────▼────────┐
              │  ingress-nginx  │
              └────────┬────────┘
                       │
              ┌────────▼────────┐
              │   Headscale     │◄───── OIDC ─────► Pocket-ID
              │ Control Server  │                   (auth.newjoy.ro)
              └────────┬────────┘
                       │
     ┌─────────────────┼─────────────────┐
     │                 │                 │
     ▼                 ▼                 ▼
  iPhone           Android           Desktop
(Tailscale)      (Tailscale)       (Tailscale)
     │                 │                 │
     └─────────────────┼─────────────────┘
                       │
              ┌────────▼────────┐
              │  DERP Relays    │  (Tailscale's public servers)
              │   (fallback)    │
              └────────┬────────┘
                       │
              ┌────────▼────────┐
              │   Home Network  │
              │ 192.168.1.0/24  │
              └─────────────────┘
```

## Features

- **No inbound ports** - Uses Cloudflare Tunnel for control plane, DERP relays for data
- **OIDC authentication** - Login via Pocket-ID (passkey-based)
- **Pi-hole DNS** - All VPN traffic uses your Pi-hole (192.168.1.202)
- **Full LAN access** - Reach MetalLB IPs, k8s nodes, and local services
- **Native mobile apps** - Official Tailscale apps for iOS/Android

## Access

- **Control Server:** https://vpn.newjoy.ro
- **Auth:** Via Pocket-ID passkey

## Components

| Component | Purpose | Storage |
|-----------|---------|---------|
| Headscale | VPN control server | 1Gi Longhorn SSD (keys only) |
| PostgreSQL | Database (2 instances HA) | 1Gi Longhorn SSD |

---

## One-Time Setup

### 1. Create OIDC Client in Pocket-ID

1. Go to https://auth.newjoy.ro
2. Navigate to **Admin → OIDC Clients → Create**
3. Configure:
   - **Name:** `Headscale VPN`
   - **Redirect URIs:** `https://vpn.newjoy.ro/oidc/callback`
   - **Icon:** (optional) Upload a VPN icon for dashboard
4. Click **Create**
5. Copy the **Client ID** (no secret needed - public client with PKCE)

**Current Client ID:** `a3ffe55a-f7ba-4562-b8f9-87e6e62b5a03`

### 2. Create Namespace (if not done)

```bash
kubectl create namespace headscale
```

### 3. Sync via ArgoCD

The deployment will be synced automatically. Verify:

```bash
kubectl get pods -n headscale
kubectl logs -n headscale -l app=headscale
```

---

## Client Setup

### iOS (iPhone/iPad)

1. Install **Tailscale** from the App Store
2. Open Tailscale, tap the menu (top-left)
3. Scroll down, tap **Use a different server**
4. Enter: `https://vpn.newjoy.ro`
5. Tap **Sign in**
6. You'll be redirected to Pocket-ID - authenticate with your passkey
7. Approve the device in Tailscale

### Android

1. Install **Tailscale** from Google Play
2. Open Tailscale, tap the menu (top-left)
3. Tap **Use a different server**
4. Enter: `https://vpn.newjoy.ro`
5. Tap **Sign in**
6. Authenticate via Pocket-ID
7. Approve the device

### macOS

```bash
# Install Tailscale
brew install tailscale

# Connect to your Headscale server
tailscale login --login-server https://vpn.newjoy.ro
```

### Linux

```bash
# Install Tailscale (Debian/Ubuntu)
curl -fsSL https://tailscale.com/install.sh | sh

# Connect to your Headscale server
sudo tailscale up --login-server https://vpn.newjoy.ro
```

### Windows

1. Download Tailscale from https://tailscale.com/download
2. Install and open
3. Right-click system tray icon → **Preferences**
4. Under **Account**, click **Change...**
5. Enter: `https://vpn.newjoy.ro`
6. Sign in via Pocket-ID

---

## Subnet Router (LAN Access)

A Tailscale subnet router pod (`subnet-router.yaml`) advertises the LAN (`192.168.1.0/24`) to VPN clients, enabling access to MetalLB IPs and k8s nodes.

### How It Works

| Component | Purpose |
|-----------|---------|
| `subnet-router-setup-job.yaml` | Creates auth key with `tag:subnet-router` (PostSync, one-time) |
| `subnet-router.yaml` | Tailscale pod that advertises routes |
| ACL `autoApprovers` | Auto-approves routes from `tag:subnet-router` only |

### Security

- Only nodes with `tag:subnet-router` can advertise LAN routes
- The auth key is tagged, so only the subnet router pod gets this permission
- Regular VPN clients cannot advertise routes (no tag)
- Exit nodes are disabled

**No manual steps required** - routes are auto-approved via ACL policy on first connection.

### Manual Commands (if needed)

```bash
# Check subnet router status
kubectl get pods -n headscale -l app=tailscale-subnet-router

# List routes
kubectl exec -n headscale deploy/headscale -- headscale routes list

# List nodes with tags
kubectl exec -n headscale deploy/headscale -- headscale nodes list
```

---

## DNS Configuration

VPN clients automatically use Pi-hole (192.168.1.202) for DNS, configured in the Headscale config.

This means:
- Ad blocking works on VPN
- Local DNS entries (*.local) resolve correctly
- Split DNS for homelab services

---

## Accessing Services via VPN

Once connected via VPN with routes advertised:

| Service | Address | Description |
|---------|---------|-------------|
| Pi-hole DNS | 192.168.1.202 | DNS (automatic via Headscale) |
| Pi-hole UI | pihole.newjoy.ro | Web UI |
| Kubernetes nodes | pamacs.local, buksi.local, pufi.local | Direct node access |
| MetalLB services | 192.168.1.200-254 | LoadBalancer IPs |

---

## Headscale Administration

### List Nodes

```bash
kubectl exec -n headscale deploy/headscale -- headscale nodes list
```

### Remove a Node

```bash
kubectl exec -n headscale deploy/headscale -- headscale nodes delete -i NODE_ID
```

### List Routes

```bash
kubectl exec -n headscale deploy/headscale -- headscale routes list
```

### Enable/Disable Routes

```bash
kubectl exec -n headscale deploy/headscale -- headscale routes enable -r ROUTE_ID
kubectl exec -n headscale deploy/headscale -- headscale routes disable -r ROUTE_ID
```

### Create API Key (for automation)

```bash
kubectl exec -n headscale deploy/headscale -- headscale apikeys create --expiration 90d
```

---

## Troubleshooting

### Check Headscale Status

```bash
kubectl get pods -n headscale
kubectl logs -n headscale -l app=headscale
```

### Test OIDC Flow

1. Open https://vpn.newjoy.ro in a browser
2. You should see the Headscale web interface
3. Click login to test OIDC flow with Pocket-ID

### Client Connection Issues

```bash
# On the client
tailscale status
tailscale netcheck

# Check DERP connectivity
tailscale debug derp
```

### VPN Connected but Can't Reach LAN

1. Verify routes are advertised: `tailscale status`
2. Check routes are enabled in Headscale: `headscale routes list`
3. Ensure the route-advertising node is online

---

## Disaster Recovery

### Backup Strategy

Database backups use **CloudNativePG-native backups** to Backblaze B2:

| Layer | What | Frequency | Retention |
|-------|------|-----------|-----------|
| WAL Archiving | Continuous transaction logs | Real-time | 30 days |
| Base Backup | Full database snapshot | Daily 3:15 AM | 30 days |
| Noise Key | Cryptographic key (PVC) | Longhorn snapshots | Longhorn retention |

### Verify Backups

```bash
# Check backup status
kubectl get backups -n headscale

# Check cluster backup status
kubectl get cluster headscale-db -n headscale -o jsonpath='{.status.firstRecoverabilityPoint}'
```

### Restore: Point-in-Time Recovery (PITR)

To restore to a specific point in time, create a new cluster with recovery configuration:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: headscale-db-restored
  namespace: headscale
spec:
  instances: 2
  imageName: ghcr.io/cloudnative-pg/postgresql:16
  
  bootstrap:
    recovery:
      source: headscale-db
      recoveryTarget:
        targetTime: "2024-01-15 10:30:00.000000+00"
  
  externalClusters:
    - name: headscale-db
      barmanObjectStore:
        destinationPath: "s3://homelab-longhorn-backup/cnpg/headscale-db"
        endpointURL: "https://s3.eu-central-003.backblazeb2.com"
        s3Credentials:
          accessKeyId:
            name: cnpg-backup-credentials
            key: ACCESS_KEY_ID
          secretAccessKey:
            name: cnpg-backup-credentials
            key: SECRET_ACCESS_KEY
  
  storage:
    size: 1Gi
    storageClass: longhorn-ssd
```

### Backup Noise Key

The noise private key is stored on the PVC. Back it up separately if needed:

```bash
kubectl exec -n headscale deploy/headscale -- cat /var/lib/headscale/noise_private.key > noise_private.key.backup
```

---

## Security Notes

1. **OIDC only** - No pre-auth keys or manual user creation needed
2. **Cloudflare Tunnel** - Control plane never directly exposed to internet
3. **DERP relays** - Data plane uses Tailscale's encrypted relays when direct connection isn't possible
4. **MagicDNS** - Clients get their own `*.vpn.newjoy.ro` hostnames
5. **ACL** - Configure access policies in `acl.json` if needed

