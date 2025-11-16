# HomePBP - Home Personal Build Platform

Self-hosting infrastructure using 3 Odroid nodes running Kubernetes.

## What This Is

A 3-node highly-available Kubernetes cluster on low-power ARM hardware:
- **Talos Linux** - Immutable OS designed for Kubernetes
- **Installed to SSD** - Fast boot, independent operation
- **Longhorn storage** - HDDs provide persistent volumes
- **HA cluster** - Can lose 1 node and stay operational

## Quick Start

```bash
cd genesis
./setup.sh                    # Check prerequisites
./create-usb-installer.sh     # Create USB installer
# Boot Odroids from USB, follow README.md
```

## Architecture

```
3x Odroid Nodes
Each with:
├── SSD: Talos OS + Kubernetes
├── HDD1: Longhorn storage
└── HDD2: Longhorn storage

All 3 = Control Plane + Worker
Total: ~12TB storage across cluster
```

## Status

**Phase 0:** Complete - Ready to install
- USB installer script
- Complete installation guide
- Cluster configuration templates

## Features

- ✅ High availability (can lose 1 node)
- ✅ Immutable OS (no configuration drift)
- ✅ Easy upgrades (`talosctl upgrade`)
- ✅ Low power (~15W total)
- ✅ Enterprise-grade practices

## Installation

See [genesis/README.md](genesis/README.md) for complete step-by-step instructions.

## Goals

- Self-sustaining, resilient infrastructure
- Low maintenance (immutable OS)
- Enterprise-grade practices for home lab
- Learn Kubernetes, Talos, infrastructure-as-code
