# HomePBP Setup Guide

Simple network boot setup for installing Ubuntu on your homelab nodes.

## Overview

This setup provides network boot capability using netboot.xyz, which includes Ubuntu Server installers and many other useful tools. No complex configuration needed - netboot.xyz comes with everything built-in.

## Requirements

- 3 physical nodes with dual NICs
- MikroTik router with DHCP server
- Docker on your laptop/desktop (for TFTP server)

## 1. TFTP Server Setup

### Download netboot.xyz Boot File
```bash
mkdir tftpboot && cd tftpboot
wget https://boot.netboot.xyz/ipxe/netboot.xyz-undionly.kpxe -O undionly.kpxe
```

### Start the TFTP Server
```bash
docker-compose up -d
```

This starts a simple TFTP server that serves the netboot.xyz boot file.

### Verify Setup
```bash
# Check the service is running
docker-compose ps

# Check the netboot.xyz file exists
ls -la tftpboot/undionly.kpxe
```

## 2. MikroTik Router Configuration

### Configure DHCP Server for Network Boot

Connect to your MikroTik router and run these commands:

```routeros
# Set your genesis server IP (replace 192.168.1.100 with your actual IP)
/ip dhcp-server option
add code=66 name=tftp-server value="192.168.1.100"
add code=67 name=boot-file value="undionly.kpxe"

# Apply to your DHCP server (replace "dhcp1" with your DHCP server name)
/ip dhcp-server
set dhcp1 dhcp-option=tftp-server,boot-file

# Alternative single-line method:
/ip dhcp-server set dhcp1 next-server=192.168.1.100 boot-file-name=undionly.kpxe
```

### Verify DHCP Configuration
```routeros
/ip dhcp-server print detail
```

You should see:
- `next-server: 192.168.1.100` (your genesis server IP)
- `boot-file-name: undionly.kpxe`

## 3. Node Installation Process

### For Each Node:

1. **Boot the node** - It will network boot and show the netboot.xyz menu
2. **Select "Linux Network Installs" → "Ubuntu" → "22.04 LTS Server"**
3. **During Ubuntu installation, create custom partitions:**

```
SSD (/dev/sda):
├── /dev/sda1 - 1GB   - EFI System Partition
├── /dev/sda2 - 50GB  - / (root filesystem, ext4)
├── /dev/sda3 - 20GB  - /var/lib/rancher/k3s (k3s data, ext4)
└── /dev/sda4 - Rest  - Longhorn SSD storage (leave unformatted)

HDD (/dev/sdb):
└── /dev/sdb1 - All   - Longhorn HDD storage (leave unformatted)
```

4. **Configure networking during install:**
   - Control plane NIC: DHCP or static (192.168.1.101/102/103)
   - Storage NIC: Configure later

5. **Create user:** `ubuntu` with your SSH key

6. **Complete installation and reboot**

### Post-Installation Setup

Run on each node after installation:

```bash
# Download and run post-install script
curl -O https://raw.githubusercontent.com/yourusername/homepbp/main/scripts/post-install-node.sh
chmod +x post-install-node.sh
sudo ./post-install-node.sh k8s-node01  # Change to node02, node03
```

### Configure Storage Network

Copy the netplan template and customize for each node:

```bash
# On each node, edit /etc/netplan/01-netcfg.yaml
sudo vim /etc/netplan/01-netcfg.yaml
```

Use this template (adjust IPs per node):
```yaml
network:
  version: 2
  ethernets:
    # Control plane NIC (adjust interface name)
    enp1s0:
      dhcp4: true
    
    # Storage NIC (adjust interface name and IP per node)  
    enp2s0:
      addresses: [192.168.2.101/24]  # .101 for node01, .102 for node02, etc
```

Apply the configuration:
```bash
sudo netplan apply
```

### Set up SSH access

From your laptop:
```bash
ssh-copy-id ubuntu@192.168.1.101
ssh-copy-id ubuntu@192.168.1.102
ssh-copy-id ubuntu@192.168.1.103
```

## 4. Verification

### Test network boot:
1. Boot a node
2. Should see netboot.xyz menu
3. Navigate to Ubuntu installer

### Test SSH access:
```bash
ssh ubuntu@192.168.1.101
ssh ubuntu@192.168.1.102  
ssh ubuntu@192.168.1.103
```

### Check partitioning:
```bash
# On each node
lsblk
df -h
```

Should show:
- `/` mounted on /dev/sda2
- `/var/lib/rancher/k3s` mounted on /dev/sda3
- Unformatted /dev/sda4 and /dev/sdb1 for Longhorn

## Next Steps

After all nodes are set up:
1. Deploy K3s cluster using Ansible
2. Configure Longhorn storage
3. Set up ArgoCD for GitOps

## Troubleshooting

### Node won't network boot:
- Check DHCP server configuration
- Verify TFTP server is running: `docker-compose ps`
- Check network connectivity to genesis server

### Can't reach netboot.xyz menu:
- Verify internet connectivity from nodes
- Check if firewall is blocking HTTPS

### Storage partitions:
- Don't format Longhorn partitions during OS install
- Longhorn will handle formatting and mounting
- Keep partitions unformatted until Longhorn deployment
