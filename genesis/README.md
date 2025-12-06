# Genesis - Kubernetes Cluster on Odroid HC4

Install and manage a 3-node highly-available Kubernetes cluster on Odroid HC4 nodes using Fedora CoreOS and k3s.

## Overview

This setup creates a production-grade Kubernetes cluster on low-power x86_64 hardware:
- **3 Odroid HC4 nodes** - Each runs control plane + workloads
- **Fedora CoreOS** - Immutable, container-focused OS
- **k3s** - Lightweight Kubernetes distribution
- **Installed to NVMe** - Fast boot, independent operation
- **Longhorn storage** - Uses HDDs for persistent volumes

## Architecture

```
3x Odroid HC4 Nodes
├── NVMe SSD: CoreOS + k3s + etcd
├── HDD1: Longhorn storage
└── HDD2: Longhorn storage

Network:
├── eth0 (Management VLAN): SSH, k3s API, general traffic
└── eth1 (Storage VLAN): Longhorn replication & I/O

All 3 nodes = Control Plane + Worker
Can lose 1 node and cluster stays up
Dedicated storage network for optimal I/O performance
```

## What You Need

### Hardware
- 3x Odroid HC4 Plus/Ultra
- Each with: 4GB RAM, 1 NVMe SSD (boot), 2 SATA HDDs (storage)
- USB drive (4GB+) for installation
- Keyboard + HDMI monitor (for initial setup)

### Software
- Mac with the following tools:
  - `butane` - Generate ignition configs (brew install butane)
  - `jq` - Parse JSON metadata (brew install jq)
  - `python3` - HTTP server for ignition configs (brew install python3)
  - `kubectl` - Manage cluster (brew install kubectl)
- Run `./setup.sh` to check all prerequisites
- SSH key at `~/.ssh/id_ed25519` (generate with `ssh-keygen -t ed25519`)
- Network with DHCP on both VLANs

## Quick Start

**Prerequisites:** 
- Configure your switch with two VLANs (management + storage)
- Have an SSH key at `~/.ssh/id_ed25519` (generate with `ssh-keygen -t ed25519`)

```bash
cd genesis

# 1. Download CoreOS ISO (once, reuse for all nodes)
./download-coreos.sh

# 2. Create USB installer (once, reuse for all nodes)
./create-usb-installer.sh

# 3. Generate ignition configs for all nodes
export CLUSTER_NAME=baxter
./generate-ignition.sh odroid-1
./generate-ignition.sh odroid-2
./generate-ignition.sh odroid-3

# 4. Start HTTP server (keep running during installation)
python3 -m http.server 8080
# Get your Mac's IP: ipconfig getifaddr en0

# 5. For each node:
#    - Boot from USB (keyboard + monitor needed)
#    - Login as 'core' (no password)
#    - Run: sudo coreos-installer install /dev/nvme0n1 \
#           --ignition-url http://YOUR_MAC_IP:8080/ignition-odroid-1.json
#    - Remove USB and reboot

# 6. Bootstrap k3s cluster (after all nodes installed)
./bootstrap-cluster.sh

# 7. Access your cluster
export KUBECONFIG=$(pwd)/kubeconfig
kubectl get nodes

# All nodes respond to baxter.local (round-robin)
# Individual nodes: odroid-1.local, odroid-2.local, odroid-3.local
```

**Note:** Simple HTTP server method - no need for coreos-installer on your Mac!

## Detailed Setup

### Step 1: Download Fedora CoreOS

```bash
cd genesis
./download-coreos.sh
```

This downloads the x86_64 (AMD64) CoreOS live ISO (~1GB). The ISO supports ignition embedding for automated installation.

### Step 2: Create USB Installer

```bash
./create-usb-installer.sh
```

This writes the CoreOS live ISO to a USB drive. **You can reuse this same USB for all three nodes** - no per-node customization needed.

### Step 3: Generate Ignition Configs

```bash
export CLUSTER_NAME=baxter  # All nodes will respond to baxter.local

./generate-ignition.sh odroid-1
./generate-ignition.sh odroid-2
./generate-ignition.sh odroid-3
```

This creates `ignition-odroid-1.json`, `ignition-odroid-2.json`, `ignition-odroid-3.json` with your SSH key and node-specific configuration.

### Step 3b: Start HTTP Server

The CoreOS installer will fetch ignition configs over HTTP during installation:

```bash
# In the genesis directory, start HTTP server
python3 -m http.server 8080
```

**Keep this terminal open** while installing nodes.

**Find your Mac's IP address:**
```bash
# For WiFi (en0)
ipconfig getifaddr en0

# For Ethernet (en1)  
ipconfig getifaddr en1
```

Note this IP - you'll need it during installation (e.g., `192.168.1.100`).

### Step 4: Install First Node

1. **Insert USB** into Odroid HC4
2. **Connect keyboard + HDMI monitor**
3. **Power on** and boot from USB
4. **Login as `core`** at the prompt (no password required on live ISO)
5. **Install to NVMe with ignition:**

```bash
# Identify disks (optional but recommended)
lsblk

# You should see:
# NAME        SIZE TYPE
# sda           8G disk  (USB installer)
# nvme0n1       2T disk  (your NVMe SSD - install here!)
# sdb         400G disk  (HDD 1 - for Longhorn)
# sdc         4.0T disk  (HDD 2 - for Longhorn)

# Install CoreOS to NVMe with ignition config
# Replace 192.168.1.100 with YOUR Mac's IP address
sudo coreos-installer install /dev/nvme0n1 \
  --ignition-url http://192.168.1.100:8080/ignition-odroid-1.json

# This takes ~2-5 minutes
# - Downloads CoreOS (~800MB)
# - Fetches your ignition config from Mac
# - Installs to NVMe with config applied
```

6. **Remove USB and reboot:**

```bash
sudo systemctl reboot
```

7. Wait ~1-2 minutes for the node to boot from NVMe

### Step 5: Verify First Node

After the node reboots from NVMe:

```bash
# SSH into the node via .local address (mDNS)
ssh core@odroid-1.local

# Check both network interfaces
ip addr show

# Check k3s is running
sudo systemctl status k3s

# Check disks
lsblk
```

The node is ready!

### Step 6: Repeat for Other Nodes

For each additional node (odroid-2, odroid-3):

1. **Use the same USB** (no need to recreate it)
2. **Boot Odroid from USB**
3. **Login as `core`**
4. **Run install command** with the correct ignition file:

```bash
# For odroid-2:
sudo coreos-installer install /dev/nvme0n1 \
  --ignition-url http://192.168.1.100:8080/ignition-odroid-2.json

# For odroid-3:
sudo coreos-installer install /dev/nvme0n1 \
  --ignition-url http://192.168.1.100:8080/ignition-odroid-3.json
```

5. **Remove USB and reboot**

The HTTP server continues serving all ignition configs - just use the correct URL for each node.

### Step 7: Configure Your Network Switch

**Before bootstrapping the cluster, configure your switch with VLANs:**

1. **Create two VLANs:**
   - VLAN 1 (or your management VLAN): For eth0 - management traffic
   - VLAN 10 (or your storage VLAN): For eth1 - storage traffic

2. **Configure switch ports for each Odroid:**
   - Port 1 (eth0): Access mode or trunk with management VLAN
   - Port 2 (eth1): Access mode or trunk with storage VLAN

3. **Configure DHCP servers:**
   - DHCP on management VLAN (with internet gateway)
   - DHCP on storage VLAN (local only, no gateway needed)

4. **Optional: Reserve IPs in DHCP:**
   - Makes node IPs predictable after reboot
   - Reserve based on MAC addresses

### Step 8: Using .local Addresses

**Using .local addresses:**
- **Individual nodes:** `odroid-1.local`, `odroid-2.local`, `odroid-3.local`
- **Cluster-wide:** `baxter.local` (or your `CLUSTER_NAME.local`) resolves to all 3 nodes for round-robin access
- No need to track DHCP-assigned IPs
- Works automatically via mDNS/Avahi
- Your Mac natively supports .local resolution

**Round-robin access examples:**
```bash
# SSH to any node via cluster name (round-robin)
ssh -i ~/.ssh/id_ed25519 core@baxter.local

# Kubectl via cluster name
kubectl config set-cluster default --server=https://baxter.local:6443

# Access ingress via cluster name
curl http://baxter.local
```

**Important:** Note both IPs for each node (for Longhorn storage network config):
- Management IP (eth0): Auto-discovered via .local, used for SSH, kubectl
- Storage IP (eth1): Used for Longhorn configuration (query via SSH)

### Step 9: Bootstrap k3s Cluster

After all 3 nodes are installed and running:

```bash
# Bootstrap the cluster using .local addresses
./bootstrap-cluster.sh

# Automatically uses:
# - odroid-1.local
# - odroid-2.local
# - odroid-3.local
```

This script:
- Initializes k3s on first node
- Joins other nodes to create HA cluster
- Fetches and configures kubeconfig
- Sets up kubectl access

### Step 10: Verify Cluster

The bootstrap script fetched the kubeconfig, so just verify:

```bash
# Use the kubeconfig from bootstrap
export KUBECONFIG=$(pwd)/kubeconfig

# Check all nodes are ready
kubectl get nodes -o wide

# You should see all 3 nodes
# All nodes accessible via .local: odroid-1.local, odroid-2.local, odroid-3.local
# Cluster also accessible via: baxter.local (round-robin)

# Check system pods
kubectl get pods -A
```

### Step 11: Install Argo CD

Install Argo CD to manage the cluster via GitOps:

```bash
# Install Argo CD
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Wait for Argo CD to be ready
kubectl wait --for=condition=available --timeout=300s deployment/argocd-server -n argocd

# Get admin password
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d

# Access Argo CD UI
kubectl port-forward svc/argocd-server -n argocd 8080:443
# Open https://localhost:8080 (username: admin)
```

See "GitOps Setup Guide" section below for configuring your Git repository in Argo CD.

## Storage Configuration

Each Odroid HC4 has:

```
/dev/nvme0n1 (NVMe SSD 2TB)
├── CoreOS (~10GB)
├── k3s + etcd (~5GB)
└── Remaining (~1.985TB) - Available for Longhorn if needed

/dev/sdb (HDD 400GB)
└── Longhorn storage (primary use)

/dev/sdc (HDD 4TB)
└── Longhorn storage (primary use)
```

**Total cluster storage:** ~13TB raw (varies with Longhorn replication)

## Network Configuration

Each HC4 has two Gigabit Ethernet ports configured for different VLANs:

### Dual-Network Architecture

**eth0 - Management Network (VLAN: your management VLAN)**
- Purpose: SSH access, k3s API server, kubectl traffic, general cluster communication
- Configuration: DHCP (IPv4 + IPv6)
- Priority: 100 (primary interface)
- Example subnet: 192.168.1.0/24

**eth1 - Storage Network (VLAN: your storage VLAN)**
- Purpose: Longhorn replication traffic, storage I/O, pod volume mounts
- Configuration: DHCP (IPv4 + IPv6)
- Priority: 90
- Example subnet: 192.168.42.0/24

### Why Separate Networks?

**Performance:**
- Isolates storage I/O from general traffic
- Prevents storage traffic from saturating management network
- Dedicated bandwidth for Longhorn replication (3-way by default)

**Security:**
- Storage network can be isolated/firewalled
- Reduces attack surface on management network
- Can implement different QoS policies

**Scalability:**
- Storage traffic grows independently from management
- Can use different network infrastructure (switches, VLANs)
- Easier to troubleshoot network issues

### Network Requirements

**Switch Configuration:**
- Configure trunk ports or access ports for respective VLANs
- Management VLAN on port for eth0
- Storage VLAN on port for eth1
- Both ports support 1Gbps

**Router/DHCP Server:**
- DHCP server on both VLANs
- Optional: Reserve IPs based on MAC addresses for consistency
- DNS resolution for management IPs
- Storage network typically doesn't need internet access

**Recommended Subnets:**
```
Management Network (eth0):
- Subnet: 192.168.1.0/24
- Gateway: 192.168.1.1
- DHCP range: 192.168.1.100-192.168.1.200
- Odroid IPs: 192.168.1.10-12 (reserved)

Storage Network (eth1):
- Subnet: 192.168.42.0/24
- No gateway needed (local traffic only)
- DHCP range: 192.168.42.100-192.168.42.200
- Odroid IPs: 192.168.42.10-12 (reserved)
```

### Configuring Longhorn for Storage Network

After installing Longhorn, you need to tell it to use eth1 (storage network) for all storage traffic.

**Method 1: Via Longhorn Settings (UI)**

1. Access Longhorn UI:
```bash
   kubectl port-forward -n longhorn-system svc/longhorn-frontend 8080:80
   ```
   Open http://localhost:8080

2. Go to **Settings** → **General**

3. Find **Longhorn Storage Network** setting

4. Get storage network IPs for all nodes:
   ```bash
   # SSH to each node via management network
   ssh -i ~/.ssh/id_ed25519 core@odroid-1.local
   /usr/local/bin/get-storage-ip  # Shows eth1 IP, e.g., 192.168.42.10
   ```

5. Set **Storage Network CIDR** to your storage subnet, e.g., `192.168.42.0/24`

**Method 2: Via kubectl (Recommended)**

```bash
# Set storage network CIDR
kubectl patch -n longhorn-system settings.longhorn.io/storage-network \
  --type='json' \
  -p='[{"op": "replace", "path": "/value", "value":"192.168.42.0/24"}]'

# Verify
kubectl get settings.longhorn.io -n longhorn-system storage-network -o yaml
```

**Verification:**
```bash
# Check Longhorn is using storage network
kubectl get pods -n longhorn-system -o wide
# Pod IPs should be from storage network (192.168.42.x)

# Monitor storage traffic
ssh -i ~/.ssh/id_ed25519 core@odroid-1.local
sudo iftop -i eth1  # Should see Longhorn traffic between nodes
```

## Day-to-Day Operations

### Check Cluster Health

```bash
# Check nodes
kubectl get nodes

# Check all pods
kubectl get pods -A

# Check k3s service on a node
ssh -i ~/.ssh/id_ed25519 core@odroid-1.local sudo systemctl status k3s
```

### Update CoreOS

CoreOS updates automatically via Zincati. To check status:

```bash
ssh -i ~/.ssh/id_ed25519 core@odroid-1.local
systemctl status zincati
```

### Reboot a Node

```bash
ssh -i ~/.ssh/id_ed25519 core@odroid-1.local sudo systemctl reboot

# Node reboots, cluster stays up (HA!)
# Wait ~2 minutes for node to rejoin
```

### View Logs

```bash
# k3s logs on a node
ssh -i ~/.ssh/id_ed25519 core@odroid-1.local sudo journalctl -u k3s -f

# Kubernetes pod logs
kubectl logs -n kube-system <pod-name>
```

### Upgrade k3s

Update the k3s version in `ignition-template.yaml` and regenerate configs, or:

```bash
# On each node
ssh -i ~/.ssh/id_ed25519 core@odroid-1.local
sudo systemctl stop k3s
sudo /usr/local/bin/install-k3s.sh
sudo systemctl start k3s
```

## Troubleshooting

### Node Won't Boot After Installation

1. Check BIOS boot order (NVMe should be first)
2. Boot from USB installer again and check with `lsblk`
3. Verify installation with `coreos-installer list` on USB

### Can't SSH to Node

1. **Check management network (eth0):**
   - Verify cable connected to correct VLAN/port
   - Check router DHCP for management VLAN
   - Verify switch port configuration for management VLAN

2. **Verify ignition config has correct SSH key:**
   ```bash
   cat ignition-odroid-1.json | grep -A 2 ssh_authorized_keys
   ```

3. **Check console for IP addresses** (connect HDMI + keyboard):
   ```bash
   ip addr show
   # Should see both eth0 and eth1 with IPs from different subnets
   ```

4. **Test connectivity:**
   ```bash
   # From your Mac, ping management IP
   ping 192.168.1.10
   
   # SSH with verbose output
   ssh -vvv -i ~/.ssh/id_ed25519 core@192.168.1.10
   ```

5. **Verify VLAN configuration:**
   - Management VLAN has DHCP server
   - Management VLAN has route to internet (for SSH from your Mac)
   - Storage VLAN doesn't need internet access

### k3s Not Starting

```bash
ssh -i ~/.ssh/id_ed25519 core@odroid-1.local
sudo journalctl -u k3s -n 100
```

Common issues:
- Port 6443 already in use
- Network configuration problem
- Disk space issue

### Longhorn Not Detecting Disks

Disks must be:
- Unformatted (no filesystem)
- Not mounted
- No partition table

To wipe a disk:
```bash
ssh -i ~/.ssh/id_ed25519 core@odroid-1.local
sudo wipefs -a /dev/sdb
sudo wipefs -a /dev/sdc
```

### Storage Network Issues

**Longhorn pods not communicating:**

1. **Verify storage network IPs on all nodes:**
```bash
   # Check each node
   for node in odroid-1.local odroid-2.local odroid-3.local; do
     echo "Node $node:"
     ssh -i ~/.ssh/id_ed25519 core@$node "/usr/local/bin/get-storage-ip"
   done
   ```

2. **Test connectivity between storage IPs:**
   ```bash
   # From one node, ping another node's storage IP
   ssh -i ~/.ssh/id_ed25519 core@odroid-1.local
   ping 192.168.42.11  # Should work
   ```

3. **Verify Longhorn is using storage network:**
   ```bash
   kubectl get settings.longhorn.io -n longhorn-system storage-network -o yaml
   # Should show your storage CIDR (192.168.42.0/24)
   ```

4. **Check storage VLAN configuration:**
   - Verify switch ports for eth1 are on storage VLAN
   - Check DHCP is assigning IPs on storage subnet
   - Ensure no firewall blocking traffic between storage IPs

5. **Monitor storage network traffic:**
```bash
   # On any node
   ssh -i ~/.ssh/id_ed25519 core@odroid-1.local
   sudo iftop -i eth1
   # Should see traffic between nodes during volume operations
   ```

## GitOps Setup Guide

After installing Argo CD (Step 11), configure it to sync from the [homelab repository](https://github.com/alpar-t/homelab).

### Access Argo CD

```bash
# Port-forward to access the UI
kubectl port-forward svc/argocd-server -n argocd 8080:443

# Get admin password
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
```

Open https://localhost:8080 and login with username `admin`.

### Connect the Repository

In the Argo CD UI:

1. Go to **Settings** → **Repositories**
2. Click **Connect Repo**
3. Choose **Via HTTPS** (for public repo) or **Via SSH** (for private)
4. Enter repository URL: `https://github.com/alpar-t/homelab`
5. Click **Connect**

Or via CLI:

```bash
# Login to Argo CD CLI
argocd login localhost:8080 --insecure

# Add the repository
argocd repo add https://github.com/alpar-t/homelab
```

### Create the Root Application

Apply the root application from the repo root. This bootstraps ArgoCD to manage all applications defined in the `apps/` directory:

```bash
kubectl apply -f ../root-application.yaml
```

### Verify Sync

```bash
# Check application status
kubectl get applications -n argocd

# Watch sync progress
argocd app get homelab
```

Argo CD will now automatically deploy any Applications defined in the `apps/` directory of the homelab repo. Changes pushed to the repo sync within 3 minutes (or manually with `argocd app sync homelab`).


## Why CoreOS + k3s?

**vs Talos:**
- ✅ Better hardware compatibility (works with HC4)
- ✅ Familiar tooling (SSH, systemd)
- ✅ Easier to troubleshoot
- ✅ Still immutable and container-focused
- ✅ Automatic updates

**vs Ubuntu + k3s:**
- ✅ Immutable OS (no configuration drift)
- ✅ Atomic updates
- ✅ Minimal attack surface
- ✅ Container-native design
- ✅ Smaller footprint

## Backup Strategy

**Critical data to backup:**

1. **Git Repository**: The homelab repo is already backed up by GitHub
2. **Kubeconfig**: `genesis/kubeconfig` file (for emergency access)
3. **Argo CD Secrets**: Backup repository credentials if using private repos

**Disaster recovery:**
- Rebuild cluster from genesis scripts
- Install Argo CD (Step 11)
- Connect to homelab repo → entire cluster rebuilds automatically

## Next Steps

1. **Add applications to the homelab repo** in the `apps/` directory
2. **Set up Argo CD notifications** (Slack/Discord for sync status)
3. **Enable Argo CD SSO** (GitHub/GitLab/OIDC)

## Resources

### Platform Documentation
- [Fedora CoreOS Documentation](https://docs.fedoraproject.org/en-US/fedora-coreos/)
- [k3s Documentation](https://docs.k3s.io/)
- [Odroid HC4 Wiki](https://wiki.odroid.com/odroid-hc4/odroid-hc4)

### GitOps
- [Argo CD Documentation](https://argo-cd.readthedocs.io/)
- [Argo CD Best Practices](https://argo-cd.readthedocs.io/en/stable/user-guide/best_practices/)
- [GitOps Principles](https://opengitops.dev/)
