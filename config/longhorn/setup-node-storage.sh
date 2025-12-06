#!/bin/bash
# Setup Longhorn storage disks on CoreOS nodes
# Run this script on each node to configure HDDs for Longhorn
#
# Usage:
#   Auto-discover available disks:
#     sudo ./setup-node-storage.sh
#
#   Specify disks manually:
#     sudo DISK1=/dev/sda DISK2=/dev/sdb ./setup-node-storage.sh

set -euo pipefail

MOUNT_BASE="/var/mnt"

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

# Find the root device (to exclude it)
ROOT_DEV=$(lsblk -n -o PKNAME "$(findmnt -n -o SOURCE /)" 2>/dev/null | head -1 || echo "")
if [[ -z "$ROOT_DEV" ]]; then
    # Fallback: try to find from /sysroot (CoreOS)
    ROOT_DEV=$(lsblk -n -o PKNAME "$(findmnt -n -o SOURCE /sysroot 2>/dev/null)" 2>/dev/null | head -1 || echo "")
fi

echo "Root device: ${ROOT_DEV:-unknown}"
echo ""

# Auto-discover available disks
discover_disks() {
    local available=()
    
    # Get all disk devices
    while IFS= read -r line; do
        local name size type model fstype
        read -r name size type fstype model <<< "$line"
        
        [[ "$type" != "disk" ]] && continue
        [[ -z "$name" ]] && continue
        
        local dev="/dev/$name"
        
        # Skip if it's the root device
        if [[ "$name" == "$ROOT_DEV" ]]; then
            echo "  Skipping $dev - root device" >&2
            continue
        fi
        
        # Skip if any partition is mounted
        if lsblk -n -o MOUNTPOINT "$dev" 2>/dev/null | grep -q '/'; then
            echo "  Skipping $dev - has mounted partitions" >&2
            continue
        fi
        
        # Skip if already labeled as longhorn disk
        local label
        label=$(lsblk -n -o LABEL "$dev" 2>/dev/null | head -1)
        if [[ "$label" =~ ^longhorn-disk ]]; then
            echo "  Skipping $dev - already configured for Longhorn" >&2
            continue
        fi
        
        # Warn about RAID member disks
        if [[ "$fstype" == "ddf_raid_member" || "$fstype" == "linux_raid_member" ]]; then
            echo "  WARNING: $dev appears to be a RAID member ($fstype)" >&2
            echo "           Make sure you want to destroy the RAID array!" >&2
        fi
        
        echo "  Found: $dev ($size) - ${model:-unknown}" >&2
        available+=("$dev")
    done < <(lsblk -d -n -o NAME,SIZE,TYPE,FSTYPE,MODEL 2>/dev/null)
    
    # Output only the device paths (to stdout)
    printf '%s\n' "${available[@]}"
}

# Get disks - either from environment or auto-discover
DISKS=()
if [[ -n "${DISK1:-}" ]]; then
    DISKS+=("$DISK1")
    [[ -n "${DISK2:-}" ]] && DISKS+=("$DISK2")
    [[ -n "${DISK3:-}" ]] && DISKS+=("$DISK3")
    [[ -n "${DISK4:-}" ]] && DISKS+=("$DISK4")
    echo "Using manually specified disks: ${DISKS[*]}"
else
    echo "Auto-discovering available disks..."
    while IFS= read -r disk; do
        [[ -n "$disk" ]] && DISKS+=("$disk")
    done < <(discover_disks)
    echo ""
fi

if [[ ${#DISKS[@]} -eq 0 ]]; then
    echo "No available disks found!"
    echo ""
    echo "To specify disks manually:"
    echo "  DISK1=/dev/sdX [DISK2=/dev/sdY] $0"
    exit 1
fi

# Safety check - ensure disk exists and isn't mounted
check_disk() {
    local disk=$1
    
    if [[ ! -b "$disk" ]]; then
        echo "ERROR: $disk does not exist"
        exit 1
    fi
    
    if mount | grep -q "^$disk "; then
        echo "ERROR: $disk is currently mounted. Unmount first or choose a different disk."
        exit 1
    fi
    
    # Check for existing partitions that might be mounted
    if mount | grep -q "^${disk}[0-9p]"; then
        echo "ERROR: A partition on $disk is currently mounted."
        exit 1
    fi
}

echo "Will configure ${#DISKS[@]} disk(s):"
for i in "${!DISKS[@]}"; do
    num=$((i + 1))
    echo "  ${DISKS[$i]} -> ${MOUNT_BASE}/disk${num} (label: longhorn-disk${num})"
done
echo ""
echo "WARNING: This will FORMAT the disks and DESTROY all data!"
echo ""
read -p "Continue? (yes/no): " confirm

if [[ "$confirm" != "yes" ]]; then
    echo "Aborted."
    exit 0
fi

# Check all disks first
for disk in "${DISKS[@]}"; do
    check_disk "$disk"
done

MOUNTS_TO_ENABLE=""

for i in "${!DISKS[@]}"; do
    num=$((i + 1))
    disk="${DISKS[$i]}"
    mount_point="${MOUNT_BASE}/disk${num}"
    label="longhorn-disk${num}"
    unit_name="var-mnt-disk${num}.mount"
    
    echo ""
    echo "Configuring $disk..."
    
    # Wipe any existing signatures (RAID, filesystem, etc)
    echo "  Wiping existing signatures..."
    wipefs -a "$disk" || true
    
    echo "  Formatting as ext4 with label $label..."
    mkfs.ext4 -F -L "$label" "$disk"
    
    echo "  Creating mount point $mount_point..."
    mkdir -p "$mount_point"
    
    echo "  Creating systemd mount unit..."
    cat > "/etc/systemd/system/${unit_name}" << EOF
[Unit]
Description=Mount Longhorn Disk ${num}
Before=local-fs.target

[Mount]
What=/dev/disk/by-label/${label}
Where=${mount_point}
Type=ext4
Options=defaults,noatime

[Install]
WantedBy=local-fs.target
EOF
    
    MOUNTS_TO_ENABLE="$MOUNTS_TO_ENABLE $unit_name"
done

echo ""
echo "Enabling and starting mounts..."
systemctl daemon-reload
systemctl enable --now $MOUNTS_TO_ENABLE

echo ""
echo "=== Setup complete ==="
echo ""
for i in "${!DISKS[@]}"; do
    num=$((i + 1))
    df -h "${MOUNT_BASE}/disk${num}"
done

echo ""
echo "To configure Longhorn to use these disks, run on your workstation:"
echo ""
NODE_NAME=$(hostname)
echo "  kubectl label node ${NODE_NAME} node.longhorn.io/create-default-disk=config"
paths=""
for i in "${!DISKS[@]}"; do
    num=$((i + 1))
    [[ -n "$paths" ]] && paths="$paths,"
    paths="$paths{\"path\":\"${MOUNT_BASE}/disk${num}\",\"allowScheduling\":true}"
done
echo "  kubectl annotate node ${NODE_NAME} node.longhorn.io/default-disks-config='[${paths}]'"
