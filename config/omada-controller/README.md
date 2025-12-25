# Omada Controller

TP-Link Omada SDN Controller for managing WiFi access points, switches, and routers.

## Architecture

```
                                     ┌─────────────────┐
User → Cloudflare → nginx-ingress → │ oauth2-proxy    │ → Omada Controller
                                     │ (Pocket-ID)     │
                                     └─────────────────┘
                                            ↓
                                       Pocket-ID (OIDC)

APs/Switches → hostNetwork ports → Omada Controller
  (discovery: 27001, 29810-29814)
```

## Components

| Component | Purpose | Storage |
|-----------|---------|---------|
| Omada Controller | Network management | 5Gi SSD (data) + 1Gi HDD (logs) |
| oauth2-proxy | OIDC authentication | None |
| MongoDB | Database (embedded) | In data volume |

## Access

- **URL:** https://wifi.newjoy.ro
- **Auth:** Via Pocket-ID passkey, then Omada local admin

## Important: hostNetwork

The deployment uses `hostNetwork: true` because:
- APs broadcast on the network to discover the controller
- Device adoption requires direct network access
- Ports 27001, 29810-29814 must be accessible from the LAN

This means the pod runs on the node's network directly (not behind kube-proxy).

## Required Ports

| Port | Protocol | Purpose |
|------|----------|---------|
| 8088 | TCP | HTTP management UI |
| 27001 | UDP | Device discovery (legacy) |
| 29810 | UDP | Device discovery (v5.0+) |
| 29811 | TCP | AP adoption |
| 29812 | TCP | AP upgrade |
| 29813 | TCP | AP manager v1 |
| 29814 | TCP | AP manager v2 |

## Migration from Docker

### Option A: Backup/Restore (Recommended)

1. **Export from existing controller:**
   - Go to your current Omada Controller web UI
   - Navigate to **Settings → Maintenance → Backup & Restore**
   - Click **Export** to download a `.cfg` backup file

2. **Deploy in Kubernetes:**
   ```bash
   # Let ArgoCD sync the app
   # Wait for pod to be ready
   kubectl get pods -n omada-controller -w
   ```

3. **Restore configuration:**
   - Access https://wifi.newjoy.ro
   - Complete initial setup wizard
   - Go to **Settings → Maintenance → Backup & Restore**
   - Upload and restore the `.cfg` file

4. **Update device inform URL:**
   - In your APs/switches, update the inform URL to point to:
     - The Kubernetes node IP running the pod, OR
     - A DNS name that resolves to that node

### Option B: Copy Data Volume

If you want to migrate the MongoDB data directly:

1. **Stop the Docker container:**
   ```bash
   docker-compose down
   ```

2. **Copy data to PVC:**
   ```bash
   # Create a temporary pod to copy data
   kubectl run -n omada-controller data-copy --rm -it \
     --image=busybox \
     --overrides='{"spec":{"containers":[{"name":"data-copy","image":"busybox","command":["sh"],"volumeMounts":[{"name":"data","mountPath":"/data"}]}],"volumes":[{"name":"data","persistentVolumeClaim":{"claimName":"omada-data"}}]}}' \
     -- sh

   # From another terminal, copy data
   kubectl cp ./omada-config/data omada-controller/data-copy:/data
   ```

3. **Start the controller** - it will pick up the existing data

## One-Time Setup

### 1. Create OIDC Client in Pocket-ID

1. Go to https://auth.newjoy.ro
2. Navigate to **Admin → OIDC Clients → Create**
3. Configure:
   - **Name:** `Omada Controller`
   - **Redirect URIs:** `https://wifi.newjoy.ro/oauth2/callback`
4. Copy the **Client ID** and **Client Secret**

### 2. Create Kubernetes Secret

```bash
# Generate a random cookie secret (must be 16, 24, or 32 bytes)
COOKIE_SECRET=$(openssl rand -hex 16)

# Create the secret with values from Pocket-ID
kubectl create secret generic oauth2-proxy-omada \
  --namespace=omada-controller \
  --from-literal=client-id=<CLIENT_ID_FROM_POCKET_ID> \
  --from-literal=client-secret=<CLIENT_SECRET_FROM_POCKET_ID> \
  --from-literal=cookie-secret="$COOKIE_SECRET"
```

### 3. Initial Omada Setup

After first deployment:
1. Access https://wifi.newjoy.ro
2. Complete the setup wizard
3. Create an admin account (this is the second auth layer)
4. Adopt your devices

## Troubleshooting

```bash
# Check pods
kubectl get pods -n omada-controller

# Omada Controller logs
kubectl logs -n omada-controller -l app=omada-controller

# oauth2-proxy logs
kubectl logs -n omada-controller -l app=oauth2-proxy-omada

# Check if ports are listening on the node
ss -tlnp | grep -E '8088|27001|2981'

# Check device discovery
# On a device, check if it can reach the controller:
# curl http://<node-ip>:29811
```

## Database

Omada Controller uses an **embedded MongoDB** database. It cannot use PostgreSQL.

The MongoDB data is stored in the `omada-data` PVC at `/opt/tplink/EAPController/data/db`.

## Disaster Recovery

### Backup

1. **Longhorn snapshots** - Covers the MongoDB data
2. **Export configuration:**
   ```bash
   # Via UI: Settings → Maintenance → Export
   # Keep the .cfg file safe
   ```

### Restore

1. Restore Longhorn PVC from snapshot, OR
2. Use the backup/restore feature in the UI with the `.cfg` file

## Environment Variables

| Variable | Value | Description |
|----------|-------|-------------|
| `TZ` | Europe/Bucharest | Timezone |
| `MANAGE_HTTP_PORT` | 8088 | HTTP management port |
| `MANAGE_HTTPS_PORT` | 8043 | HTTPS management port (unused) |
| `SHOW_SERVER_LOGS` | true | Output server logs to stdout |
| `SHOW_MONGODB_LOGS` | false | Suppress noisy MongoDB logs |

See [mbentley/docker-omada-controller](https://github.com/mbentley/docker-omada-controller) for all options.

