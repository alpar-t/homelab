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
- [x] backups for longhorn volumes (also backup k8s secrets - needed for disaster recovery)
- [ ] How do we keep everything up-to-date
- [X] Add email relay (Stalwart → Migadu) - consolidated into stalwart-mail
- [ ] Add external heartbeat / down detection 
- [ ] Monitor mail
- [x] Replace Authentik with Pocket ID
- [ ] **Migrate PostgreSQL from Longhorn to local storage** - see [runbooks/migrate-postgres-to-local-storage.md](runbooks/migrate-postgres-to-local-storage.md)
  - Eliminates redundant replication (CNPG already handles HA)
  - Better performance (direct SSD access)
  - Simpler architecture (fewer moving parts)
- [ ] **Set single-replica for rebuildable Longhorn volumes** - save ~115Gi storage
  - `immich-thumbs` (100Gi) - regenerated from photos
  - `immich-model-cache` (10Gi) - downloaded from internet
  - `paperless-data` (5Gi) - search index, rebuildable from media
  - `paperless-export` (5Gi) - generated exports
  - Add annotation: `longhorn.io/number-of-replicas: "1"`
- [ ] **Remove duplicate Longhorn StorageClass files** - cleanup
  - Delete `config/longhorn/storageclass-ssd.yaml` (keep `manifests/` version)
  - Delete `config/longhorn/storageclass-hdd.yaml` (keep `manifests/` version)
- [x] **Pi-hole DNS redundancy** - see [runbooks/pihole-dns-redundancy.md](runbooks/pihole-dns-redundancy.md)
- [x] **Graceful node reboots for Zincati/CoreOS updates**
  - Added `k3s-drain.service`: runs `kubectl drain` before shutdown/reboot (120s timeout)
  - Added `k3s-uncordon.service`: runs `kubectl uncordon` after k3s starts back up
  - Added PodDisruptionBudgets for cloudflare-tunnel and ingress-nginx (minAvailable: 1)
  - Drain scripts baked into ignition template for new nodes
  - Run `genesis/apply-drain-config.sh` to apply to existing nodes
  - Reboots already staggered across Tue/Wed/Thu via Zincati config
- [ ] **Test graceful drain/uncordon on a single node**
  - Run `genesis/apply-drain-config.sh` to install services on all nodes
  - SSH into one node and verify services are enabled: `systemctl is-enabled k3s-drain.service k3s-uncordon.service`
  - Reboot one node: `sudo systemctl reboot`
  - Watch from another node: `kubectl get nodes -w` — should see node go `SchedulingDisabled` before disappearing, then come back `Ready`
  - Verify pods migrated gracefully: `kubectl get events --field-selector reason=Evicted -A`
  - Verify PDBs are respected: `kubectl get pdb -A`
  - Repeat for each node on separate days

**Tasks:**
- [ ] Monitoring (Prometheus + Grafana)
- [ ] Logging (Loki)
- [ ] Add argoCD to pocket id 

**APPS:**

- [x] Omada
- [X] OTMonitor
- [x] Bitwarden (Vaultwarden)
- [x] ownCloud Infinite Scale (drive.newjoy.ro)
- [x] Immich (photos.newjoy.ro)
- [x] Node Red
- [x] Paperless-ngx

- [x] Emby
- [x] Frigate
- [ ] VPN (Headscale with Pocket ID) — manifests deployed, not yet working
- [ ] Deploy [TREK](https://github.com/mauriceboe/TREK) — holiday / trip planner
- [x] Configure arr stack (Sonarr/Radarr/Prowlarr) with Emby
- [ ] Configure private network access through Headscale
- [ ] AI agent: Claude-powered WhatsApp chatbot hooked to [alpar-t/life](https://github.com/alpar-t/life)

## Version Upgrades (audited 2026-04-12)

**Critical:**
- [x] **k3s v1.31 → v1.34.6** — done 2026-04-13, via System Upgrade Controller
- [x] **ArgoCD v3.2.1 → v3.2.8** — done 2026-04-12
- [x] **CloudNativePG 1.25 → 1.29.0** — done 2026-04-13, sequential upgrade
- [ ] **ingress-nginx → migrate away** — project archived, evaluate alternatives

**Important:**
- [ ] OpenCloud 4.1.0 → 6.0.0
- [ ] Longhorn 1.8.1 → 1.11
- [ ] OnlyOffice 8.2.2 → 9.3
- [ ] Velero 1.15 → 1.18
- [ ] Apache Tika 2.9.2.1 → 3.3

**Routine:**
- [ ] Immich, Frigate, Dex, Pi-hole, Cloudflared, Reloader, Forecastle

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

