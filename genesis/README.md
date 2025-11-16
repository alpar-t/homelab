# Genesis - Talos Kubernetes Cluster on Odroids

Install and manage a 3-node highly-available Kubernetes cluster on Odroid nodes using Talos Linux.

## Overview

This setup creates a production-grade Kubernetes cluster on low-power ARM hardware:
- **3 Odroid nodes** - Each runs control plane + workloads
- **Talos Linux** - Immutable OS designed for Kubernetes
- **Installed to SSD** - Fast boot, independent operation
- **Longhorn storage** - Uses HDDs for persistent volumes

## Architecture

```
3x Odroid Nodes
├── SSD: Talos OS + etcd + system
├── HDD1: Longhorn storage
└── HDD2: Longhorn storage

All 3 nodes = Control Plane + Worker
Can lose 1 node and cluster stays up
```

## What You Need

### Hardware
- 3x Odroid nodes (N2+, HC4, M1)
- Each with: 2GB+ RAM, 1 SSD (boot), 2 HDDs (storage)
- USB drive (8GB+) for installation
- Keyboard + HDMI monitor (for initial setup)

### Software
- Mac with `talosctl` installed
- USB drive creator script (included)

## Quick Start

```bash
# 1. Create USB installer
./create-usb-installer.sh

# 2. Boot each Odroid from USB and install

# 3. Generate cluster config
talosctl gen config mycluster https://192.168.1.10:6443

# 4. Apply config to each node

# 5. Bootstrap cluster
talosctl bootstrap --nodes 192.168.1.10
```

## Detailed Setup

### Step 1: Install talosctl on Mac

```bash
brew install siderolabs/tap/talosctl
```

### Step 2: Create USB Installation Media

```bash
cd genesis
chmod +x create-usb-installer.sh
./create-usb-installer.sh
```

Follow prompts to:
- Select USB drive
- Download Talos installer
- Write to USB

**Note:** This creates a bootable USB that will install Talos to the Odroid's SSD.

### Step 3: Prepare Odroid Storage

For each Odroid, you need:
- **SSD** - Will hold Talos OS (we'll install here)
- **2x HDD** - Will be used by Longhorn (leave empty)

Check your disk names (usually):
- SSD: `/dev/mmcblk0` or `/dev/sda`
- HDD1: `/dev/sdb`
- HDD2: `/dev/sdc`

### Step 4: Install Talos on First Odroid

1. **Insert USB** into Odroid
2. **Connect keyboard + HDMI**
3. **Power on** and enter BIOS (Del or F2)
4. **Set boot order**: USB first
5. **Save and reboot**

Odroid will boot Talos installer from USB.

6. **Install to SSD:**

```bash
# At the Talos console, install to SSD
# Replace /dev/sda with your actual SSD device
talosctl install \
  --nodes 192.168.1.10 \
  --disk /dev/sda \
  --insecure
```

Wait for installation to complete (~2 minutes).

7. **Power off**, remove USB, power on
8. Odroid boots from SSD now

**Repeat for other 2 Odroids** (use IPs .11 and .12)

### Step 5: Set Static IPs (Optional but Recommended)

Configure your router to give each Odroid a static IP:
- Odroid 1: 192.168.1.10
- Odroid 2: 192.168.1.11
- Odroid 3: 192.168.1.12

Or configure in Talos (see configuration section).

### Step 6: Generate Talos Configuration

```bash
# Generate configuration for 3-node HA cluster
talosctl gen config mycluster https://192.168.1.10:6443 \
  --output-dir talos-config/

# This creates:
# - controlplane.yaml (for all 3 nodes)
# - talosconfig (for talosctl CLI)
```

### Step 7: Customize Configuration for Your Setup

Edit `talos-config/controlplane.yaml`:

#### A. Configure Longhorn Storage

```yaml
machine:
  kubelet:
    extraMounts:
      - destination: /var/lib/longhorn
        type: bind
        source: /var/lib/longhorn
        options:
          - bind
          - rshared
          - rw
  sysctls:
    vm.max_map_count: "262144"
```

#### B. Configure Network (Optional)

```yaml
machine:
  network:
    hostname: odroid-1  # Change per node
    interfaces:
      - interface: eth0
        dhcp: true
        # Or static:
        # addresses:
        #   - 192.168.1.10/24
        # gateway: 192.168.1.1
        # nameservers:
        #   - 8.8.8.8
```

#### C. Configure Install Disk

```yaml
machine:
  install:
    disk: /dev/sda  # Your SSD device
    wipe: false     # Already installed
```

### Step 8: Apply Configuration to All Nodes

```bash
# Set up talosctl
export TALOSCONFIG=./talos-config/talosconfig

# Configure endpoints
talosctl config endpoint 192.168.1.10 192.168.1.11 192.168.1.12

# Apply config to each node
talosctl apply-config --nodes 192.168.1.10 --file talos-config/controlplane.yaml --insecure
talosctl apply-config --nodes 192.168.1.11 --file talos-config/controlplane.yaml --insecure
talosctl apply-config --nodes 192.168.1.12 --file talos-config/controlplane.yaml --insecure

# Wait ~2 minutes for nodes to apply config and reboot
```

### Step 9: Bootstrap Kubernetes Cluster

```bash
# Bootstrap etcd on first node
talosctl bootstrap --nodes 192.168.1.10

# Wait ~3 minutes for cluster to form
```

### Step 10: Get Kubeconfig and Verify

```bash
# Get kubeconfig
talosctl kubeconfig --nodes 192.168.1.10

# Check nodes
kubectl get nodes
# All 3 should show as Ready

# Check system pods
kubectl get pods -A
# All should be Running
```

### Step 11: Allow Workloads on Control Planes

```bash
# Remove taint so pods can run on all nodes
kubectl taint nodes --all node-role.kubernetes.io/control-plane-
```

### Step 12: Install Longhorn for Storage

```bash
# Install Longhorn
kubectl apply -f https://raw.githubusercontent.com/longhorn/longhorn/v1.6.0/deploy/longhorn.yaml

# Wait for Longhorn pods to start
kubectl get pods -n longhorn-system -w

# Once running, check Longhorn detects your HDDs
kubectl get nodes -o yaml | grep longhorn
```

## Storage Configuration

Each Odroid has 3 disks:

```
/dev/sda (SSD 256GB)
├── Talos OS (~2GB)
├── etcd/system (~8GB)
└── Available for pods (~246GB)

/dev/sdb (HDD 2TB)
└── Longhorn storage

/dev/sdc (HDD 2TB)
└── Longhorn storage
```

Longhorn will automatically discover and use `/dev/sdb` and `/dev/sdc`.

**Total cluster storage:** ~12TB (3 nodes × 2 HDDs × 2TB)

## Day-to-Day Operations

### Check Cluster Health

```bash
# Talos health
talosctl health --nodes 192.168.1.10,192.168.1.11,192.168.1.12

# Kubernetes nodes
kubectl get nodes

# All pods
kubectl get pods -A
```

### View Logs

```bash
# Talos system logs
talosctl logs --nodes 192.168.1.10 kubelet

# Kubernetes pod logs
kubectl logs -n kube-system <pod-name>
```

### Reboot a Node

```bash
talosctl reboot --nodes 192.168.1.10

# Node reboots, cluster stays up (HA!)
# Wait ~2 minutes for node to rejoin
```

### Upgrade Talos

```bash
# Upgrade one node at a time
talosctl upgrade --nodes 192.168.1.10 \
  --image ghcr.io/siderolabs/installer:v1.8.0

# Wait for node to come back, then upgrade next
talosctl upgrade --nodes 192.168.1.11 ...
talosctl upgrade --nodes 192.168.1.12 ...
```

### Reconfigure a Node

```bash
# Edit config
vim talos-config/controlplane.yaml

# Apply changes
talosctl apply-config --nodes 192.168.1.10 \
  --file talos-config/controlplane.yaml
```

## Troubleshooting

### Node Won't Boot After Installation

1. Check BIOS boot order (SSD first, not USB)
2. Verify Talos was installed: `talosctl disks --nodes <ip> --insecure`
3. Reinstall from USB if needed

### Can't Reach Node After Config Apply

1. Check network cable
2. Verify IP address: `talosctl get addresses --nodes <ip> --insecure`
3. Check router DHCP leases
4. Try insecure mode: `talosctl --nodes <ip> --insecure get members`

### Cluster Won't Bootstrap

```bash
# Check etcd status on all nodes
talosctl service etcd status --nodes 192.168.1.10
talosctl service etcd status --nodes 192.168.1.11
talosctl service etcd status --nodes 192.168.1.12

# Check logs
talosctl logs --nodes 192.168.1.10 etcd
```

### Longhorn Not Detecting Disks

```bash
# Check if HDDs are visible to Longhorn
kubectl get nodes -o yaml | grep longhorn

# Manually add disks if needed (see Longhorn docs)
```

## Why This Approach?

**vs Network Boot (PXE):**
- ✅ Simpler - no TFTP server needed
- ✅ Faster boot
- ✅ Cluster is independent
- ✅ Still easy to upgrade (talosctl)
- ✅ Can reinstall from USB if needed

**vs Traditional Linux + kubeadm:**
- ✅ Immutable OS (no configuration drift)
- ✅ Atomic updates
- ✅ API-driven (no SSH)
- ✅ Minimal attack surface
- ✅ Designed for Kubernetes

## Backup Strategy

**Critical data to backup:**
1. **Talos config**: `talos-config/` directory
2. **Kubeconfig**: `~/.kube/config`
3. **etcd snapshots**: via Talos or Velero
4. **Longhorn volumes**: Longhorn backup to S3/NFS

## Next Steps

1. Deploy your applications
2. Set up ingress controller (Traefik/Nginx)
3. Configure cert-manager for TLS
4. Set up monitoring (Prometheus/Grafana)
5. Configure backups (Velero)

## Resources

- [Talos Documentation](https://www.talos.dev/)
- [Longhorn Documentation](https://longhorn.io/docs/)
- [Kubernetes Documentation](https://kubernetes.io/docs/)
- [Odroid Wiki](https://wiki.odroid.com/)
