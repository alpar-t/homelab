# Pi-hole - Network-wide Ad Blocking

High-availability Pi-hole with hot spare failover for DNS redundancy.

## Architecture

```
Local Network:
  Devices → Router DNS → MetalLB (192.168.1.202) → Active Pi-hole

Mobile (VPN):
  Phone → MikroTik L2TP/IPsec → MetalLB → Active Pi-hole

Web UI:
  Browser → pihole.newjoy.ro → oauth2-proxy → Active Pi-hole Admin
                                    ↓
                              Pocket-ID SSO
```

### Hot Spare Failover Design

```
                    ┌─────────────────┐
                    │    MetalLB      │
                    │  192.168.1.202  │
                    └────────┬────────┘
                             │
                             │ externalTrafficPolicy: Local
                             │ (routes only to announcing node)
                             │
                             ▼
   ┌───────────────┐                   ┌───────────────┐
   │    pihole     │                   │   pihole-2    │
   │   (ACTIVE)    │ ←── all traffic   │   (STANDBY)   │
   │    Node A     │                   │    Node B     │
   └───────────────┘                   └───────────────┘
         │                                   │
   ┌─────┴─────┐                       ┌─────┴─────┐
   │ local-ssd │                       │ local-ssd │
   │    PVC    │                       │    PVC    │
   └───────────┘                       └───────────┘

         │ Node A fails
         ▼

   ┌───────────────┐                   ┌───────────────┐
   │    pihole     │                   │   pihole-2    │
   │    (DOWN)     │                   │   (ACTIVE)    │ ←── all traffic
   │    Node A     │                   │    Node B     │
   └───────────────┘                   └───────────────┘
```

**How it works:**
- `externalTrafficPolicy: Local` makes MetalLB route traffic only to pods on the announcing node
- Pod anti-affinity ensures the two Pi-holes run on different nodes
- Only one Pi-hole receives traffic at a time (the one on MetalLB's announcing node)
- If that node/pod fails, MetalLB fails over to the other node → traffic goes to standby
- **Bonus:** Real client IPs are preserved in Pi-hole query logs

## Components

| Component | Purpose |
|-----------|---------|
| pihole Deployment | Active DNS + Ad blocking |
| pihole-2 Deployment | Hot spare (standby) |
| 2x PVC (1Gi local-ssd) | Independent local storage per instance |
| LoadBalancer Service | Single IP with hot spare failover |
| oauth2-proxy | Authentication via Pocket-ID |
| Web UI Ingress | Admin interface via SSO |

## Access

- **DNS:** `192.168.1.202` (MetalLB LoadBalancer, hot spare failover)
- **Web UI:** https://pihole.newjoy.ro (protected by Pocket-ID SSO)

## Setup

### 1. Configure oauth2-proxy (Required for Web UI)

See `config/oauth2-proxy-pihole/README.md` for one-time setup:
1. Create OIDC client in Pocket-ID
2. Create Kubernetes secret with client credentials
3. ArgoCD deploys oauth2-proxy automatically

Pi-hole has no internal password - Pocket-ID handles all authentication.

### 2. Configure Local Network DNS

Configure your router's DHCP to use the MetalLB IP:

```
DNS Server: 192.168.1.202
```

This single IP routes to the active Pi-hole. If it fails, MetalLB automatically fails over to the standby.

## Mobile Access (MikroTik L2TP/IPsec VPN)

Use your MikroTik router's built-in VPN to access Pi-hole from iOS/Android.

> **Note:** This guide uses L2TP/IPsec which works on RouterOS v6 and v7. If you upgrade to RouterOS v7, consider WireGuard instead (faster, simpler, better battery life).

### Full Tunnel vs Split Tunnel (DNS Only)

| Mode | What it routes | Use when |
|------|----------------|----------|
| **Full tunnel** | All traffic through VPN | You want all mobile traffic protected (privacy on public WiFi, access home network resources) |
| **DNS only** | Only DNS queries | You just want ad-blocking, don't want to slow down video/downloads |

**Default:** L2TP creates a full tunnel. For DNS-only, you need extra client config (covered below).

### MikroTik Setup (WebFig/Winbox)

#### 1. Create IP Pool for VPN clients

- Go to: **IP → Pool**
- Click **+** to add new
- Name: `vpn-pool`
- Addresses: `10.0.100.2-10.0.100.20`
- Click **OK**

#### 2. Create PPP Profile

- Go to: **PPP → Profiles**
- Click **+** to add new
- Name: `vpn-profile`
- Local Address: `10.0.100.1`
- Remote Address: `vpn-pool`
- DNS Server: `<any-node-ip>` (e.g., `192.168.1.10` - MikroTik will find Pi-hole)
- Click **OK**

#### 3. Create VPN User

- Go to: **PPP → Secrets**
- Click **+** to add new
- Name: `phone` (or your username)
- Password: (create a strong password)
- Service: `l2tp`
- Profile: `vpn-profile`
- Click **OK**

#### 4. Enable L2TP Server

- Go to: **PPP → Interface**
- Click **L2TP Server** button at top
- Enabled: ✓
- Use IPsec: `required`
- IPsec Secret: (create a pre-shared key, e.g., `MyIPsecKey123`)
- Default Profile: `vpn-profile`
- Click **OK**

#### 5. Firewall Rules

- Go to: **IP → Firewall → Filter Rules**
- Click **+** to add new rule:
  - Chain: `input`
  - Protocol: `udp`
  - Dst. Port: `500,1701,4500`
  - Action: `accept`
  - Comment: `Allow L2TP/IPsec`
- Click **OK**
- Drag rule above any drop rules

- Add another rule:
  - Chain: `input`
  - Protocol: `ipsec-esp`
  - Action: `accept`
  - Comment: `Allow IPsec ESP`
- Click **OK**

#### 6. NAT for VPN clients (if accessing internet through VPN)

- Go to: **IP → Firewall → NAT**
- Click **+** to add new
- Chain: `srcnat`
- Src. Address: `10.0.100.0/24`
- Action: `masquerade`
- Click **OK**

### iOS Setup

1. **Settings → VPN → Add VPN Configuration**
2. Type: `L2TP`
3. Description: `Home Pi-hole`
4. Server: Your public IP or dynamic DNS hostname
5. Account: `phone` (username from step 3)
6. Password: (password from step 3)
7. Secret: (IPsec secret from step 4)
8. Send All Traffic: **ON** (full tunnel) or **OFF** (see DNS-only below)

### Android Setup

1. **Settings → Network → VPN → Add VPN**
2. Name: `Home Pi-hole`
3. Type: `L2TP/IPSec PSK`
4. Server address: Your public IP or dynamic DNS
5. IPSec pre-shared key: (IPsec secret from step 4)
6. Username: `phone`
7. Password: (password from step 3)

### DNS-Only Mode (Split Tunnel)

By default, L2TP routes everything. For DNS-only:

**iOS:** 
- In VPN config, set "Send All Traffic" to **OFF**
- iOS will still use the VPN's DNS server for all queries

**Android:**
- Android's built-in VPN client always does full tunnel
- For split tunnel, use an app like **strongSwan VPN Client**:
  1. Install from Play Store
  2. Add profile → IKEv1 (or IPsec)
  3. In settings, configure "Split tunneling" to only route DNS (10.0.100.0/24)

**When to use which:**

- **Full tunnel:** Public WiFi (coffee shops, airports), want privacy for all traffic
- **DNS only:** On mobile data, just want ad-blocking without routing all traffic through home (saves battery, faster)

## Troubleshooting

### Check Pi-hole pods

```bash
# Both pods should be Running on different nodes
kubectl get pods -n pihole -o wide

# Check logs for both instances
kubectl logs -n pihole -l app=pihole --prefix
```

### Test DNS resolution

```bash
# Via MetalLB IP
dig @192.168.1.202 google.com
```

### Verify failover setup

```bash
# Check endpoints - should show both pod IPs
kubectl get endpoints pihole-dns -n pihole

# Check which node MetalLB is announcing from
kubectl get pods -n pihole -o wide
# The pod on the MetalLB announcing node is the active one
```

### Test failover

```bash
# Delete the active pod to trigger failover
kubectl delete pod -n pihole <active-pod-name>

# DNS should continue working (via standby)
dig @192.168.1.202 google.com
```

### Check query logs

Access the web UI at https://pihole.newjoy.ro and check Query Log.

## Notes

- Two Pi-hole instances: one active, one hot spare
- DNS exposed via MetalLB LoadBalancer (192.168.1.202)
- Hot spare failover via `externalTrafficPolicy: Local`
- Only one Pi-hole receives traffic at a time; standby takes over on failure
- Real client IPs preserved in query logs (benefit of Local policy)
- Local SSD storage for fast restarts (data is rebuildable)
- Web UI is SSO-protected via Pocket-ID - no separate Pi-hole password
- Both instances share the same ConfigMaps (custom DNS, dnsmasq config)

## Data Storage

Each Pi-hole instance uses **local SSD storage** (local-ssd PVC, 1Gi per instance).

**Why local storage?**
- Faster pod restarts (no Longhorn attach/detach overhead)
- Data is rebuildable - blocklists re-download, config is in ConfigMaps
- With two instances, losing one's data doesn't affect DNS availability

**Persisted (per instance):**
- Downloaded blocklists (re-downloaded on gravity update)
- Query logs and statistics (on active instance only; resets on failover)
- Cached settings

**Configured via ConfigMaps (shared by both instances):**
- Custom DNS entries (`pihole-custom-dns`)
- dnsmasq configuration (`pihole-dnsmasq`)

**Configured via env vars:**
- Upstream DNS (defaults to Cloudflare, managed by benchmark job)
- DNSSEC enabled
- Timezone, web port

## Trade-offs

| Benefit | Trade-off |
|---------|-----------|
| Hot spare failover | Standby sits idle until needed |
| Single DNS IP for clients | - |
| Real client IPs in logs | - |
| Local SSD = fast restarts | Data lost if node dies (but rebuildable) |

## Local DNS (GitOps Managed)

Custom local DNS entries are managed via GitOps in `manifests/custom-dns-configmap.yaml`.

### Adding a New Entry

1. Edit `config/pihole/manifests/custom-dns-configmap.yaml`:
   ```
   192.168.1.200 ha-db.local
   192.168.1.201 nextcloud-db.local
   ```

2. Push to Git

3. ArgoCD syncs the ConfigMap

4. Reloader detects the change and restarts Pi-hole automatically

### Current Entries

| Hostname | IP | Service |
|----------|-----|---------|
| ha-db.local | 192.168.1.200 | Home Assistant PostgreSQL |

> **Note:** The deployment has a Reloader annotation that watches `pihole-custom-dns`. When you update the ConfigMap via Git, Pi-hole will automatically restart to pick up changes.

## Adding Custom Blocklists

Via the web UI:
1. Go to https://pihole.newjoy.ro
2. Settings → Adlists → Add new
3. Popular lists: https://firebog.net/
