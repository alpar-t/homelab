# HomePBP Implementation Plan

Building a resilient, low-power home lab using Odroid nodes and Kubernetes.

## Phase 0: Initial Installation ✓ Complete

**Goal:** Install Talos Linux on 3 Odroid nodes

**Implementation:**
- USB installer script for Talos ARM64
- Installation guide tailored to Odroid hardware
- 3-node HA control plane setup
- Longhorn storage configuration

**Architecture:**
- 3x Odroid: Each with SSD (OS) + 2x HDD (storage)
- Talos installed to SSD
- All nodes run control plane + workloads
- Longhorn uses HDDs for persistent volumes

**Key Decisions:**
- ✅ Install to disk (not PXE/stateless)
- ✅ USB installation media (simpler than network boot)
- ✅ 3-node HA control plane (can lose 1 node)
- ✅ Same config for all nodes (symmetric cluster)
- ✅ Longhorn for storage (uses local HDDs)

## Phase 1: Cluster Deployment (Next)

**Goal:** Working 3-node Kubernetes cluster

**Tasks:**
- [ ] Create USB installer
- [ ] Install Talos on all 3 Odroids
- [ ] Generate and apply cluster configuration
- [ ] Bootstrap Kubernetes cluster
- [ ] Verify HA (test node failure)
- [ ] Install Longhorn for persistent storage
- [ ] Test basic deployments

**Success Criteria:**
- All 3 nodes in `Ready` state
- Can lose 1 node without cluster disruption
- Longhorn providing persistent volumes
- Can deploy and scale applications

## Phase 2: Core Services

**Goal:** Production-ready infrastructure services

**Tasks:**
- [ ] Ingress controller (Traefik or Nginx)
- [ ] Cert-manager for TLS certificates
- [ ] External DNS integration
- [ ] Monitoring (Prometheus + Grafana)
- [ ] Logging (Loki)
- [ ] Backup strategy for etcd

## Phase 3: Application Deployment

**Goal:** Self-hosted services

**Candidates:**
- github for git hosting (will not self host this part)
- CD with Argo CD
- Container registry
- Documentation (Wiki.js or similar)
- Personal services (as needed)

## Phase 4: Automation & GitOps

**Goal:** Infrastructure as code

**Tasks:**
- [ ] Terraform for infrastructure
- [ ] Ansible for configuration (if needed)
- [ ] GitOps with Argo CD or Flux
- [ ] Automated Talos updates
- [ ] Automated application deployments

## Hardware

**Current Setup:**
- 3x Odroid nodes (N2+, HC4, or M1)
- Each with: 2-4GB RAM, 1 SSD, 2 HDDs
- Total storage: ~12TB (6x 2TB HDDs)

**Per Node:**
```
SSD (256GB): Talos OS + system
HDD1 (2TB): Longhorn storage
HDD2 (2TB): Longhorn storage
```

## Design Principles

1. **Resilience First**: Can tolerate 1 node failure
2. **Simple Operation**: No TFTP dependency, boots from disk
3. **Minimal Maintenance**: Immutable OS, easy upgrades
4. **Low Power**: ~5W per Odroid, ~15W total cluster
5. **Enterprise Practices**: HA, monitoring, backups, GitOps

## Why These Choices?

**Talos vs Traditional Linux:**
- No SSH = smaller attack surface
- Immutable = consistent, predictable
- API-driven = automatable
- Built for Kubernetes = optimized

**Install to Disk vs Network Boot:**
- Simpler daily operation
- No TFTP server dependency
- Faster boot
- Still easy upgrades via `talosctl`
- Can reinstall from USB if needed

**3 Control Planes vs 1+2:**
- True HA (etcd quorum)
- Can lose 1 node
- No single point of failure
- Minimal resource overhead

## Current Status

**Phase 0:** ✓ Complete
- USB installer script ready
- Installation documentation complete
- Configuration templates ready

**Ready for:** Phase 1 - Install on actual hardware
