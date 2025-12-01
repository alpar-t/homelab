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
NODE1="${NODE1:-odroid-1.local}"
NODE2="${NODE2:-odroid-2.local}"
NODE3="${NODE3:-odroid-3.local}"
CLUSTER_NAME="${CLUSTER_NAME:-baxter}"

echo "Note: Using .local mDNS addresses for cluster nodes"
echo "Override with: NODE1=192.168.1.10 NODE2=192.168.1.11 NODE3=192.168.1.12 ./bootstrap-cluster.sh"
echo ""

echo "Bootstrapping k3s HA cluster: ${CLUSTER_NAME}"
echo "Nodes:"
echo "  - ${NODE1} (primary)"
echo "  - ${NODE2}"
echo "  - ${NODE3}"
echo ""

# Function to SSH into a node
ssh_node() {
    local node_ip=$1
    shift
    ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null core@${node_ip} "$@"
}

# Check if nodes are reachable
echo "Checking node connectivity..."
for node in ${NODE1} ${NODE2} ${NODE3}; do
    if ! ping -c 1 -W 2 ${node} &> /dev/null; then
        echo "Error: Cannot reach ${node}"
        exit 1
    fi
    echo "  ✓ ${node} is reachable"
done
echo ""

# Wait for k3s to be ready on first node
echo "Waiting for k3s on primary node (${NODE1})..."
until ssh_node ${NODE1} "sudo systemctl is-active --quiet k3s"; do
    echo "  Waiting for k3s.service to be active..."
    sleep 5
done
echo "  ✓ k3s is running on primary node"
echo ""

# Get the cluster token from first node
echo "Getting cluster token from primary node..."
K3S_TOKEN=$(ssh_node ${NODE1} "sudo cat /var/lib/rancher/k3s/server/token")
if [ -z "${K3S_TOKEN}" ]; then
    echo "Error: Could not get k3s token from primary node"
    exit 1
fi
echo "  ✓ Got cluster token"
echo ""

# Configure additional nodes to join the cluster
for node in ${NODE2} ${NODE3}; do
    echo "Configuring node ${node} to join cluster..."
    
    # Stop k3s if it's running standalone
    ssh_node ${node} "sudo systemctl stop k3s || true"
    
    # Update k3s service to join existing cluster
    ssh_node ${node} "sudo tee /etc/systemd/system/k3s.service.d/override.conf" > /dev/null <<EOF
[Service]
ExecStart=
ExecStart=/usr/local/bin/k3s server \\
  --disable=traefik \\
  --disable=servicelb \\
  --write-kubeconfig-mode=644 \\
  --server https://${NODE1}:6443 \\
  --token ${K3S_TOKEN}
EOF
    
    # Reload and restart k3s
    ssh_node ${node} "sudo systemctl daemon-reload"
    ssh_node ${node} "sudo systemctl restart k3s"
    
    echo "  ✓ Node ${node} configured and joining cluster"
done

echo ""
echo "Waiting for all nodes to join cluster..."
sleep 10

# Get kubeconfig from primary node
echo "Fetching kubeconfig..."
scp -i "${SSH_KEY}" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    core@${NODE1}:/etc/rancher/k3s/k3s.yaml ./kubeconfig

# Update server address in kubeconfig to use .local address
sed -i '' "s/127.0.0.1/${NODE1}/" kubeconfig

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
echo "Next steps:"
echo "  1. Install Longhorn: kubectl apply -f https://raw.githubusercontent.com/longhorn/longhorn/v1.7.2/deploy/longhorn.yaml"
echo "  2. Configure storage disks in Longhorn UI"
echo "  3. Deploy your applications"

