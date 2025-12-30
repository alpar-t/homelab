#!/bin/bash
set -euo pipefail

# Apply Zincati (CoreOS auto-update) configuration to running nodes
# This staggers update windows to prevent simultaneous reboots
#
# Usage: ./apply-zincati-config.sh
#
# This script:
# 1. Creates the Zincati config on each node with different update days
# 2. Restarts the Zincati service to apply changes
#
# Update schedule:
#   buksi  - Tuesdays   03:00-05:00 UTC
#   pamacs - Wednesdays 03:00-05:00 UTC
#   pufi   - Thursdays  03:00-05:00 UTC

echo "=== Applying Zincati Update Configuration ==="
echo ""
echo "This will configure staggered update windows to prevent"
echo "simultaneous reboots that break Kubernetes cluster quorum."
echo ""

apply_config() {
    local node="$1"
    local host="$2"
    local day="$3"
    
    echo "Configuring ${node} (${host}) - Updates on ${day}..."
    
    # Create config content
    local config="[updates]
# Use periodic strategy - only reboot during maintenance windows
strategy = \"periodic\"

[[updates.periodic.window]]
# Maintenance window: 3 AM - 5 AM UTC on ${day}
days = [ \"${day}\" ]
start_time = \"03:00\"
length_minutes = 120
"
    
    # Apply to node
    ssh "core@${host}" "sudo mkdir -p /etc/zincati/config.d && cat > /tmp/zincati-config.toml << 'EOF'
${config}
EOF
sudo mv /tmp/zincati-config.toml /etc/zincati/config.d/51-cluster-updates.toml"
    
    # Restart Zincati to apply
    ssh "core@${host}" "sudo systemctl restart zincati"
    
    # Verify
    local status
    status=$(ssh "core@${host}" "sudo systemctl is-active zincati")
    if [ "$status" = "active" ]; then
        echo "  ✓ ${node}: Zincati configured and running"
    else
        echo "  ✗ ${node}: Zincati status: ${status}"
    fi
}

# Apply to each node with different update days
apply_config "buksi"  "buksi.local"  "Tue"
apply_config "pamacs" "pamacs.local" "Wed"
apply_config "pufi"   "pufi.local"   "Thu"

echo ""
echo "=== Configuration Complete ==="
echo ""
echo "Update windows (3:00-5:00 AM UTC):"
echo "  buksi  - Tuesdays"
echo "  pamacs - Wednesdays"
echo "  pufi   - Thursdays"
echo ""
echo "Verify with: ssh core@<node>.local 'cat /etc/zincati/config.d/51-cluster-updates.toml'"
