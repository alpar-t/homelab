# Recover Cluster from Single Node

This runbook documents recovering a 3-node k3s cluster when only one node is running.

## Scenario

- **Cluster**: 3-node k3s HA with embedded etcd (pufi, buksi, pamacs)
- **Problem**: Only 1 node running → no etcd quorum → cluster stuck
- **Goal**: Restore full 3-node cluster

---

## Prerequisites

- SSH access to the surviving node
- CoreOS USB installer
- Access to ignition configs (`genesis/ignition-*.json`)

---

## Step 1: Reset etcd on Surviving Node ( if single node only )

With only 1 node, etcd can't achieve quorum (needs 2/3). Reset it to single-node mode:

```bash
ssh core@<surviving-node>.local

# Stop k3s
sudo systemctl stop k3s

# Reset etcd to single-node (removes other nodes from membership)
sudo k3s server --cluster-reset

# Wait for: "Managed etcd cluster membership has been reset"
# Then Ctrl+C

# Start k3s
sudo systemctl start k3s

# Verify
sudo systemctl status k3s
kubectl get nodes
```

**Note**: This does NOT delete data. It only removes missing nodes from etcd membership.

---

## Step 2: Update kubeconfig

```bash
cd ~/Work/github/homepbp/genesis

# Fetch new kubeconfig from surviving node
scp core@<surviving-node>.local:/etc/rancher/k3s/k3s.yaml ./kubeconfig
sed -i '' 's/127.0.0.1/<surviving-node>.local/' kubeconfig

export KUBECONFIG=$(pwd)/kubeconfig
kubectl get nodes
```

---

## Step 3: Reignite Failed Nodes

For each failed node, follow the reignition process.

### 3a: Boot from USB and Install

```bash
# On your Mac - start HTTP server
cd ~/Work/github/homepbp/genesis
python3 -m http.server 8080

# Get your Mac's IP
ipconfig getifaddr en0
```

On the node (booted from CoreOS USB):
```bash
sudo coreos-installer install /dev/nvme0n1 \
  --ignition-url http://<YOUR_MAC_IP>:8080/ignition-<node>.json \
  --insecure-ignition

# Remove USB and reboot
sudo systemctl reboot
```

### 3b: Fix DNS (if using older ignition)

If the node was ignited with an older config that doesn't have proper DNS:

```bash
ssh core@<node-ip>

# Configure DNS to use Cloudflare + Google
sudo tee /etc/NetworkManager/system-connections/enp2s0.nmconnection > /dev/null <<'EOF'
[connection]
id=enp2s0-management
type=ethernet
interface-name=enp2s0
autoconnect=true
autoconnect-priority=100

[ipv4]
method=auto
dns=1.1.1.1;8.8.8.8;
ignore-auto-dns=true

[ipv6]
method=auto
addr-gen-mode=stable-privacy
EOF

sudo chmod 600 /etc/NetworkManager/system-connections/enp2s0.nmconnection
sudo nmcli connection reload
sudo nmcli connection down enp2s0-management || true
sudo nmcli connection up enp2s0-management

# Verify
cat /etc/resolv.conf
ping -c 2 google.com
```

### 3c: Install Avahi (if using older ignition)

```bash
# Install Avahi for .local mDNS resolution
sudo rpm-ostree install avahi avahi-tools nss-mdns

# Create Avahi config interfaces 
sudo vi /etc/avahi/avahi-daemon.conf 

# Enable and start
sudo systemctl enable avahi-daemon
sudo systemctl start avahi-daemon
```

---

## Step 3d: Mount Existing Longhorn Disks (if data exists)

**IMPORTANT**: If the node's disks already have Longhorn data from before, do NOT run `setup-node-storage.sh` — it will wipe the data!

Instead, just mount the existing disks:

```bash
ssh core@<node-ip>

# Check disks have existing Longhorn labels
lsblk -o NAME,SIZE,TYPE,FSTYPE,LABEL,MODEL
# Should show: longhorn-disk1, longhorn-disk2

# Create mount points
sudo mkdir -p /var/mnt/disk1 /var/mnt/disk2

# Create mount unit for disk1
sudo tee /etc/systemd/system/var-mnt-disk1.mount > /dev/null <<'EOF'
[Unit]
Description=Mount Longhorn Disk 1
Before=local-fs.target

[Mount]
What=/dev/disk/by-label/longhorn-disk1
Where=/var/mnt/disk1
Type=ext4
Options=defaults,noatime

[Install]
WantedBy=local-fs.target
EOF

# Create mount unit for disk2
sudo tee /etc/systemd/system/var-mnt-disk2.mount > /dev/null <<'EOF'
[Unit]
Description=Mount Longhorn Disk 2
Before=local-fs.target

[Mount]
What=/dev/disk/by-label/longhorn-disk2
Where=/var/mnt/disk2
Type=ext4
Options=defaults,noatime

[Install]
WantedBy=local-fs.target
EOF

# Enable and start mounts
sudo systemctl daemon-reload
sudo systemctl enable --now var-mnt-disk1.mount var-mnt-disk2.mount

# Verify
df -h /var/mnt/disk1 /var/mnt/disk2
ls -la /var/mnt/disk1/  # Should see 'replicas' directory
```

Also create the SSD storage directory:
```bash
sudo mkdir -p /var/lib/longhorn-ssd
```

---

## Step 4: Join Node to Cluster

Use the join script:

```bash
cd ~/Work/github/homepbp/genesis
./join-cluster.sh <new-node>.local <surviving-node>.local

# Example:
./join-cluster.sh pufi.local pamacs.local
```

Or use IP if .local isn't working yet:
```bash
./join-cluster.sh 192.168.1.166 pamacs.local
```

---

## Step 5: Configure Longhorn for Rejoined Node

After a node joins the cluster, tell Longhorn about its disks:

```bash
# Label node to use custom disk config
kubectl label node <node-name> node.longhorn.io/create-default-disk=config

# Annotate with disk paths (adjust based on how many disks the node has)
# Two disks:
kubectl annotate node <node-name> node.longhorn.io/default-disks-config='[{"path":"/var/mnt/disk1","allowScheduling":true},{"path":"/var/mnt/disk2","allowScheduling":true}]'

# One disk:
kubectl annotate node <node-name> node.longhorn.io/default-disks-config='[{"path":"/var/mnt/disk1","allowScheduling":true}]'
```

### Apply Zincati Update Policy

If the node was ignited with an older config, apply the staggered update policy to prevent simultaneous reboots:

```bash
# For a single node (e.g., pufi on Thursdays):
ssh core@pufi.local "sudo mkdir -p /etc/zincati/config.d && sudo tee /etc/zincati/config.d/51-cluster-updates.toml > /dev/null << 'EOF'
[updates]
strategy = \"periodic\"

[[updates.periodic.window]]
days = [ \"Thu\" ]
start_time = \"03:00\"
length_minutes = 120
EOF
sudo systemctl restart zincati"

# Or apply to all nodes at once:
cd ~/Work/github/homepbp/genesis
./apply-zincati-config.sh
```

Update schedule:
- **buksi** - Tuesdays 03:00-05:00 UTC
- **pamacs** - Wednesdays 03:00-05:00 UTC
- **pufi** - Thursdays 03:00-05:00 UTC

### Tag disks for SSD/HDD storage classes (optional)

If using separate SSD and HDD storage classes:

```bash
cd ~/Work/github/homepbp/config/longhorn
./tag-disks.sh
```

### Verify Longhorn sees the node and disks

```bash
# Check node is registered in Longhorn
kubectl get nodes.longhorn.io -n longhorn-system

# Check disks are discovered
kubectl get nodes.longhorn.io -n longhorn-system <node-name> -o yaml | grep -A20 disks:
```

In the Longhorn UI (https://longhorn.newjoy.ro or via port-forward):
- Go to **Node** tab
- Verify the rejoined node shows with its disks
- Check disk status is "Schedulable"

---

## Step 6: Repeat for Other Nodes

Repeat Steps 3-5 for each additional node (buksi, etc.)

---

## Step 7: Verify Full Cluster

```bash
kubectl get nodes
# All 3 nodes should be Ready

kubectl get pods -A
# All pods should be Running

# Check Longhorn nodes and disks
kubectl get nodes.longhorn.io -n longhorn-system

# Check Longhorn volumes are healthy
kubectl get volumes -n longhorn-system
```

---

## Troubleshooting

### Node can't resolve DNS

Check `/etc/resolv.conf` and NetworkManager config:
```bash
cat /etc/resolv.conf
nmcli connection show enp2s0-management
```

### Node can't reach .local addresses

Verify Avahi is running:
```bash
sudo systemctl status avahi-daemon
avahi-browse -a
```

### k3s fails to start on rejoined node

Check logs:
```bash
sudo journalctl -u k3s -f
```

Common issues:
- Token mismatch (get fresh token from cluster member)
- Old cluster data (clean with `rm -rf /var/lib/rancher/k3s/server/{db,token,tls,cred}`)

### "duplicate node name found" error when joining

If you see this error after reinstalling a node:
```
etcd cluster join failed: duplicate node name found, please use a unique name for this node
```

The old etcd member entry still exists in the cluster. Even `--cluster-reset` may not remove it if the cluster has quorum. You need to manually remove the stale member.

**Solution**: Download etcdctl and remove the stale member:

```bash
ssh core@<working-node>.local

# Download etcdctl (k3s doesn't include it by default)
curl -L https://github.com/etcd-io/etcd/releases/download/v3.5.9/etcd-v3.5.9-linux-amd64.tar.gz -o /tmp/etcd.tar.gz
cd /tmp && tar xzf etcd.tar.gz
ETCDCTL=/tmp/etcd-v3.5.9-linux-amd64/etcdctl

# List current etcd members
sudo $ETCDCTL \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/var/lib/rancher/k3s/server/tls/etcd/server-ca.crt \
  --cert=/var/lib/rancher/k3s/server/tls/etcd/server-client.crt \
  --key=/var/lib/rancher/k3s/server/tls/etcd/server-client.key \
  member list

# Output shows member IDs like:
# 1a2b3c4d5e6f7890, started, buksi, https://192.168.1.x:2380, ...
# 2b3c4d5e6f789012, started, pamacs, https://192.168.1.y:2380, ...

# Remove the stale node (use the ID from the first column)
sudo $ETCDCTL \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/var/lib/rancher/k3s/server/tls/etcd/server-ca.crt \
  --cert=/var/lib/rancher/k3s/server/tls/etcd/server-client.crt \
  --key=/var/lib/rancher/k3s/server/tls/etcd/server-client.key \
  member remove <STALE_MEMBER_ID>

# Clean up
rm -rf /tmp/etcd*
```

Now retry the join:
```bash
./join-cluster.sh <node>.local <working-node>.local
```

### Longhorn volumes degraded

After all nodes rejoin, Longhorn should auto-rebuild replicas. Check:
```bash
kubectl get volumes -n longhorn-system
kubectl get replicas -n longhorn-system
```

---

## Recovery Timeline

| Date | Event | Notes |
|------|-------|-------|
| 2024-12-30 | pamacs only surviving | Started recovery |
| | | |

---

## Related

- [genesis/join-cluster.sh](../genesis/join-cluster.sh) - Automated cluster join script
- [genesis/README.md](../genesis/README.md) - Full cluster setup documentation
- [recover-longhorn-orphaned-volume.md](./recover-longhorn-orphaned-volume.md) - Longhorn data recovery

