# Local-SSD StorageClass

Uses k3s built-in local-path-provisioner for local SSD storage.

## Why Local Storage for Databases?

When an application handles its own HA/replication (like CloudNativePG), adding Longhorn's distributed storage creates redundant complexity:
- Double replication (app + storage layer)
- More failure modes
- Network overhead for storage I/O

Local storage is simpler and faster for these workloads.

## Storage Path

Uses k3s default: `/var/lib/rancher/k3s/storage`

## StorageClass

- **`local-ssd`**: Local storage for PostgreSQL and similar workloads
- **`local-path`**: k3s default (same provisioner, different name)

## Usage

```yaml
spec:
  storage:
    size: 5Gi
    storageClass: local-ssd
```

## References

- [Rancher Local Path Provisioner](https://github.com/rancher/local-path-provisioner)
- [migrate-postgres-to-local-storage.md](../../runbooks/migrate-postgres-to-local-storage.md)

