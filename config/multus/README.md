# Multus CNI

Multus CNI is a meta-plugin that enables attaching multiple network interfaces to pods in Kubernetes.

## Purpose

We use Multus to provide Longhorn with a dedicated storage network (`enp1s0` / 192.168.42.0/24) separate from the default cluster network.

## Deployment

Multus is deployed via ArgoCD from `apps/multus.yaml`.

The manifest in `manifests/multus-daemonset.yaml` is the "thick plugin" version from the upstream Multus repository.

## How it works

1. Multus installs as a DaemonSet on every node
2. It creates the `NetworkAttachmentDefinition` CRD
3. Pods can request additional network interfaces via annotations
4. Longhorn's instance-manager pods use this to get a second interface on the storage network

## Verification

Check Multus pods are running:

```bash
kubectl get pods -n kube-system -l app=multus
```

Check the CRD is installed:

```bash
kubectl get crd network-attachment-definitions.k8s.cni.cncf.io
```

## Updating

To update Multus:

```bash
# Download new version
curl -sL "https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/master/deployments/multus-daemonset-thick.yml" \
  -o config/multus/manifests/multus-daemonset.yaml

# Commit and push - ArgoCD will sync
```

## References

- [Multus CNI GitHub](https://github.com/k8snetworkplumbingwg/multus-cni)
- [Longhorn Storage Network](https://longhorn.io/docs/1.10.1/advanced-resources/deploy/storage-network/)

