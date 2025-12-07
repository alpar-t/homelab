#!/bin/bash
# Tag Longhorn disks for SSD vs HDD storage classes
# Run this after Longhorn is installed and nodes are registered
#
# Usage: ./tag-disks.sh [kubeconfig]
#   kubeconfig: Path to kubeconfig file (default: ../../genesis/kubeconfig)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KUBECONFIG="${1:-$SCRIPT_DIR/../../genesis/kubeconfig}"

if [[ ! -f "$KUBECONFIG" ]]; then
    echo "Error: kubeconfig not found at $KUBECONFIG"
    exit 1
fi

export KUBECONFIG

echo "=== Current Longhorn Disk Configuration ==="
kubectl get nodes.longhorn.io -n longhorn-system -o json | \
    jq -r '.items[] | "\(.metadata.name):", (.spec.disks | to_entries[] | "  \(.key): \(.value.path) tags=\(.value.tags // [])")'

echo ""
echo "=== Tagging HDD disks (at /var/mnt/*) ==="

# Get all nodes and their disks, tag disks at /var/mnt/* as "hdd"
for node in $(kubectl get nodes.longhorn.io -n longhorn-system -o jsonpath='{.items[*].metadata.name}'); do
    echo "Processing node: $node"
    
    # Get disk names for disks at /var/mnt/*
    disks=$(kubectl get nodes.longhorn.io -n longhorn-system $node -o json | \
        jq -r '.spec.disks | to_entries[] | select(.value.path | startswith("/var/mnt/")) | .key')
    
    for disk in $disks; do
        echo "  Tagging disk $disk as hdd"
        kubectl -n longhorn-system patch nodes.longhorn.io $node --type=json \
            -p="[{\"op\": \"replace\", \"path\": \"/spec/disks/$disk/tags\", \"value\": [\"hdd\"]}]"
    done
done

echo ""
echo "=== Adding SSD storage from root filesystem ==="
echo "Note: This adds /var/lib/longhorn-ssd as SSD storage on each node"

# Add SSD disk on each node using root filesystem
# The path /var/lib/longhorn-ssd should be on the SSD (boot disk)
for node in $(kubectl get nodes.longhorn.io -n longhorn-system -o jsonpath='{.items[*].metadata.name}'); do
    echo "Adding SSD disk to node: $node"
    
    # Check if ssd disk already exists
    existing=$(kubectl get nodes.longhorn.io -n longhorn-system $node -o json | \
        jq -r '.spec.disks | keys[] | select(. == "ssd-disk")' || true)
    
    if [[ -n "$existing" ]]; then
        echo "  SSD disk already exists, updating tags"
        kubectl -n longhorn-system patch nodes.longhorn.io $node --type=json \
            -p='[{"op": "replace", "path": "/spec/disks/ssd-disk/tags", "value": ["ssd"]}]'
    else
        echo "  Adding new SSD disk"
        kubectl -n longhorn-system patch nodes.longhorn.io $node --type=merge -p='{
            "spec": {
                "disks": {
                    "ssd-disk": {
                        "allowScheduling": true,
                        "evictionRequested": false,
                        "path": "/var/lib/longhorn-ssd",
                        "storageReserved": 0,
                        "tags": ["ssd"]
                    }
                }
            }
        }'
    fi
done

echo ""
echo "=== Final Disk Configuration ==="
kubectl get nodes.longhorn.io -n longhorn-system -o json | \
    jq -r '.items[] | "\(.metadata.name):", (.spec.disks | to_entries[] | "  \(.key): \(.value.path) tags=\(.value.tags // [])")'

echo ""
echo "=== Next Steps ==="
echo "1. SSH to each node and create the SSD directory:"
echo "   sudo mkdir -p /var/lib/longhorn-ssd"
echo ""
echo "2. Apply the StorageClasses:"
echo "   kubectl apply -f config/longhorn/storageclass-ssd.yaml"
echo "   kubectl apply -f config/longhorn/storageclass-hdd.yaml"

