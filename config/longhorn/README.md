# Longhorn Storage

Distributed block storage for Kubernetes using local HDDs on each node.

## Prerequisites

Each node needs storage disks mounted before Longhorn can use them.

### 1. Check disk layout on each node

```bash
for node in pufi buksi pamacs; do
  echo "=== $node ==="
  ssh core@${node}.local "lsblk -o NAME,SIZE,TYPE,FSTYPE,LABEL,MODEL"
done
```

Identify which disks are available for Longhorn (not the OS disk).

### 2. Run the setup script on each node

Copy and run the script. It auto-discovers available disks (skips root device and mounted disks):

```bash
# Copy script to all nodes
for node in pufi buksi pamacs; do
  scp config/longhorn/setup-node-storage.sh core@${node}.local:/tmp/
done

# Run with auto-discovery (recommended):
ssh -t core@pufi.local "sudo /tmp/setup-node-storage.sh"

# Or specify disks manually:
ssh -t core@pufi.local "sudo DISK1=/dev/sda DISK2=/dev/sdb /tmp/setup-node-storage.sh"
```

The script will show discovered disks and ask for confirmation before formatting.

### 3. Verify mounts

```bash
for node in pufi buksi pamacs; do
  echo "=== $node ==="
  ssh core@${node}.local "df -h /var/mnt/disk1 /var/mnt/disk2"
done
```

## Deployment

Longhorn is deployed via ArgoCD from `apps/longhorn.yaml`.

After ArgoCD syncs, configure Longhorn to use the disks on each node:

```bash
# For nodes with two disks:
kubectl label node <node> node.longhorn.io/create-default-disk=config
kubectl annotate node <node> node.longhorn.io/default-disks-config='[{"path":"/var/mnt/disk1","allowScheduling":true},{"path":"/var/mnt/disk2","allowScheduling":true}]'

# For nodes with one disk:
kubectl label node <node> node.longhorn.io/create-default-disk=config
kubectl annotate node <node> node.longhorn.io/default-disks-config='[{"path":"/var/mnt/disk1","allowScheduling":true}]'
```

## Configuration

Helm values are in `config/longhorn/values.yaml`. Key settings:

- `defaultClassReplicaCount: 3` - Each volume has 3 replicas (one per node)
- `defaultDataPath: /var/mnt/disk1` - Default storage location
- `replicaAutoBalance: best-effort` - Automatically balance replicas across nodes

## Accessing the UI

### Via Authentik (production)

Access at **https://longhorn.newjoy.ro** (requires Authentik setup below).

### Via Port-Forward (local/debugging)

```bash
kubectl port-forward -n longhorn-system svc/longhorn-frontend 8080:80
```

Then open http://localhost:8080

## Authentik Protection Setup

Longhorn has no built-in authentication. We protect it using Authentik's proxy mode.

### How it works

```
User → nginx-ingress → Authentik Outpost → Longhorn
                            ↓
                    (handles auth + proxying)
```

The ingress routes `longhorn.newjoy.ro` to Authentik, which authenticates users
and proxies requests to Longhorn's internal service.

### One-time setup in Authentik UI

**1. Create Provider**
1. Go to **Applications → Providers → Create**
2. Select **Proxy Provider**
3. Configure:
   - Name: `longhorn-proxy`
   - Authorization flow: `default-provider-authorization-implicit-consent`
   - Mode: **Proxy**
   - External host: `https://longhorn.newjoy.ro`
   - Internal host: `http://longhorn-frontend.longhorn-system.svc.cluster.local:80`
4. Click **Create**

**2. Create Application**
1. Go to **Applications → Applications → Create**
2. Configure:
   - Name: `Longhorn`
   - Slug: `longhorn`
   - Provider: select `longhorn-proxy`
   - Launch URL: `https://longhorn.newjoy.ro` (optional, for dashboard)
3. Click **Create**

**3. Add to Outpost**
1. Go to **Applications → Outposts**
2. Click on **authentik Embedded Outpost**
3. In the **Applications** section, add `Longhorn`
4. Click **Update**

### Verify

Visit https://longhorn.newjoy.ro - you should be redirected to Authentik login,
then proxied to the Longhorn UI after authentication

