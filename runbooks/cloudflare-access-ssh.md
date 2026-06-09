# SSH access via Cloudflare Access

Off-LAN access to homelab nodes through Cloudflare Tunnel + Cloudflare
Access. No open ports, no VPN. Authentication gated by Cloudflare
(Google login), then standard SSH on top.

## Connect

```bash
ssh -o ProxyCommand="cloudflared access tcp --hostname=%h" core@ssh.newjoy.ro
```

First run opens a browser for Cloudflare Access (Google login).
Subsequent connections within the 24h Access session are silent.

For a permanent alias, add to `~/.ssh/config`:

```
Host ssh.newjoy.ro
    User core
    ProxyCommand cloudflared access tcp --hostname=%h
```

Then just `ssh ssh.newjoy.ro` from anywhere.

## How it works

```
local ssh ─► cloudflared (local CLI) ─► CF edge ─► cloudflared (k8s pod) ─► 192.168.1.174:22
                       │
                  CF Access auth
                  (Google login)
```

`cloudflared access tcp` opens a TCP stream from the workstation to
the cluster, authenticated via Cloudflare Access. The local SSH
client speaks SSH over that stream, using your normal keys, agent,
and `~/.ssh/config`. The private key never leaves the workstation.

## What's set up

### Cluster side (in this repo)

`config/cloudflare-tunnel/manifests/configmap.yaml` ingress rule
routes `ssh.newjoy.ro` to `192.168.1.174:22` (buksi) before the
catch-all that hands everything else to ingress-nginx. Reloader
restarts the cloudflared pods when this configmap changes.

### Cloudflare dashboard (one-time, manual)

- **Zero Trust → Access controls → Applications:** `SSH (homelab
  nodes)`, hostname `ssh.newjoy.ro`, type "self-hosted and private"
- **Policy:** Allow rule with `Emails` selector → `alpar.torok@elastic.co`
- **Identity provider:** Google (same as argocd.newjoy.ro)
- **DNS:** no per-host record needed; covered by the existing
  wildcard CNAME `*.newjoy.ro → <tunnel>.cfargotunnel.com`

## Workstation prerequisites

One-time install:

```bash
brew install cloudflared        # macOS
```

That's it. No Cloudflare login required up front — the browser pop
happens on first SSH attempt.

## Gotchas

- **Use `cloudflared access tcp`, not `cloudflared access ssh`.** The
  older `ssh` subcommand was consolidated into `tcp` in 2026
  cloudflared builds and is no longer available.
- **The cluster cloudflared runs in local-config mode** (`--config
  /etc/cloudflared/config/config.yaml` in the args). This means any
  "Public hostnames" you configure on the tunnel via the Cloudflare
  dashboard are silently ignored — all routing has to go through the
  configmap in this repo.
- **Ingress rule order matters.** The `ssh.newjoy.ro` rule must stay
  BEFORE the catch-all `service: http://ingress-nginx-controller...`
  rule, since cloudflared evaluates ingress rules top-down.
- **Cloudflare's browser-rendered SSH is finicky.** It rejects most
  modern OpenSSH private key formats with `Wrong passphrase or
  invalid/unrecognized private key file format`. Use the CLI
  ProxyCommand approach above instead.
- **Tunnel only terminates at buksi.** To reach pamacs (192.168.1.173)
  or pufi (192.168.1.166), SSH to buksi first and hop. If buksi is
  down, update the configmap to point at another node and re-sync.

## Once you're on the node

```bash
kubectl get nodes
kubectl create secret ...
# ... any other bootstrap work
```

(k3s' kubectl wrapper picks up `/etc/rancher/k3s/k3s.yaml`
automatically, no sudo or KUBECONFIG env needed for the `core` user.)
