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

### Step 11: Choose Your Management Approach

You have two options depending on whether you want GitOps from day 1:

#### Option A: GitOps with Argo CD (Recommended for Production)

**Install Argo CD first** (it doesn't need persistent storage):

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

**Then manage everything via Argo CD:**
1. Create a Git repo for your cluster config
2. Define Longhorn as an Argo Application
3. Add other applications (ingress, cert-manager, monitoring)
4. All changes go through Git PRs

See "GitOps Setup Guide" section below for details.

#### Option B: Manual Installation (Quick Start)

**Install Longhorn directly** (then optionally move to GitOps later):

```bash
# Install Longhorn
kubectl apply -f https://raw.githubusercontent.com/longhorn/longhorn/v1.7.2/deploy/longhorn.yaml

# Wait for pods to be ready
kubectl get pods -n longhorn-system -w
```

**Note:** You can still adopt this into Argo CD later (day 2 operation).

### Step 12: Configure Longhorn Storage

```bash
# Access Longhorn UI
kubectl port-forward -n longhorn-system svc/longhorn-frontend 8080:80
```

Open http://localhost:8080 and:
1. Go to **Node** tab
2. For each node, click **Edit node and disks**
3. Add SATA HDDs:
   - Path: `/dev/sdb`
   - Storage Reserved: 0GB
   - Click **Add Disk**
   - Repeat for `/dev/sdc`

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

## GitOps Setup Guide (Option A)

If you chose the GitOps approach (Argo CD first), here's how to set everything up.

### Prerequisites

- Argo CD installed (from Step 14)
- Git repository for your cluster configuration
- GitHub/GitLab account with SSH keys configured

### Repository Structure

Create a Git repository with this structure:

```
cluster-config/
├── apps/
│   ├── longhorn.yaml
│   ├── ingress-nginx.yaml
│   ├── cert-manager.yaml
│   └── monitoring.yaml
├── longhorn/
│   ├── kustomization.yaml
│   ├── values.yaml
│   └── storage-network-patch.yaml
├── ingress-nginx/
│   └── values.yaml
└── bootstrap/
    └── app-of-apps.yaml
```

### 1. Install Longhorn via Argo CD

Create `apps/longhorn.yaml`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: longhorn
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://charts.longhorn.io
    chart: longhorn
    targetRevision: 1.7.2
    helm:
      values: |
        defaultSettings:
          # Use storage network for Longhorn traffic
          storageNetwork: "192.168.42.0/24"
          replicaReplenishmentWaitInterval: 0
          defaultReplicaCount: 3
          
        persistence:
          defaultClass: true
          defaultClassReplicaCount: 3
          
        # Resource limits for production
        longhornManager:
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 512Mi
              
        longhornDriver:
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 200m
              memory: 256Mi
  
  destination:
    server: https://kubernetes.default.svc
    namespace: longhorn-system
  
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```

Apply it:

```bash
kubectl apply -f apps/longhorn.yaml
```

### 2. App of Apps Pattern

Create `bootstrap/app-of-apps.yaml` to manage all applications:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: cluster-apps
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/YOUR_USERNAME/cluster-config
    targetRevision: main
    path: apps
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

Apply the app-of-apps:

```bash
kubectl apply -f bootstrap/app-of-apps.yaml
```

Now Argo CD will automatically deploy everything defined in `apps/`.

### 3. Add Ingress Controller

Create `apps/ingress-nginx.yaml`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ingress-nginx
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://kubernetes.github.io/ingress-nginx
    chart: ingress-nginx
    targetRevision: 4.11.3
    helm:
      values: |
        controller:
          service:
            type: LoadBalancer
            # Use MetalLB or similar for bare metal
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
  destination:
    server: https://kubernetes.default.svc
    namespace: ingress-nginx
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

### 4. Access Argo CD via Ingress

Once ingress is set up, expose Argo CD:

```yaml
# ingress/argocd-ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: argocd-server
  namespace: argocd
  annotations:
    nginx.ingress.kubernetes.io/backend-protocol: "HTTPS"
    nginx.ingress.kubernetes.io/ssl-passthrough: "true"
spec:
  ingressClassName: nginx
  rules:
  - host: argocd.yourdomain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: argocd-server
            port:
              number: 443
```

### 5. Verify Argo CD is Managing Everything

```bash
# Check all applications
kubectl get applications -n argocd

# Check application status
argocd app list

# View application details
argocd app get longhorn

# Sync an application manually if needed
argocd app sync longhorn
```

### 6. Making Changes via GitOps

All changes now go through Git:

```bash
# Clone your repo
git clone git@github.com:YOUR_USERNAME/cluster-config.git
cd cluster-config

# Make changes
vim longhorn/values.yaml

# Commit and push
git add longhorn/values.yaml
git commit -m "Update Longhorn replica count to 2"
git push

# Argo CD automatically syncs within 3 minutes
# Or sync immediately:
argocd app sync longhorn
```

### 7. Disaster Recovery

If your cluster is destroyed, rebuild with:

```bash
# 1. Recreate cluster (CoreOS + k3s from genesis)
# 2. Install Argo CD
# 3. Apply app-of-apps
kubectl apply -f bootstrap/app-of-apps.yaml

# Everything rebuilds automatically from Git!
```

### Benefits of GitOps with Argo CD

✅ **Single Source of Truth**: All config in Git  
✅ **Audit Trail**: Every change has a commit  
✅ **Easy Rollback**: `git revert` + sync  
✅ **Disaster Recovery**: Rebuild from Git in minutes  
✅ **Team Collaboration**: Changes via PRs  
✅ **Drift Detection**: Argo alerts on manual changes  
✅ **Progressive Delivery**: Canary/blue-green deployments  

### Monitoring GitOps

```bash
# Install Argo CD CLI
brew install argocd

# Login
argocd login argocd.yourdomain.com

# Watch sync status
argocd app list -w

# View sync history
argocd app history longhorn

# Check health
argocd app get longhorn --show-operation
```

## Accessing Your Cluster

With a 3-node HA setup, you can access the cluster via **any node IP** for both kubectl and ingress traffic.

### kubectl Access (API Server)

All 3 nodes run the k3s API server on port 6443:

```bash
# Your kubeconfig already points to one node
export KUBECONFIG=$(pwd)/kubeconfig
kubectl get nodes

# You can switch between nodes if one is down:
kubectl config set-cluster default --server=https://192.168.1.11:6443
```

**For high availability**, consider:
- Using all 3 IPs with client-side failover
- Setting up a load balancer (HAProxy, nginx) in front of the API servers
- Using DNS round-robin with multiple A records

### Ingress Traffic (HTTP/HTTPS)

Your ingress controller (nginx or Traefik) runs on all nodes, so you can hit any IP:

#### Option 1: Direct Node Access (Simplest)

```bash
# Access your apps via any node IP
curl http://192.168.1.10
curl http://192.168.1.11  # Same result
curl http://192.168.1.12  # Same result
```

**Use case**: Development, quick testing

#### Option 2: DNS Round Robin (Simple Load Distribution)

Configure DNS with multiple A records:

```
# DNS configuration
app.yourdomain.com.  A  192.168.1.10
app.yourdomain.com.  A  192.168.1.11
app.yourdomain.com.  A  192.168.1.12
```

**Pros**: Single hostname, basic failover  
**Cons**: DNS caching, not true load balancing

#### Option 3: MetalLB with Virtual IP (Recommended)

Install MetalLB to get a **single floating IP** for ingress:

```yaml
# apps/metallb.yaml (via Argo CD)
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: metallb
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://metallb.github.io/metallb
    chart: metallb
    targetRevision: 0.14.9
    helm:
      values: |
        # MetalLB will manage IP allocation
  destination:
    server: https://kubernetes.default.svc
    namespace: metallb-system
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
---
# After MetalLB is installed, configure IP pool
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: default
  namespace: metallb-system
spec:
  addresses:
  - 192.168.1.100-192.168.1.110  # VIP range from management network
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: default
  namespace: metallb-system
spec:
  ipAddressPools:
  - default
```

Now your ingress gets a VIP:

```bash
kubectl get svc -n ingress-nginx
# NAME                       TYPE           EXTERNAL-IP      PORT(S)
# ingress-nginx-controller   LoadBalancer   192.168.1.100    80:xxx/TCP,443:xxx/TCP

# Access via single IP
curl http://192.168.1.100
```

**Pros**:
- ✅ Single IP for all traffic
- ✅ Automatic failover (VIP moves if node fails)
- ✅ Works like cloud load balancers
- ✅ Clean DNS (one A record)

**When to use**: Production deployments

#### Option 4: External Load Balancer

Use a separate load balancer (HAProxy, nginx, hardware LB) in front of your cluster:

```
Internet → External LB (192.168.1.5) → [Node1, Node2, Node3]
```

**When to use**: Enterprise environments, need advanced features (SSL offloading, WAF)

### Recommendations

**Development/Testing**:
- Use any node IP directly
- Quick and simple

**Home Lab/Small Production**:
- Use MetalLB with VIP
- Gives you a clean single IP
- Easy to set up

**Large Production**:
- External load balancer + MetalLB
- HAProxy/nginx LB for external traffic
- MetalLB for internal services

### Example: Complete Ingress Setup with MetalLB

```bash
# 1. Install MetalLB (via Argo CD or kubectl)
kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.14.9/config/manifests/metallb-native.yaml

# 2. Configure IP pool (wait for MetalLB to be ready)
cat <<EOF | kubectl apply -f -
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: default
  namespace: metallb-system
spec:
  addresses:
  - 192.168.1.100-192.168.1.110
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: default
  namespace: metallb-system
spec:
  ipAddressPools:
  - default
EOF

# 3. Install nginx ingress (gets VIP automatically)
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/baremetal/deploy.yaml

# 4. Patch to use LoadBalancer type
kubectl patch svc ingress-nginx-controller -n ingress-nginx \
  -p '{"spec": {"type": "LoadBalancer"}}'

# 5. Get the VIP
kubectl get svc -n ingress-nginx ingress-nginx-controller
# EXTERNAL-IP will show 192.168.1.100 (from MetalLB pool)

# 6. Point DNS to VIP
# *.yourdomain.com → 192.168.1.100

# 7. Create ingress for your apps
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: example-app
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  ingressClassName: nginx
  rules:
  - host: app.yourdomain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: example-app
            port:
              number: 80
  tls:
  - hosts:
    - app.yourdomain.com
    secretName: app-tls
EOF
```

Now access your app at `https://app.yourdomain.com` → VIP (192.168.1.100) → Any healthy node!

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

### If Using GitOps (Recommended):
1. **Git Repository**: Your `cluster-config` repo (already backed up by Git hosting)
2. **Kubeconfig**: `kubeconfig` file (for emergency access)
3. **Longhorn Volumes**: Configure Longhorn backup to S3/NFS
4. **Argo CD Secrets**: Backup repository credentials if needed

**Disaster recovery with GitOps:**
- Rebuild cluster from genesis scripts
- Install Argo CD
- Apply app-of-apps → entire cluster rebuilds automatically
- Restore Longhorn volumes from S3/NFS backups

### If Using Manual Installation:
1. **Ignition configs**: `ignition-*.json` files
2. **Kubeconfig**: `kubeconfig` file
3. **k3s token**: From `/var/lib/rancher/k3s/server/token`
4. **Kubernetes manifests**: All applied YAML files
5. **Longhorn volumes**: Longhorn backup to S3/NFS

## Next Steps

### GitOps Path (Recommended):

1. **Set up Git repository** for cluster config
2. **Install Argo CD** (see GitOps Setup Guide)
3. **Define applications as code**:
   - Longhorn with storage network config
   - Ingress controller (nginx or traefik)
   - Cert-manager for TLS
   - Monitoring stack (Prometheus/Grafana via kube-prometheus-stack)
   - Your applications
4. **Configure Longhorn backup** to S3/NFS (via Argo app)
5. **Set up Argo CD notifications** (Slack/Discord for sync status)
6. **Enable Argo CD SSO** (GitHub/GitLab/OIDC)

### Manual Path:

1. **Deploy your applications** with `kubectl apply`
2. **Set up ingress controller** (k3s includes Traefik, or install nginx)
3. **Configure cert-manager** for TLS certificates
4. **Set up monitoring** (Prometheus/Grafana)
5. **Configure backups** (Longhorn backup + Velero)
6. **Consider migrating to GitOps** (Argo CD can adopt existing resources)

## Resources

### Platform Documentation
- [Fedora CoreOS Documentation](https://docs.fedoraproject.org/en-US/fedora-coreos/)
- [k3s Documentation](https://docs.k3s.io/)
- [Longhorn Documentation](https://longhorn.io/docs/)
- [Odroid HC4 Wiki](https://wiki.odroid.com/odroid-hc4/odroid-hc4)

### GitOps & CI/CD
- [Argo CD Documentation](https://argo-cd.readthedocs.io/)
- [Argo CD Best Practices](https://argo-cd.readthedocs.io/en/stable/user-guide/best_practices/)
- [GitOps Principles](https://opengitops.dev/)

### Networking
- [Longhorn Storage Network](https://longhorn.io/docs/1.7.2/advanced-resources/deploy/storage-network/)
- [NetworkManager Configuration](https://networkmanager.dev/docs/)
- [MetalLB Documentation](https://metallb.universe.tf/)
- [k3s Networking](https://docs.k3s.io/networking)

### Monitoring & Observability
- [kube-prometheus-stack](https://github.com/prometheus-operator/kube-prometheus)
- [Grafana Dashboards for Longhorn](https://grafana.com/grafana/dashboards/?search=longhorn)
