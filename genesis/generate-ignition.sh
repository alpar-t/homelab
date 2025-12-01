#!/bin/bash
set -euo pipefail

# Generate Ignition config for a node
# Usage: Set environment variables and run:
#   export NODE_HOSTNAME=odroid-1
#   ./generate-ignition.sh
#
# Optional: export SSH_KEY="$(cat ~/.ssh/other_key.pub)" to use a different key

# Check required environment variables
: "${NODE_HOSTNAME:?NODE_HOSTNAME must be set (e.g., odroid-1)}"

# Auto-detect SSH key if not provided
if [ -z "${SSH_KEY:-}" ]; then
    if [ -f "$HOME/.ssh/id_ed25519.pub" ]; then
        SSH_KEY="$(cat $HOME/.ssh/id_ed25519.pub)"
        echo "Using SSH key: ~/.ssh/id_ed25519.pub"
    elif [ -f "$HOME/.ssh/id_rsa.pub" ]; then
        SSH_KEY="$(cat $HOME/.ssh/id_rsa.pub)"
        echo "Using SSH key: ~/.ssh/id_rsa.pub"
    else
        echo "Error: No SSH key found."
        echo "Generate one with: ssh-keygen -t ed25519"
        echo "Or set SSH_KEY environment variable"
        exit 1
    fi
fi

echo "Generating ignition config for:"
echo "  Hostname: ${NODE_HOSTNAME}"
echo "  Network: DHCP with IPv4 and IPv6"
echo ""

# Check if butane is installed
if ! command -v butane &> /dev/null; then
    echo "Error: butane is not installed."
    echo ""
    echo "Install with:"
    echo "  macOS: brew install butane"
    echo "  Linux: Download from https://github.com/coreos/butane/releases"
    exit 1
fi

# Create temporary file with substituted values
TEMP_FILE=$(mktemp)
cp ignition-template.bu "${TEMP_FILE}"

# Substitute variables
sed -i '' "s|{{NODE_HOSTNAME}}|${NODE_HOSTNAME}|g" "${TEMP_FILE}"
sed -i '' "s|{{SSH_KEY}}|${SSH_KEY}|g" "${TEMP_FILE}"

# Generate ignition JSON
OUTPUT_FILE="ignition-${NODE_HOSTNAME}.json"
butane --pretty --strict < "${TEMP_FILE}" > "${OUTPUT_FILE}"

# Cleanup
rm "${TEMP_FILE}"

echo "✓ Generated: ${OUTPUT_FILE}"
echo ""
echo "Next steps:"
echo "1. Start HTTP server: python3 -m http.server 8000"
echo "2. On Odroid console, run:"
echo "   sudo coreos-installer install /dev/nvme0n1 \\"
echo "     --ignition-url http://YOUR_MAC_IP:8000/${OUTPUT_FILE} \\"
echo "     --insecure-ignition"

