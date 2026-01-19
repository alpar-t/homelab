#!/bin/bash
set -euo pipefail

# Join a newly ignited node to an existing k3s cluster
# Usage: ./join-cluster.sh <new-node> <existing-cluster-member>
# Example: ./join-cluster.sh pufi.local pamacs.local

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
NODE_TO_ADD="${1:-}"
CLUSTER_MEMBER="${2:-}"

if [ -z "${NODE_TO_ADD}" ] || [ -z "${CLUSTER_MEMBER}" ]; then
    echo "Usage: $0 <new-node> <existing-cluster-member>"
    echo ""
    echo "Example:"
    echo "  $0 pufi.local pamacs.local"
    echo ""
    echo "This script joins a freshly ignited node to an existing k3s cluster."
    echo "Run this after the new node has booted from NVMe and is reachable via SSH."
    exit 1
fi

# Detect SSH key
if [ -f "$HOME/.ssh/id_ed25519" ]; then
    SSH_KEY="$HOME/.ssh/id_ed25519"
elif [ -f "$HOME/.ssh/id_rsa" ]; then
    SSH_KEY="$HOME/.ssh/id_rsa"
else
    echo -e "${RED}Error: No SSH key found at ~/.ssh/id_ed25519 or ~/.ssh/id_rsa${NC}"
    exit 1
fi

echo "=============================================="
echo "  Join Node to k3s Cluster"
echo "=============================================="
echo ""
echo "  New node:        ${NODE_TO_ADD}"
echo "  Cluster member:  ${CLUSTER_MEMBER}"
echo "  SSH key:         ${SSH_KEY}"
echo ""

# SSH helper function
ssh_node() {
    local node=$1
    shift
    ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no -o ConnectTimeout=10 core@${node} "$@"
}

# Function to resolve hostname to IP
resolve_ip() {
    local hostname=$1
    local ip=$(getent hosts "${hostname}" 2>/dev/null | awk '{print $1}' | head -1)
    if [ -z "${ip}" ]; then
        ip=$(ping -c 1 -W 2 "${hostname}" 2>/dev/null | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}' | head -1)
    fi
    echo "${ip}"
}

# Step 1: Check connectivity to both nodes
echo -e "${YELLOW}Step 1: Checking node connectivity...${NC}"

if ! ping -c 1 -W 3 ${CLUSTER_MEMBER} &> /dev/null; then
    echo -e "${RED}Error: Cannot reach cluster member ${CLUSTER_MEMBER}${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} ${CLUSTER_MEMBER} is reachable"

if ! ping -c 1 -W 3 ${NODE_TO_ADD} &> /dev/null; then
    echo -e "${RED}Error: Cannot reach new node ${NODE_TO_ADD}${NC}"
    echo "  Make sure the node has booted from NVMe and is on the network."
    exit 1
fi
echo -e "  ${GREEN}✓${NC} ${NODE_TO_ADD} is reachable"
echo ""

# Step 2: Verify SSH access
echo -e "${YELLOW}Step 2: Verifying SSH access...${NC}"

if ! ssh_node ${CLUSTER_MEMBER} "echo ok" &> /dev/null; then
    echo -e "${RED}Error: Cannot SSH to ${CLUSTER_MEMBER}${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} SSH to ${CLUSTER_MEMBER} works"

if ! ssh_node ${NODE_TO_ADD} "echo ok" &> /dev/null; then
    echo -e "${RED}Error: Cannot SSH to ${NODE_TO_ADD}${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} SSH to ${NODE_TO_ADD} works"
echo ""

# Step 3: Get cluster token from existing member
echo -e "${YELLOW}Step 3: Getting cluster token from ${CLUSTER_MEMBER}...${NC}"

K3S_TOKEN=$(ssh_node ${CLUSTER_MEMBER} "sudo cat /var/lib/rancher/k3s/server/token" 2>/dev/null)
if [ -z "${K3S_TOKEN}" ]; then
    echo -e "${RED}Error: Could not get k3s token from ${CLUSTER_MEMBER}${NC}"
    echo "  Is k3s running on that node?"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} Got cluster token"
echo ""

# Step 4: Resolve IPs
echo -e "${YELLOW}Step 4: Resolving node IPs...${NC}"

CLUSTER_MEMBER_IP=$(resolve_ip "${CLUSTER_MEMBER}")
if [ -z "${CLUSTER_MEMBER_IP}" ]; then
    echo -e "${RED}Error: Could not resolve IP for ${CLUSTER_MEMBER}${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} ${CLUSTER_MEMBER} -> ${CLUSTER_MEMBER_IP}"

# Get new node's IP from the node itself (more reliable)
NEW_NODE_IP=$(ssh_node ${NODE_TO_ADD} "ip -4 addr show enp2s0 2>/dev/null | grep -oP '(?<=inet\s)\\d+(\\.\\d+){3}' | head -1")
if [ -z "${NEW_NODE_IP}" ]; then
    # Fallback to resolving from outside
    NEW_NODE_IP=$(resolve_ip "${NODE_TO_ADD}")
fi
if [ -z "${NEW_NODE_IP}" ]; then
    echo -e "${RED}Error: Could not determine IP for ${NODE_TO_ADD}${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} ${NODE_TO_ADD} -> ${NEW_NODE_IP}"

# Get hostname (without .local)
NEW_NODE_HOSTNAME=$(ssh_node ${NODE_TO_ADD} "hostname")
echo -e "  ${GREEN}✓${NC} Hostname: ${NEW_NODE_HOSTNAME}"
echo ""

# Step 5: Stop k3s and clean up on new node
echo -e "${YELLOW}Step 5: Preparing ${NODE_TO_ADD} for cluster join...${NC}"

ssh_node ${NODE_TO_ADD} "sudo systemctl stop k3s || true"
echo "  Stopped k3s"

ssh_node ${NODE_TO_ADD} "sudo rm -rf /var/lib/rancher/k3s/server/db"
ssh_node ${NODE_TO_ADD} "sudo rm -rf /var/lib/rancher/k3s/server/token"
ssh_node ${NODE_TO_ADD} "sudo rm -rf /var/lib/rancher/k3s/server/tls"
ssh_node ${NODE_TO_ADD} "sudo rm -rf /var/lib/rancher/k3s/server/cred"
echo "  Cleaned old cluster data"
echo ""

# Step 6: Configure k3s to join the cluster
echo -e "${YELLOW}Step 6: Configuring k3s to join cluster...${NC}"

ssh_node ${NODE_TO_ADD} "sudo tee /etc/systemd/system/k3s.service" > /dev/null <<EOF
[Unit]
Description=Lightweight Kubernetes
Documentation=https://k3s.io
Wants=network-online.target avahi-daemon.service
After=network-online.target avahi-daemon.service

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

# Priority settings to keep k3s responsive under high load
Nice=-10
CPUWeight=10000
IOWeight=1000
OOMScoreAdjust=-900

ExecStartPre=-/sbin/modprobe br_netfilter
ExecStartPre=-/sbin/modprobe overlay
ExecStart=/usr/local/bin/k3s server \\
  --disable=traefik \\
  --disable=servicelb \\
  --write-kubeconfig-mode=644 \\
  --server https://${CLUSTER_MEMBER_IP}:6443 \\
  --token ${K3S_TOKEN} \\
  --node-ip ${NEW_NODE_IP} \\
  --advertise-address ${NEW_NODE_IP} \\
  --tls-san ${NEW_NODE_IP} \\
  --tls-san ${NODE_TO_ADD}

[Install]
WantedBy=multi-user.target
EOF

echo -e "  ${GREEN}✓${NC} k3s.service configured to join cluster at ${CLUSTER_MEMBER_IP}"
echo ""

# Step 7: Start k3s
echo -e "${YELLOW}Step 7: Starting k3s on ${NODE_TO_ADD}...${NC}"

ssh_node ${NODE_TO_ADD} "sudo systemctl daemon-reload"
ssh_node ${NODE_TO_ADD} "sudo systemctl start k3s"

echo "  Waiting for k3s to start..."
sleep 10

# Check if k3s is running
if ssh_node ${NODE_TO_ADD} "sudo systemctl is-active --quiet k3s"; then
    echo -e "  ${GREEN}✓${NC} k3s is running"
else
    echo -e "${YELLOW}  ⚠ k3s may still be starting. Check with:${NC}"
    echo "    ssh core@${NODE_TO_ADD} 'sudo journalctl -u k3s -f'"
fi
echo ""

# Step 8: Verify node joined the cluster
echo -e "${YELLOW}Step 8: Verifying cluster membership...${NC}"

sleep 5

# Try to check nodes via the cluster member
NODES=$(ssh_node ${CLUSTER_MEMBER} "sudo kubectl get nodes --no-headers 2>/dev/null" || echo "")
if echo "${NODES}" | grep -q "${NEW_NODE_HOSTNAME}"; then
    echo -e "  ${GREEN}✓${NC} ${NEW_NODE_HOSTNAME} is now part of the cluster!"
    echo ""
    echo "Cluster nodes:"
    echo "${NODES}" | sed 's/^/  /'
else
    echo -e "${YELLOW}  ⚠ Node may still be joining. Check cluster status with:${NC}"
    echo "    kubectl get nodes"
fi

echo ""
echo "=============================================="
echo -e "  ${GREEN}✓ Join process complete!${NC}"
echo "=============================================="
echo ""
echo "Verify from your Mac:"
echo "  export KUBECONFIG=$(pwd)/kubeconfig"
echo "  kubectl get nodes"
echo ""




