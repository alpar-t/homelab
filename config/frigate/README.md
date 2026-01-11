# Frigate NVR

AI-powered Network Video Recorder with Intel QSV hardware acceleration.

## Overview

- **3x 4K cameras**: front, gate, back
- **Motion-based recording**: ~14 days retention with 500GB storage
- **Intel QSV acceleration**: Hardware-accelerated video decoding
- **No AI detection** (can be enabled later for car/person detection)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Camera Network                               │
│                                                                  │
│   192.168.1.20      192.168.1.21      192.168.1.22              │
│   ┌─────────┐       ┌─────────┐       ┌─────────┐               │
│   │  front  │       │  gate   │       │  back   │               │
│   └────┬────┘       └────┬────┘       └────┬────┘               │
│        │                 │                 │                     │
│        └────────────────┼─────────────────┘                     │
│                         │ RTSP                                   │
│                         ▼                                        │
│   ┌─────────────────────────────────────────┐                   │
│   │              Frigate Pod                 │                   │
│   │  ┌──────────────────────────────────┐   │                   │
│   │  │     Intel QSV (i915 GPU)         │   │                   │
│   │  │  - H.264/H.265 HW Decode         │   │                   │
│   │  └──────────────────────────────────┘   │                   │
│   │  ┌──────────────────────────────────┐   │                   │
│   │  │         Motion Detection          │   │                   │
│   │  └──────────────────────────────────┘   │                   │
│   └─────────────────────────────────────────┘                   │
│                         │                                        │
│                         ▼                                        │
│   ┌─────────────────────────────────────────┐                   │
│   │    Longhorn HDD (500GB, no backup)      │                   │
│   │    - Recordings (~14 days)              │                   │
│   └─────────────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────┘
```

## Prerequisites

1. **Intel GPU Plugin** must be deployed (provides `gpu.intel.com/i915` resource)
2. **Longhorn storage** with HDD storage class

## Setup

### 1. Create RTSP Secret

```bash
kubectl create secret generic frigate-rtsp -n frigate \
  --from-literal=FRIGATE_RTSP_PASSWORD='...'
```

### 2. Create OAuth2 Proxy Secret

See [oauth2-proxy-frigate README](../oauth2-proxy-frigate/README.md) for Pocket ID client setup.

```bash
kubectl create secret generic oauth2-proxy-frigate -n frigate \
  --from-literal=client-id='frigate' \
  --from-literal=client-secret='YOUR_CLIENT_SECRET' \
  --from-literal=cookie-secret='YOUR_COOKIE_SECRET'
```

### 3. Deploy via ArgoCD

The application will be deployed automatically when the manifests are pushed to git.

## Access

- **External (via Cloudflare)**: https://frigate.newjoy.ro
- **Internal (low latency)**: Use the ClusterIP service directly

## Storage Estimation

| Motion Level | Daily Storage | 500GB Duration |
|--------------|---------------|----------------|
| Light (~5%)  | ~18 GB/day    | ~28 days       |
| Normal (~10%)| ~36 GB/day    | ~14 days       |
| Heavy (~20%) | ~72 GB/day    | ~7 days        |

## Enabling AI Detection (Future)

To enable car detection on the front camera, update the configmap:

```yaml
cameras:
  front:
    detect:
      enabled: true
    objects:
      track:
        - car
```

## Troubleshooting

### Check Intel GPU access

```bash
kubectl exec -n frigate deploy/frigate -- ls -la /dev/dri
```

### Check Frigate logs

```bash
kubectl logs -n frigate deploy/frigate -f
```

### Verify camera connectivity

```bash
# Test RTSP stream from within cluster
kubectl run -n frigate --rm -it --image=linuxserver/ffmpeg test -- \
  ffprobe -v quiet -print_format json -show_streams \
  "rtsp://admin:PASSWORD@192.168.1.20:554/ch1/main/av_stream"
```

### Check hardware acceleration

```bash
kubectl exec -n frigate deploy/frigate -- cat /config/logs/frigate.log | grep -i vaapi
```

