# HomePBP Implementation Plan

Building a resilient, low-power home lab using Odroid nodes and Kubernetes.

## Phase 0: Initial Installation ✓ Complete

**Implementation:**
- name resolution for the cluster ( baxter.local ) 
- ArgoCD setup
- Longhorn storage configuration

**Architecture:**
- 3x Odroid: Each with SSD (OS) + 2x HDD (storage)
- Fedora CoreOS with k3s installed to SSD 
- All nodes run control plane + workloads
- Longhorn uses HDDs and SSDs for persistent volumes

**Key Decisions:**
- ✅ Install to disk (not PXE/stateless)
- ✅ 3-node HA control plane (can lose 1 node)
- ✅ Same config for all nodes (symmetric cluster)
- ✅ Longhorn for storage (uses local HDDs and SSD)

## Phase 1: Cluster Deployment (Next)

**Goal:** Working 3-node Kubernetes cluster

**Tasks:**
- [X] Verify HA (test node failure)
- [X] Install and configure ARgoCD 
- [x] Install Longhorn with ARgoCD for persistent storage
- [x] Test basic deployments

**Success Criteria:**
- All 3 nodes in `Ready` state
- Can lose 1 node without cluster disruption
- Longhorn providing persistent volumes
- Can deploy and scale applications

## Phase 2: Core Services

**Goal:** Production-ready infrastructure services


**Follow-ups:**

- [ ] how do I monitor the disks e.g. for failure and nottify on them 
- [ ] backups for longhorn volumes (also backup k8s secrets - needed for disaster recovery) 
- [ ] How do we keep everything up-to-date
- [X] Add email relay (Stalwart → Migadu) - consolidated into stalwart-mail
- [ ] Add external heartbeat / down detection 
- [ ] Monitor mail
- [ ] Replace Authentik with Pocket ID
- [ ] 

**Tasks:**
- [ ] Monitoring (Prometheus + Grafana)
- [ ] Logging (Loki)
- [ ] Add argoCD to pocket id 

**APPS:**

- [x] Omada
- [X] OTMonitor
- [ ] Bitwarden
- [X] ownCloud Infinite Scale (drive.newjoy.ro) - manifests created, needs OIDC secret
- [ ] Photoprism or Immich
- [ ] Node Red
- [x] Paperless-ngx 

- [ ] Emby
- [ ] Frigate
- [ ] VPN ( Headscale with PokcetId ?)

## Hardware

**Current Setup:**
- 2x Odroid H3+ (16GB RAM each)
- 1x Odroid H3 Ultra (32GB RAM)
- Each with: 1 SSD, 2 HDDs
- Total: 64GB RAM, ~12TB storage (6x 2TB HDDs)

**Per Node:**
```
SSD (256GB): CoreOS + system + default Longhorn volume
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

