# HomePBP - Homelab Kubernetes Cluster

This repository contains the infrastructure and configurations for a self-hosted Kubernetes system for homelab use, featuring:

- **Network boot with iPXE** - Diskless boot capabilities with fallback
- **Automated node provisioning** - Zero-touch configuration of nodes
- **High-availability K3s** - All nodes participate in the control plane
- **Smart auto-discovery** - Nodes find and join the cluster automatically
- **Power-failure resilient** - Handles concurrent boot scenarios elegantly
- **GitOps ready** - Prepared for ArgoCD integration

## Architecture

The system consists of:

1. **Genesis Server**: A Docker Compose setup that runs on a laptop or desktop to provide:
   - iPXE boot services via TFTP and HTTP
   - Cloud-init configuration delivery

2. **Nodes**: Physical or virtual machines that:
   - Network boot via iPXE
   - Auto-configure using cloud-init
   - Form a k3s Kubernetes cluster
   - Use local disk fallback for reliability

## Requirements

- External DHCP server (configured to point to the Genesis server for network booting)
- Ubuntu 20.04 LTS (used as the node OS)
- k3s (lightweight Kubernetes distribution)
- Physical or virtual machines for the nodes

## Dependencies

- Docker (for TFTP server)
- MikroTik router or other DHCP server that supports network boot options

## Directory Structure

```
infrastructure/
├── genesis/              # Genesis server components
│   ├── docker-compose.yml     # Docker services for network booting
│   ├── setup-genesis.sh       # Script to set up the Genesis environment
│   ├── generate-node-config.sh # Script to generate per-node cloud-init configs
│   ├── ipxe/                 # iPXE boot files
│   │   ├── http/             # Files served via HTTP
│   │   └── tftpboot/         # Files served via TFTP
│   └── cloud-init/           # Cloud-init configurations
```

## Getting Started

### Setting up the Genesis Server

1. Clone this repository
2. Run the setup script:

```bash
cd infrastructure/genesis
./setup-genesis.sh
```

3. Start the services:

```bash
docker-compose up -d
```

### Generating Node Configurations

#### High-Availability Architecture

The system implements a fully resilient high-availability K3s cluster where:

- **All nodes are servers** - Every node participates in the control plane
- **No single point of failure** - The cluster survives if any node goes down
- **Embedded etcd database** - For reliable distributed state management
- **Self-healing** - Cluster recovers automatically after outages or power failures

#### Smart Auto-Discovery

Nodes feature a sophisticated auto-discovery system that:

1. Scans the network for existing K3s servers
2. Automatically joins existing clusters when found
3. Creates a new cluster if none exists after multiple checks
4. Uses random delays to prevent "split-brain" during concurrent boot scenarios
5. Performs final verification before cluster initialization

#### Power Failure Recovery

In case of full power outage where all nodes boot simultaneously:

1. All nodes scan the network for existing clusters
2. Each node waits a random period before attempting to initialize
3. Usually the first node to complete scanning becomes the initial server
4. Other nodes detect the first server and join it
5. This prevents multiple clusters from forming

#### Usage

To generate cloud-init configurations for nodes:

```bash
# Generate configuration for a node (will auto-discover)
./generate-node-config.sh <hostname> [<ssh-public-key-path>]

# Generate configuration with hints about existing servers
./generate-node-config.sh <hostname> [<ssh-public-key-path>] <known-server-ips>
```

The system will automatically detect common SSH key locations if not specified.

#### Examples

```bash
# Generate config for a node (auto-discovers SSH key)
./generate-node-config.sh k8s-node01

# Generate config with explicit SSH key path
./generate-node-config.sh k8s-node02 ~/.ssh/custom_key.pub

# Generate config with preferred server IPs
./generate-node-config.sh k8s-node03 192.168.1.101,192.168.1.102

# Generate config with both custom key and preferred servers
./generate-node-config.sh k8s-node04 ~/.ssh/id_ed25519.pub 192.168.1.101,192.168.1.102
```

### DHCP Configuration

Configure your DHCP server to include the following options:

- Next-server: IP address of your Genesis server
- Filename: "boot.ipxe"

## Network Boot Process

1. Node powers on and requests network boot from DHCP server
2. DHCP server directs the node to the TFTP server for the iPXE binary (`undionly.kpxe`)
3. iPXE binary is loaded, providing HTTP boot capabilities
4. The iPXE script (`boot.ipxe`) is executed, which loads Ubuntu kernel and initrd over HTTP
5. Cloud-init configuration is applied during boot using node-specific configs
6. Node either joins an existing k3s cluster or forms a new one

## Local Disk Fallback

During the first boot, the system will:
1. Partition local storage as needed
2. Create a local boot partition
3. Install a bootloader configured to boot locally
4. Cache the k3s images for offline use

## Future Additions

- GitOps setup with ArgoCD
- Longhorn storage configuration
- Ingress setup with HTTPS
- Recovery mode for maintenance
