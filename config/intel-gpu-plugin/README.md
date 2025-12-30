# Intel GPU Device Plugin for Kubernetes

Kubernetes device plugin for Intel GPUs. Enables workloads to request GPU resources 
for hardware-accelerated video transcoding (QSV/VAAPI) and compute tasks.

## Overview

The Intel GPU device plugin exposes Intel GPUs as schedulable Kubernetes resources.
This allows pods to request GPU access without privileged mode or special security contexts.

**Resource Types:**
| Resource | Description |
|----------|-------------|
| `gpu.intel.com/i915` | GPU instance via i915 kernel driver |

## Hardware

All Odroid H3+/Ultra nodes in this cluster have:
- **CPU:** Intel Celeron N5105 (Jasper Lake)
- **GPU:** Intel UHD Graphics
- **Capabilities:** H.264, HEVC, VP9 encode/decode; AV1 decode

## Usage

To request a GPU in your workload:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: gpu-workload
spec:
  containers:
    - name: app
      image: your-image
      resources:
        limits:
          gpu.intel.com/i915: 1
```

The device plugin automatically:
- Mounts `/dev/dri` devices into the container
- Sets proper SELinux contexts for device access
- Handles permissions without privileged mode

## Verification

Check if the plugin is running:

```bash
kubectl get pods -n intel-gpu-plugin
```

Check if GPUs are detected on nodes:

```bash
kubectl get nodes -o=jsonpath="{range .items[*]}{.metadata.name}{'\n'}{' i915: '}{.status.allocatable.gpu\.intel\.com/i915}{'\n'}"
```

Expected output:
```
buksi
 i915: 1
pamacs
 i915: 1
pufi
 i915: 1
```

## Shared GPU Access

By default, each GPU can be used by only one container at a time.
For workloads that can share GPUs (e.g., multiple transcode jobs), 
modify the DaemonSet to add `-shared-dev-num` flag:

```yaml
args:
  - "-shared-dev-num=10"  # Allow 10 containers to share each GPU
```

## Troubleshooting

### Pod stuck in Pending with "Insufficient gpu.intel.com/i915"

Check if the GPU plugin is running on all nodes:
```bash
kubectl get pods -n intel-gpu-plugin -o wide
```

Check node allocatable resources:
```bash
kubectl describe node <node-name> | grep -A5 "Allocatable:"
```

### GPU not detected

Verify the GPU device exists on the node:
```bash
kubectl debug node/<node-name> -it --image=busybox -- ls -la /host/dev/dri/
```

Check GPU plugin logs:
```bash
kubectl logs -n intel-gpu-plugin -l app=intel-gpu-plugin
```

## References

- [Intel Device Plugins for Kubernetes](https://github.com/intel/intel-device-plugins-for-kubernetes)
- [GPU Plugin Documentation](https://intel.github.io/intel-device-plugins-for-kubernetes/cmd/gpu_plugin/README.html)
- [Immich Hardware Transcoding](https://immich.app/docs/features/hardware-transcoding/)

