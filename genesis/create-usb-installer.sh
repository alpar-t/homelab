#!/bin/bash

# Create Talos USB installer for Odroid nodes
# This creates a bootable USB that will install Talos to the Odroid's SSD

set -e

TALOS_VERSION="v1.7.6"
ARCH="arm64"

echo "=================================================="
echo "Talos USB Installer Creator"
echo "=================================================="
echo ""
echo "This will prepare a USB drive to install Talos on Odroids"
echo ""

# Check if running on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "Error: This script is for macOS"
    exit 1
fi

# List available disks
echo "Available disks:"
diskutil list
echo ""

read -p "Enter USB disk (e.g., disk2): " USB_DISK
echo ""

if [[ ! "$USB_DISK" =~ ^disk[0-9]+$ ]]; then
    echo "Error: Invalid disk format. Use 'diskN' format."
    exit 1
fi

# Confirm
echo "⚠️  WARNING: This will ERASE /dev/$USB_DISK"
echo ""
read -p "Are you sure? Type 'yes' to continue: " CONFIRM

if [[ "$CONFIRM" != "yes" ]]; then
    echo "Cancelled"
    exit 1
fi

# Download Talos installer image
echo ""
echo "Downloading Talos ${TALOS_VERSION} installer for ARM64..."
INSTALLER_URL="https://github.com/siderolabs/talos/releases/download/${TALOS_VERSION}/metal-${ARCH}.raw.xz"
INSTALLER_FILE="talos-${TALOS_VERSION}-${ARCH}.raw.xz"

if [[ ! -f "$INSTALLER_FILE" ]]; then
    curl -L "$INSTALLER_URL" -o "$INSTALLER_FILE"
    echo "Downloaded"
else
    echo "Using existing $INSTALLER_FILE"
fi

# Decompress
echo ""
echo "Decompressing..."
if [[ ! -f "talos-${TALOS_VERSION}-${ARCH}.raw" ]]; then
    xz -d -k "$INSTALLER_FILE"
fi

# Unmount the USB
echo ""
echo "Unmounting USB..."
diskutil unmountDisk "/dev/$USB_DISK"

# Write image to USB
echo ""
echo "Writing Talos installer to USB (this takes a few minutes)..."
echo "Progress will not be shown, please wait..."
sudo dd if="talos-${TALOS_VERSION}-${ARCH}.raw" of="/dev/r${USB_DISK}" bs=4m
sync

echo ""
echo "✓ USB installer created successfully!"
echo ""
echo "Next steps:"
echo "1. Eject USB: diskutil eject /dev/$USB_DISK"
echo "2. Insert USB into Odroid"
echo "3. Boot Odroid from USB"
echo "4. Follow installation instructions in README.md"
echo ""

