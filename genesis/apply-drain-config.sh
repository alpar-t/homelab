#!/bin/bash
set -euo pipefail

# Apply graceful drain/uncordon services to running nodes
# This ensures pods get graceful termination before Zincati reboots
#
# Usage: ./apply-drain-config.sh
#
# This script:
# 1. Copies drain/uncordon scripts to each node
# 2. Creates systemd services that run before shutdown and after startup
# 3. Enables the services

echo "=== Applying Graceful Drain Configuration ==="
echo ""
echo "This will configure automatic kubectl drain before reboot"
echo "and kubectl uncordon after startup on each node."
echo ""

DRAIN_SCRIPT='#!/bin/bash
set -euo pipefail

KUBECTL="/usr/local/bin/k3s kubectl"
NODE_NAME=$(hostname)

# If k3s is not running, nothing to drain
if ! systemctl is-active --quiet k3s; then
  echo "k3s not running, skipping drain"
  exit 0
fi

echo "Draining node ${NODE_NAME}..."

$KUBECTL drain "${NODE_NAME}" \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --force \
  --timeout=120s \
  --skip-wait-for-delete-timeout=30 \
  2>&1 || echo "Drain timed out or had errors, proceeding with reboot"

echo "Drain complete for ${NODE_NAME}"
'

UNCORDON_SCRIPT='#!/bin/bash
set -euo pipefail

KUBECTL="/usr/local/bin/k3s kubectl"
NODE_NAME=$(hostname)

# Wait for k3s API to be ready
for i in $(seq 1 30); do
  if $KUBECTL get node "${NODE_NAME}" &>/dev/null; then
    break
  fi
  echo "Waiting for k3s API... (${i}/30)"
  sleep 5
done

if $KUBECTL get node "${NODE_NAME}" -o jsonpath='"'"'{.spec.unschedulable}'"'"' 2>/dev/null | grep -q true; then
  echo "Uncordoning node ${NODE_NAME}..."
  $KUBECTL uncordon "${NODE_NAME}"
  echo "Node ${NODE_NAME} uncordoned"
else
  echo "Node ${NODE_NAME} is already schedulable"
fi
'

DRAIN_SERVICE='[Unit]
Description=Drain k3s node before shutdown
DefaultDependencies=no
Before=shutdown.target reboot.target halt.target
Requires=k3s.service
After=k3s.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/k3s-drain-node.sh
TimeoutStartSec=180

[Install]
WantedBy=shutdown.target reboot.target halt.target
'

UNCORDON_SERVICE='[Unit]
Description=Uncordon k3s node after startup
After=k3s.service
Requires=k3s.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/k3s-uncordon-node.sh
ExecStartPre=/bin/sleep 15

[Install]
WantedBy=multi-user.target
'

apply_to_node() {
    local node="$1"
    local host="$2"

    echo "Configuring ${node} (${host})..."

    # Copy scripts
    echo "$DRAIN_SCRIPT" | ssh "core@${host}" "sudo tee /usr/local/bin/k3s-drain-node.sh > /dev/null && sudo chmod 755 /usr/local/bin/k3s-drain-node.sh"
    echo "$UNCORDON_SCRIPT" | ssh "core@${host}" "sudo tee /usr/local/bin/k3s-uncordon-node.sh > /dev/null && sudo chmod 755 /usr/local/bin/k3s-uncordon-node.sh"

    # Create systemd services
    echo "$DRAIN_SERVICE" | ssh "core@${host}" "sudo tee /etc/systemd/system/k3s-drain.service > /dev/null"
    echo "$UNCORDON_SERVICE" | ssh "core@${host}" "sudo tee /etc/systemd/system/k3s-uncordon.service > /dev/null"

    # Enable services
    ssh "core@${host}" "sudo systemctl daemon-reload && \
      sudo systemctl enable k3s-drain.service && \
      sudo systemctl enable k3s-uncordon.service"

    # Run uncordon now in case node was left cordoned
    ssh "core@${host}" "sudo /usr/local/bin/k3s-uncordon-node.sh" || true

    echo "  ✓ ${node}: drain/uncordon services installed and enabled"
}

apply_to_node "buksi"  "buksi.local"
apply_to_node "pamacs" "pamacs.local"
apply_to_node "pufi"   "pufi.local"

echo ""
echo "=== Configuration Complete ==="
echo ""
echo "What happens now:"
echo "  Before reboot: k3s-drain.service runs 'kubectl drain' (120s timeout)"
echo "  After startup:  k3s-uncordon.service runs 'kubectl uncordon'"
echo ""
echo "Verify with:"
echo "  ssh core@<node>.local 'systemctl is-enabled k3s-drain.service'"
echo "  ssh core@<node>.local 'systemctl is-enabled k3s-uncordon.service'"
