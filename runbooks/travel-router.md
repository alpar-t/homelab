# Travel router (GL.iNet GL-MT3000 / Beryl AX)

Portable router for travel + homelab failover. Joins the tailnet as
`gl-mt3000` (`100.96.142.22`) so remote devices reach the home
`192.168.1.0/24` through the home subnet router (`k8s-subnet-router`,
`100.115.237.20`). Background: CLAUDE.md → "Travel network / backup uplink".

## Access

The GL is at **`192.168.80.1`** on its own LAN (`br-lan`, `192.168.80.0/24`).
SSH as **root** with the default workstation key — no ssh-config alias, no
password:

```bash
ssh root@192.168.80.1        # OpenWrt/dropbear, root has full busybox shell
```

Notes on the box: OpenWrt-based, **busybox** userland — `ping` has no
fractional `-i`, **no `python3`**, no `lsusb`; use `iwinfo`, `logread`,
`ip`, and `tailscale` directly. LAN may renumber to `192.168.9.x` when the
Brovi LTE stick is the WAN (to dodge a subnet clash); the LAN base here is
`.80.x`.

## Uplink modes

- **WiFi repeater** (client): interface `apcli0` (2.4 GHz) / `apclix0`
  (5 GHz). Check the associated network + signal with:
  ```bash
  iwinfo apcli0 info      # ESSID, channel, Signal, Noise, bitrate
  ```
- **LTE**: Brovi E3372 USB stick as WAN. If plugged in it shows under
  `/sys/kernel/debug/usb/devices` (grep Manufacturer/Product) — busybox has
  no `lsusb`. If no Huawei/Brovi entry appears, **the stick is not
  connected** and the only uplink is WiFi.

## 2026-07-25 incident — Tailscale "stalls for minutes" while travelling

**Symptom**: remote/tailnet access via the GL froze for minutes at a time,
then recovered on its own.

**Root cause**: the **direct Tailscale path from the GL to home was
flapping**. The peer had a real direct path (`CurAddr 188.24.31.130:1091`,
home public IP) but its RTT oscillated between a healthy **~40 ms** and
**~2.7 s with 3/4 packets dropped**, re-handshaking repeatedly
(`LastHandshake` kept refreshing). During the bad windows the direct path
collapsed and DERP relay (Frankfurt/Warsaw, ~26 ms) didn't pick up fast
enough → multi-minute stall until the next successful handshake.

**Why it flapped**: the uplink was **hotel WiFi repeated on congested
2.4 GHz channel 6**, `Signal -63 dBm` against an abnormally high
`Noise -49 dBm` (~14 dB SNR). Intermittent UDP loss on that uplink breaks
the hole-punched direct path. The **Brovi LTE stick was not plugged in**, so
there was no alternate uplink. (5 GHz client `apclix0` was DOWN — 2.4 GHz
only.)

**Amplifier — tailnet DNS**: the tailnet global nameserver is the home
Pi-hole **`192.168.1.202`**, reachable only *through* this flaky tunnel. Any
tailnet device using tailnet DNS (`--accept-dns=true`, e.g. the iPhone) has
every lookup time out during a flap, turning a brief path wobble into
"everything is frozen." The GL itself is insulated — it runs
`--accept-dns=false`, so its own `nslookup` uses the local/hotel resolver
and kept working throughout.

**Not the cause** (ruled out): 100% ICMP loss to `192.168.1.254` and
`192.168.1.202` is expected — the hotel gateway drops ICMP, and the home
hosts were unreachable only during the flap windows. Internet from the GL
(`ping 1.1.1.1`) stayed at 0% loss / ~15 ms the whole time. CPU temp
(~63 °C), load, and memory were all fine.

### Diagnostics used

```bash
# uplink quality (the real culprit)
iwinfo apcli0 info                       # Signal/Noise/channel/bitrate
ip route; ip -s link show apcli0         # routes + iface errors/drops

# is the tunnel actually passing traffic RIGHT NOW?
tailscale ping -c 10 100.115.237.20      # flapping = timeouts then a slow pong
tailscale status --json | tr ',' '\n' \
  | grep -iE 'HostName|CurAddr|Relay|LastHandshake|Online'
tailscale netcheck                       # NAT type, nearest DERP, UDP:true

# NOTE: no local tailscaled logs. It runs
#   /usr/sbin/tailscaled --port 41641 --state /etc/tailscale/tailscaled.state
# with no --verbose and no logfile, so `logread` has nothing and there is no
# /tmp/tailscaled.log. Historical reconnect logs live only in Tailscale's
# cloud logtail / admin console, not on the box. `LastHandshake` refreshing
# to "now" is the on-box reconnect signal.
```

### Fixes / mitigations (in order of leverage)

1. **Better uplink.** Plug in the Brovi LTE stick (dedicated data, no hotel
   congestion) or point the WiFi client at the hotel **5 GHz** SSID instead
   of 2.4 GHz ch 6. Either stabilises the direct path and the stalls stop.
2. **Make DNS survive tunnel flaps.** Don't leave roaming devices pointed at
   `192.168.1.202`. Set `--accept-dns=false` on travel devices, or change
   the tailnet global nameserver to a public resolver (or one reachable via
   a `100.x` tailnet IP) so lookups don't depend on the home-subnet path.
3. **Latent risk — subnet collision.** The hotel LAN was also
   `192.168.1.0/24`, identical to home. Tailscale currently wins via /32
   host routes + a metric-0 `192.168.1.0/24 dev tailscale0`, so it wasn't
   the active fault, but it's fragile. If home hosts become reachable *only
   when* off the hotel WiFi, suspect this and renumber one side.
