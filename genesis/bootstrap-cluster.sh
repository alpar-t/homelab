#!/bin/bash
set -euo pipefail

# Bootstrap k3s HA cluster across 3 nodes
# This assumes all 3 nodes have CoreOS installed and k3s.service running

# Configuration
# Use default SSH key (id_ed25519 or id_rsa)
if [ -f "$HOME/.ssh/id_ed25519" ]; then
    SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
elif [ -f "$HOME/.ssh/id_rsa" ]; then
    SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_rsa}"
else
    echo "Error: No SSH key found. Generate one with: ssh-keygen -t ed25519"
    exit 1
fi

# Use .local mDNS addresses by default (opinionated setup)
NODE1_HOST="${NODE1:-pufi.local}"
NODE2_HOST="${NODE2:-buksi.local}"
NODE3_HOST="${NODE3:-pamacs.local}"
CLUSTER_NAME="${CLUSTER_NAME:-baxter}"

echo "Bootstrapping k3s HA cluster: ${CLUSTER_NAME}"
echo "Resolving node addresses..."

# Function to resolve hostname to IP
resolve_ip() {
    local hostname=$1
    # Try getent first (works with mDNS via nss-mdns)
    local ip=$(getent hosts "${hostname}" 2>/dev/null | awk '{print $1}' | head -1)
    if [ -z "${ip}" ]; then
        # Fallback to ping
        ip=$(ping -c 1 "${hostname}" 2>/dev/null | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}' | head -1)
    fi
    echo "${ip}"
}

# Resolve hostnames to IPs (k3s/Go doesn't use NSS/mDNS)
NODE1_IP=$(resolve_ip "${NODE1_HOST}")
NODE2_IP=$(resolve_ip "${NODE2_HOST}")
NODE3_IP=$(resolve_ip "${NODE3_HOST}")

if [ -z "${NODE1_IP}" ] || [ -z "${NODE2_IP}" ] || [ -z "${NODE3_IP}" ]; then
    echo "Error: Failed to resolve node IPs"
    echo "  ${NODE1_HOST} -> ${NODE1_IP:-FAILED}"
    echo "  ${NODE2_HOST} -> ${NODE2_IP:-FAILED}"
    echo "  ${NODE3_HOST} -> ${NODE3_IP:-FAILED}"
    exit 1
fi

echo "Nodes:"
echo "  - ${NODE1_HOST} (${NODE1_IP}) - primary"
echo "  - ${NODE2_HOST} (${NODE2_IP})"
echo "  - ${NODE3_HOST} (${NODE3_IP})"
echo ""

# Function to SSH into a node (using hostname for SSH, but we'll use IPs for k3s config)
ssh_node() {
    local node_host=$1
    shift
    ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no core@${node_host} "$@"
}

# Check if nodes are reachable
echo "Checking node connectivity..."
for node in ${NODE1_HOST} ${NODE2_HOST} ${NODE3_HOST}; do
    if ! ping -c 1 -W 2 ${node} &> /dev/null; then
        echo "Error: Cannot reach ${node}"
        exit 1
    fi
    echo "  ✓ ${node} is reachable"
done
echo ""

# Configure and start primary node first
echo "Configuring primary node (${NODE1_HOST})..."

# Stop k3s on primary
ssh_node ${NODE1_HOST} "sudo systemctl stop k3s || true"

# Clean any old cluster data on primary
echo "  Cleaning old k3s data on primary..."
ssh_node ${NODE1_HOST} "sudo rm -rf /var/lib/rancher/k3s/server/db"
ssh_node ${NODE1_HOST} "sudo rm -rf /var/lib/rancher/k3s/server/token"
ssh_node ${NODE1_HOST} "sudo rm -rf /var/lib/rancher/k3s/server/tls"
ssh_node ${NODE1_HOST} "sudo rm -rf /var/lib/rancher/k3s/server/cred"

# Remove any override files
ssh_node ${NODE1_HOST} "sudo rm -f /etc/systemd/system/k3s.service.d/override.conf"

# Configure k3s on primary node with proper IP bindings
echo "  Configuring k3s on primary with IP ${NODE1_IP}..."
ssh_node ${NODE1_HOST} "sudo tee /etc/systemd/system/k3s.service" > /dev/null <<EOF
[Unit]
Description=Lightweight Kubernetes
Documentation=https://k3s.io
Wants=network-online.target
After=network-online.target

[Service]
Type=notify
KillMode=process
Delegate=yes
LimitNOFILE=1048576
LimitNPROC=infinity
LimitCORE=infinity
TasksMax=infinity
TimeoutStartSec=0
Restart=always
RestartSec=5s
ExecStartPre=-/sbin/modprobe br_netfilter
ExecStartPre=-/sbin/modprobe overlay
ExecStart=/usr/local/bin/k3s server \\
  --disable=traefik \\
  --disable=servicelb \\
  --write-kubeconfig-mode=644 \\
  --cluster-init \\
  --node-ip ${NODE1_IP} \\
  --advertise-address ${NODE1_IP} \\
  --tls-san ${NODE1_IP} \\
  --tls-san ${NODE1_HOST}

[Install]
WantedBy=multi-user.target
EOF

# Reload and start primary
ssh_node ${NODE1_HOST} "sudo systemctl daemon-reload"
ssh_node ${NODE1_HOST} "sudo systemctl start k3s"

echo "  Waiting for k3s on primary node..."
sleep 10
until ssh_node ${NODE1_HOST} "sudo systemctl is-active --quiet k3s"; do
    echo "  Waiting for k3s.service to be active..."
    sleep 5
done
echo "  ✓ k3s is running on primary node"
echo ""

# Get the cluster token from first node
echo "Getting cluster token from primary node..."
K3S_TOKEN=$(ssh_node ${NODE1_HOST} "sudo cat /var/lib/rancher/k3s/server/token")
if [ -z "${K3S_TOKEN}" ]; then
    echo "Error: Could not get k3s token from primary node"
    exit 1
fi
echo "  ✓ Got cluster token"
echo ""

# Configure additional nodes to join the cluster
for node_host in ${NODE2_HOST} ${NODE3_HOST}; do
    echo "Configuring node ${node_host} to join cluster..."
    
    # Stop k3s if it's running standalone
    ssh_node ${node_host} "sudo systemctl stop k3s || true"
    
    # Clean up old k3s data (needed if node was running standalone)
    echo "  Cleaning up old k3s data..."
    ssh_node ${node_host} "sudo rm -rf /var/lib/rancher/k3s/server/db"
    ssh_node ${node_host} "sudo rm -rf /var/lib/rancher/k3s/server/token"
    ssh_node ${node_host} "sudo rm -rf /var/lib/rancher/k3s/server/tls"
    ssh_node ${node_host} "sudo rm -rf /var/lib/rancher/k3s/server/cred"
    
    # Remove any override files
    ssh_node ${node_host} "sudo rm -f /etc/systemd/system/k3s.service.d/override.conf"
    
    # Get the IP of this node
    node_ip=""
    if [ "${node_host}" = "${NODE2_HOST}" ]; then
        node_ip="${NODE2_IP}"
    else
        node_ip="${NODE3_IP}"
    fi
    
    # Update k3s service to join existing cluster using IP (k3s/Go doesn't use NSS/mDNS)
    echo "  Configuring k3s to join primary node at ${NODE1_IP}..."
    echo "  This node will advertise as ${node_ip}..."
    ssh_node ${node_host} "sudo tee /etc/systemd/system/k3s.service" > /dev/null <<EOF
[Unit]
Description=Lightweight Kubernetes
Documentation=https://k3s.io
Wants=network-online.target
After=network-online.target

[Service]
Type=notify
KillMode=process
Delegate=yes
LimitNOFILE=1048576
LimitNPROC=infinity
LimitCORE=infinity
TasksMax=infinity
TimeoutStartSec=0
Restart=always
RestartSec=5s
ExecStartPre=-/sbin/modprobe br_netfilter
ExecStartPre=-/sbin/modprobe overlay
ExecStart=/usr/local/bin/k3s server \\
  --disable=traefik \\
  --disable=servicelb \\
  --write-kubeconfig-mode=644 \\
  --server https://${NODE1_IP}:6443 \\
  --token ${K3S_TOKEN} \\
  --node-ip ${node_ip} \\
  --advertise-address ${node_ip} \\
  --tls-san ${node_ip} \\
  --tls-san ${node_host}

[Install]
WantedBy=multi-user.target
EOF
    
    # Reload and restart k3s
    ssh_node ${node_host} "sudo systemctl daemon-reload"
    ssh_node ${node_host} "sudo systemctl restart k3s"
    
    echo "  ✓ Node ${node_host} configured and joining cluster"
done

echo ""
echo "Waiting for all nodes to join cluster..."
sleep 10

# Get kubeconfig from primary node
echo "Fetching kubeconfig..."
scp -i "${SSH_KEY}" -o StrictHostKeyChecking=no \
    core@${NODE1_HOST}:/etc/rancher/k3s/k3s.yaml ./kubeconfig

# Update server address in kubeconfig to use .local address (works from Mac via mDNS)
sed -i '' "s/127.0.0.1/${NODE1_HOST}/" kubeconfig

export KUBECONFIG=$(pwd)/kubeconfig

echo ""
echo "Cluster nodes:"
kubectl get nodes -o wide

echo ""
echo "✓ Cluster bootstrap complete!"
echo ""
echo "Kubeconfig saved to: $(pwd)/kubeconfig"
echo "Use it with:"
echo "  export KUBECONFIG=$(pwd)/kubeconfig"
echo "  kubectl get nodes"
echo ""
echo "Access nodes via:"
echo "  Individual: ${NODE1_HOST}, ${NODE2_HOST}, ${NODE3_HOST}"
echo "  Cluster:    ${CLUSTER_NAME}.local (round-robin)"
echo ""
echo "Next steps:"
echo "  1. Install Argo CD (for GitOps)"
echo "  2. Install Longhorn via Argo CD"
echo "  3. Configure storage disks in Longhorn"
echo "  4. Deploy your applications"

