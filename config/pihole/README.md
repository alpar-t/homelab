# Pi-hole - Network-wide Ad Blocking

Pi-hole deployed as a DaemonSet for high availability DNS across all nodes.

## Architecture

```
Local Network:
  Devices → Router DNS (node IPs:53) → Pi-hole DaemonSet

Mobile (VPN):
  Phone → MikroTik L2TP/IPsec → Pi-hole DNS

Web UI:
  Browser → pihole.newjoy.ro → Authentik SSO → Pi-hole Admin
```

## Components

| Component | Purpose | HA Strategy |
|-----------|---------|-------------|
| Pi-hole DaemonSet | DNS + Ad blocking | Runs on every node (hostNetwork) |
| Web UI Ingress | Admin interface | Via Authentik SSO |

## Access

- **Web UI:** https://pihole.newjoy.ro (protected by Authentik SSO)
- **Local DNS:** Any node IP on port 53

## Setup

### 1. Configure Authentik (Required for Web UI)

1. **Create Provider** in Authentik Admin:
   - Go to: Applications → Providers → Create
   - Type: **Proxy Provider**
   - Name: `pihole-proxy`
   - Mode: **Proxy**
   - External host: `https://pihole.newjoy.ro`
   - Internal host: `http://pihole-web.pihole.svc.cluster.local:80`

2. **Create Application**:
   - Go to: Applications → Applications → Create
   - Name: `Pi-hole`
   - Slug: `pihole`
   - Provider: select `pihole-proxy`
   - Icon (optional): `https://pi-hole.net/wp-content/uploads/2016/12/Vortex-R.png`

3. **Add to Outpost**:
   - Go to: Applications → Outposts → authentik Embedded Outpost
   - Add `Pi-hole` to Applications
   - Click Update

Pi-hole has no internal password - Authentik handles all authentication.

### 2. Configure Local Network DNS

Configure your router to use Pi-hole as DNS. For HA, add all node IPs:

```
Primary DNS:   192.168.x.10  (node 1)
Secondary DNS: 192.168.x.11  (node 2)
```

Replace with your actual node IPs. Pi-hole runs on standard port 53 using hostNetwork mode.

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
- DNS Server: `<your-node-ip>` (any node IP, e.g., `192.168.1.10`)
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
kubectl get pods -n pihole -o wide
kubectl logs -n pihole -l app=pihole
```

### Test DNS resolution

```bash
# From a node
dig @localhost google.com

# Or using node IP from your workstation
dig @<node-ip> google.com
```

### Check query logs

Access the web UI at https://pihole.newjoy.ro and check Query Log.

## Notes

- Pi-hole runs on every node as a DaemonSet with hostNetwork for high availability
- DNS is exposed on standard port 53 on each node - configure your router to use node IPs
- Web UI is SSO-protected via Authentik - no separate Pi-hole password
- Data is ephemeral (emptyDir) - custom blocklists need reconfiguration after pod restart

## Adding Custom Blocklists

Via the web UI:
1. Go to https://pihole.newjoy.ro
2. Settings → Adlists → Add new
3. Popular lists: https://firebog.net/
 