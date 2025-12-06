#!/bin/bash
# Setup Longhorn storage disks on CoreOS nodes
# Run this script on each node to configure HDDs for Longhorn

set -euo pipefail

# Configuration - adjust these for your nodes
DISK1="${DISK1:-/dev/sda}"
DISK2="${DISK2:-/dev/sdb}"
MOUNT1="/var/mnt/disk1"
MOUNT2="/var/mnt/disk2"

echo "=== Longhorn Storage Setup ==="
echo ""
echo "Current disk layout:"
lsblk -o NAME,SIZE,TYPE,FSTYPE,LABEL,MOUNTPOINT,MODEL
echo ""

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root (use sudo)"
    exit 1
fi

# Safety check - ensure disks exist and aren't mounted
check_disk() {
    local disk=$1
    local label=$2
    
    if [[ ! -b "$disk" ]]; then
        echo "ERROR: $disk does not exist"
        exit 1
    fi
    
    if mount | grep -q "^$disk"; then
        echo "ERROR: $disk is currently mounted. Unmount first or choose a different disk."
        exit 1
    fi
    
    # Check for existing partitions that might be mounted
    if mount | grep -q "^${disk}[0-9]"; then
        echo "ERROR: A partition on $disk is currently mounted."
        exit 1
    fi
}

echo "Will configure:"
echo "  $DISK1 -> $MOUNT1 (label: longhorn-disk1)"
echo "  $DISK2 -> $MOUNT2 (label: longhorn-disk2)"
echo ""
echo "WARNING: This will FORMAT the disks and DESTROY all data!"
echo ""
read -p "Continue? (yes/no): " confirm

if [[ "$confirm" != "yes" ]]; then
    echo "Aborted."
    exit 0
fi

check_disk "$DISK1" "longhorn-disk1"
check_disk "$DISK2" "longhorn-disk2"

echo ""
echo "Formatting disks..."
mkfs.ext4 -F -L longhorn-disk1 "$DISK1"
mkfs.ext4 -F -L longhorn-disk2 "$DISK2"

echo "Creating mount points..."
mkdir -p "$MOUNT1" "$MOUNT2"

echo "Creating systemd mount units..."
cat > /etc/systemd/system/var-mnt-disk1.mount << 'EOF'
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

cat > /etc/systemd/system/var-mnt-disk2.mount << 'EOF'
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

echo "Enabling and starting mounts..."
systemctl daemon-reload
systemctl enable --now var-mnt-disk1.mount var-mnt-disk2.mount

echo ""
echo "=== Setup complete ==="
echo ""
df -h "$MOUNT1" "$MOUNT2"

