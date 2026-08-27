# Direct WireGuard for the GL-MT3000 travel router

The GL-MT3000 uses a direct, split-tunnel WireGuard connection to reach the
home `192.168.1.0/24` LAN. Public internet traffic stays on the GL's current
WAN, while the GL's local dnsmasq cache forwards DNS to the home Pi-hole
through WireGuard. This avoids Tailscale's direct/DERP path transitions and
stops LAN clients from bypassing the GL cache.

The internet router forwards to MetalLB VIP `192.168.1.208`. The single
WireGuard pod is softly preferred on `buksi`, where the MetalLB
`externalTrafficPolicy: Local` media services run, but can reschedule to
another node. MetalLB moves the VIP to the pod's node, while the shared Secret
keeps the server identity unchanged. WireGuard is the only remote-access
deployment; the old Tailscale subnet router is removed during cutover.

## Addressing and routing

| Purpose | Value |
| --- | --- |
| Home endpoint | `torok.go.ro:41641/udp` |
| Home MetalLB VIP | `192.168.1.208` |
| Home WireGuard address | `10.77.0.1/24` |
| GL WireGuard address | `10.77.0.2/32` |
| Routed through WireGuard | `10.77.0.1/32`, Pi-hole `10.43.252.171/32`, home host `/32`s, `192.168.1.0/24` |
| GL LANs accepted by home | `192.168.80.0/24`, `192.168.9.0/24` |
| DNS path | Clients → GL dnsmasq cache → Pi-hole ClusterIP `10.43.252.171` through WG |
| MTU | `1380` |
| NAT keepalive | 25 seconds |

The home pod source-NATs WireGuard and GL-LAN sources before sending them to
the home LAN. Home devices therefore need no route back to `10.77.0.0/24` or
the GL LAN.

The generated GL profile includes `/32` routes for Pi-hole, Home Assistant,
Immich, and Emby before the broad home `/24`. Those more-specific routes still
win when a hotel WAN also uses `192.168.1.0/24`.

## One-time preparation

### 1. Confirm the address and port

Confirm that `192.168.1.208` is not assigned to a static LAN device and reserve
it for MetalLB. Keep the external port at **UDP `41641`**; TCP is neither needed
nor useful.

The generated GL profile assumes the public and private ports are both
`41641`. If the existing rule uses a different public port, change only the
profile's `Endpoint` port before importing it. Confirm that `torok.go.ro`
resolves to the current home public address.

### 2. Generate keys and the GL profile

Choose a private path outside the repository and run:

```bash
scripts/prepare-travel-wireguard.sh /secure/path/gl-home.conf
```

The helper:

- uses a short-lived key-generation pod and the registry-verified WireGuard
  image;
- creates the manually-managed `wireguard/wireguard-keys` Secret with the
  home private key, GL public key, and per-peer preshared key;
- writes the GL private key only into the mode-`0600` import profile; and
- refuses to overwrite either an existing profile or an existing Secret, so
  an accidental rerun cannot silently rotate the tunnel.

The private profile is the only client-key backup. Store it with other secrets
until the GL has imported it, then delete the loose copy if the router backup
is sufficient.

### 3. Deploy the home listener

Commit and push the manifests only after the Secret exists. ArgoCD replaces
the `tailscale` Application with `wireguard`, deploys `wireguard-home` from
`config/wireguard/manifests/`, and removes the old Tailscale namespace.

```bash
kubectl -n wireguard rollout status deployment/wireguard-home
kubectl -n wireguard logs deployment/wireguard-home --tail=100
kubectl -n wireguard exec deployment/wireguard-home -- wg show wg0
kubectl -n wireguard exec deployment/wireguard-home -- \
  ss -ulnp | grep ':41641'
kubectl -n wireguard get service wireguard-home -o wide
```

Once the Service shows external IP `192.168.1.208`, change the internet
router's existing rule to forward **UDP `41641`** to
**`192.168.1.208:41641`**. The VIP target is what allows the pod to move
between nodes.

At this stage `latest handshake` is absent because the GL is not connected.
That is healthy; readiness tests the interface, not peer reachability.

### HA behavior

There is deliberately one active pod, not multiple WireGuard servers sharing
a UDP flow. If its node becomes NotReady/Unreachable, the 30-second toleration
expires, Kubernetes creates the pod elsewhere, and MetalLB re-advertises
`192.168.1.208` from that node. The GL then performs a new handshake with the
same server key and endpoint. Expect roughly tens of seconds plus scheduling
and image-start time, not lossless failover.

While `buksi` is healthy, soft affinity keeps the pod there so Emby, Immich,
and arr-stack LoadBalancers with Local traffic policy work through the tunnel.
If `buksi` itself is down those buksi-pinned services are down too; WireGuard
failover still preserves Pi-hole, Home Assistant, and other reachable LAN or
Cluster-policy services.

## GL cutover

Do this while physically connected to the GL LAN, so a VPN mistake cannot
lock out router administration.

Do not start this profile from **VPN → WireGuard Client**. On this firmware the
GL UI attaches even a split-AllowedIPs profile to its global `Primary Tunnel`
and kill switch, which blackholes ordinary internet traffic. The UI profile
used during the initial import was removed after its values were copied.

Configure a normal OpenWrt `proto=wireguard` interface named `wg_home` in
`/etc/config/network`, using the keys and endpoint from `gl-home.conf`:

- interface address `10.77.0.2/32`, MTU `1380`;
- endpoint `torok.go.ro:41641`, keepalive 25 seconds;
- `route_allowed_ips=1`;
- allowed IPs `10.77.0.1/32`, `10.43.252.171/32`, the home-service `/32`s,
  and `192.168.1.0/24`.

Put `wg_home` in its own firewall zone with output accepted, masquerading and
MTU fixing enabled, then add a `lan` → `wg_home` forwarding. Leave the
interface without `disabled=1`: netifd then starts it automatically at boot.
Ordinary internet keeps using the WAN default route because WireGuard has no
`0.0.0.0/0` AllowedIP.

Verify on the GL:

```bash
wg show
ip route | grep -E '10\.77\.0\.1|192\.168\.1\.0'

# MetalLB does not reliably answer ICMP; use TCP application checks.
curl -fsS -o /dev/null http://192.168.1.204:8096 && echo 'Emby reachable'
curl -fsS -o /dev/null http://192.168.1.102:8123 && echo 'HA reachable'
```

Verify at home:

```bash
kubectl -n wireguard exec deployment/wireguard-home -- wg show wg0
```

`latest handshake` should remain under roughly two minutes while the GL is
online, and transfer counters should increase during the TCP checks.

The configuration passed a physical GL power-cycle test on 2026-08-21:
`wg_home` started automatically, restored its handshake and split routes,
dnsmasq retained Pi-hole-first ordering and its 10,000-entry cache, Emby and
Home Assistant returned HTTP 200, and authenticated access to the Kubernetes
API at `192.168.1.174:6443` succeeded from a GL LAN client.

A physical WAN disconnect/reconnect test passed the same day. The Brovi DHCP
address and default route returned, WireGuard re-handshook without manual
action, Pi-hole blocking resumed, and Emby, Home Assistant, and authenticated
Kubernetes access all recovered.

WireGuard resolves `torok.go.ro` when the profile starts. If the home public
IP changes during a trip and the tunnel stops handshaking, stop/start the GL
profile to resolve the new address.

### Automatic recovery after an upstream Wi-Fi change

WireGuard has no connected/disconnected process: OpenWrt considers `wg_home`
up whenever its local interface is configured, even if the peer has stopped
handshaking. Normally WireGuard recovers automatically after the WAN path
changes. On 2026-08-27, however, `wg_home` remained locally up with correct
routes and endpoint DNS while receiving no handshake replies for 7.5 hours;
restarting only that interface restored the tunnel immediately.

The GL therefore runs `scripts/gl-wireguard-watchdog.sh` once per minute from
root's crontab:

```cron
* * * * * /root/gl-wireguard-watchdog.sh
```

The watchdog treats a handshake older than three minutes as stale, sends a
probe and waits five seconds for normal recovery, then restarts only `wg_home`
if it is still stale. Restarts are limited to once per ten minutes so a real
home outage cannot cause a tight loop. The 25-second keepalive makes the
three-minute threshold meaningful for this peer; do not reuse it unchanged on
an idle WireGuard profile without keepalive. Interventions are visible with:

```bash
logread -e gl-wireguard-watchdog
```

Install or refresh it from this repository while connected to the GL LAN:

```bash
scp scripts/gl-wireguard-watchdog.sh root@192.168.80.1:/root/gl-wireguard-watchdog.sh
ssh root@192.168.80.1 '
  chmod 0700 /root/gl-wireguard-watchdog.sh
  grep -qxF "* * * * * /root/gl-wireguard-watchdog.sh" /etc/crontabs/root ||
    echo "* * * * * /root/gl-wireguard-watchdog.sh" >>/etc/crontabs/root
  /etc/init.d/cron restart
'
```

After installation, exercise the recovery path without waiting for a real
outage. This bypasses only the pre-restart freshness checks; the normal
three-minute threshold still validates the recovered handshake:

```bash
ssh root@192.168.80.1 \
  'WG_HOME_FORCE_RESTART=true WG_HOME_COOLDOWN=0 /root/gl-wireguard-watchdog.sh'
```

## Replacement and configuration backup

The home-side manifests, key/profile preparation helper, watchdog, and rebuild
instructions are source-controlled here. The GL's live UCI configuration is
not: `/etc/config/network` contains the client private key, and the router also
stores Wi-Fi credentials and other secrets. Never commit a raw GL configuration
backup or UCI export.

On firmware 4.8.1, the built-in `sysupgrade` backup covers the relevant UCI
network, firewall, DHCP/DNS, and wireless files, root's crontab, and SSH keys.
It does not cover `/root/gl-wireguard-watchdog.sh`; reinstall that file from
this repository after restoring the backup. Keep a current GL backup encrypted
and off the router. Restore it only to the same model and preferably the same
firmware version, then validate the settings in this runbook before relying on
the tunnel.

Without that encrypted backup or the original mode-`0600` `gl-home.conf`, a
replacement cannot recover the GL private key from the home-side Kubernetes
Secret: the server stores only the GL public key. Generate a new GL key pair
and update both sides as a controlled key rotation instead.

## Pi-hole through the GL DNS cache

The old DHCP configuration handed clients `192.168.1.202` directly. That
bypassed the GL's dnsmasq cache. Change the GL so clients query the router,
then make Pi-hole the router's upstream:

1. Open **Network → DNS**.
2. Select **DNS Proxy** and set the proxy server to
   **`10.43.252.171#53`**. This is the primary Pi-hole reached through
   WireGuard. The in-cluster address avoids Pi-hole's Local-policy MetalLB VIP,
   which rejects cross-node traffic from the WireGuard pod.
3. Enable **Override DNS Settings for All Clients**. Remove any LAN DHCP option
   that still advertises `192.168.1.202` directly.
4. In LuCI/SSH, make the dnsmasq behavior explicit. Pi-hole is primary;
   Cloudflare is used only after Pi-hole fails. The domain-specific public
   rule is essential: otherwise a reboot can deadlock because WireGuard needs
   DNS to resolve `torok.go.ro`, while Pi-hole needs WireGuard to be up.

   ```bash
   uci set dhcp.@dnsmasq[0].noresolv='1'
   uci set dhcp.@dnsmasq[0].strictorder='1'
   uci set dhcp.@dnsmasq[0].cachesize='10000'
   uci -q delete dhcp.@dnsmasq[0].server
   uci add_list dhcp.@dnsmasq[0].server='/torok.go.ro/1.1.1.1'
   uci add_list dhcp.@dnsmasq[0].server='1.1.1.1'
   uci add_list dhcp.@dnsmasq[0].server='10.43.252.171'
   uci commit dhcp
   /etc/init.d/dnsmasq restart
   ```

   This GL firmware builds dnsmasq's runtime server list in reverse UCI
   declaration order. The apparently reversed `1.1.1.1` then Pi-hole entries
   above are intentional. After restart, `logread -e dnsmasq` must list
   `10.43.252.171` before generic `1.1.1.1`. A live check on 2026-08-21 showed
   that declaring Pi-hole first caused public DNS to win despite
   `strict-order`.

Check the effective setup while connected to the GL LAN (replace `.80.1` with
`.9.1` if the GL renumbered itself):

```bash
uci get dhcp.@dnsmasq[0].cachesize
uci get dhcp.@dnsmasq[0].strictorder
uci show dhcp.@dnsmasq[0] | grep '\.server='
ps w | grep '[d]nsmasq'
nslookup example.com 192.168.80.1
nslookup example.com 192.168.80.1
```

The second lookup should be served from dnsmasq's cache. Confirm in Pi-hole's
query log that normal uncached requests arrive there. Then stop WireGuard and
look up a new public name: after the failed Pi-hole attempt, strict ordering
must fall back to `1.1.1.1`. This prevents the multi-minute DNS freeze while
keeping Pi-hole as the normal resolver. Once the GL is online, also check
`dnsmasq --help` for `--use-stale-cache`; enable it only if the installed
firmware supports and persists that option.

## Cleanup after cutover

On the GL:

- disable the Tailscale service at boot and stop it;
- remove its `* * * * * /etc/ensure-home-routes.sh` cron entry;
- remove the Tailscale wait/route block from `/etc/rc.local` and the
  `postrouting_tailscale0_rule` MASQUERADE addition from `/etc/firewall.user`;
- remove the `tailscale`, `gl-sdk4-tailscale`, and
  `gl-sdk4-ui-tailscaleview` packages;
- securely remove any loose copy of `gl-home.conf` after backing up the GL.

The 2026-08-21 cutover retained a mode-`0600` rollback archive and retired
state only under `/root/`; no active package, init link, process, interface,
route, cron command, boot hook, firewall hook, or `/etc/config/tailscale`
remains.

At home, confirm ArgoCD pruned the old Application and namespace:

```bash
kubectl -n argocd get application tailscale
kubectl get namespace tailscale
```

Both commands should return `NotFound`. Remove the old Tailscale machine from
the Tailscale admin console after confirming no other device depends on it.

## HA validation

Validate failover during a maintenance window without deleting the pod or
node. Cordon and drain only with the normal node-maintenance runbook, then
confirm:

```bash
kubectl -n wireguard get pod -o wide
kubectl -n wireguard get service wireguard-home -o wide
kubectl -n wireguard exec deployment/wireguard-home -- wg show wg0
```

The pod must be Ready on a different node, the service must retain
`192.168.1.208`, and the GL must establish a fresh handshake. Uncordon buksi;
the scheduler does not migrate a healthy running pod back merely because the
preferred node returned. Recreate the pod during a maintenance window if you
want to restore buksi co-location.
