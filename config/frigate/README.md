# Frigate NVR

AI-powered Network Video Recorder with Intel QSV hardware acceleration.

## Overview

- **3x 4K cameras**: front, gate, back
- **Motion-based recording**: ~14 days retention with 500GB storage
- **Intel QSV acceleration**: Hardware-accelerated video decoding
- **License Plate Recognition (LPR)**: Enabled on gate camera
- **MQTT integration**: Events published to Home Assistant

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

### 2. Create MQTT Secret

MQTT broker is on Home Assistant Green at `192.168.1.102`. Create a Mosquitto user for Frigate.

```bash
kubectl create secret generic frigate-mqtt -n frigate \
  --from-literal=host='192.168.1.102' \
  --from-literal=username='frigate' \
  --from-literal=password='YOUR_MQTT_PASSWORD'
```

### 3. Create OAuth2 Proxy Secret

See [oauth2-proxy-frigate README](../oauth2-proxy-frigate/README.md) for Pocket ID client setup.

```bash
kubectl create secret generic oauth2-proxy-frigate -n frigate \
  --from-literal=client-id='frigate' \
  --from-literal=client-secret='YOUR_CLIENT_SECRET' \
  --from-literal=cookie-secret='YOUR_COOKIE_SECRET'
```

### 4. Deploy via ArgoCD

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

## License Plate Recognition (LPR)

LPR is enabled on the **gate camera** to recognize license plates on the driveway.

### How It Works

1. Frigate detects `car` or `motorcycle` objects on the gate camera
2. LPR model runs on detected vehicles to find license plates
3. OCR extracts the plate text
4. If plate matches a known plate, it's added as a `sub_label`
5. Events are published via MQTT for Home Assistant

### MQTT Topics

| Topic | Description |
|-------|-------------|
| `frigate/events` | All detection events including recognized plates |
| `frigate/tracked_object_update` | Real-time plate recognition updates |
| `frigate/gate/car` | Car detection events on gate camera |

### Known Plates

Edit `manifests/configmap.yaml` to add/update known plates:

### Tuning for Long Driveway

The gate camera is configured with:
- Lower `min_area` (300px) to catch smaller plates at distance
- Lower detection thresholds for distant vehicles

If plates aren't being recognized:
1. Check the debug view in Frigate UI to see if cars are detected
2. Adjust `min_area` in the configmap if plates are too small

### Debug LPR

Add to Frigate config for verbose LPR logs:

```yaml
logger:
  default: info
  logs:
    frigate.data_processing.common.license_plate: debug
```

## Home Assistant Integration

### Frigate Integration

Install the [Frigate integration](https://docs.frigate.video/integrations/home-assistant/) in HACS:

1. Add HACS repository: `blakeblackshear/frigate-hass-integration`
2. Install "Frigate" integration
3. Add integration with Frigate URL: `http://frigate.frigate.svc.cluster.local:5000`

### MQTT Automations

Frigate publishes events to MQTT. Create automations in Home Assistant:

#### Alert on Any License Plate Recognized

```yaml
alias: "LPR: Alert on any plate"
description: "Notify when any license plate is recognized"
trigger:
  - platform: mqtt
    topic: frigate/events
condition:
  - condition: template
    value_template: "{{ trigger.payload_json.after.current_zones | length > 0 }}"
  - condition: template
    value_template: "{{ trigger.payload_json.after.label == 'car' }}"
  - condition: template
    value_template: >
      {{ trigger.payload_json.after.recognized_license_plate is defined 
         or trigger.payload_json.after.sub_label is defined }}
action:
  - service: notify.mobile_app_your_phone
    data:
      title: "License Plate Detected"
      message: >
        {% if trigger.payload_json.after.sub_label %}
          Known plate: {{ trigger.payload_json.after.sub_label }}
        {% else %}
          Plate: {{ trigger.payload_json.after.recognized_license_plate }}
        {% endif %}
      data:
        image: "/api/frigate/notifications/{{ trigger.payload_json.after.id }}/thumbnail.jpg"
        clickAction: "/frigate"
mode: single
```

#### Alert on Unknown Plates Only

```yaml
alias: "LPR: Alert on unknown plates"
trigger:
  - platform: mqtt
    topic: frigate/events
condition:
  - condition: template
    value_template: "{{ trigger.payload_json.after.label == 'car' }}"
  - condition: template
    value_template: "{{ trigger.payload_json.after.recognized_license_plate is defined }}"
  - condition: template
    value_template: "{{ trigger.payload_json.after.sub_label is not defined }}"
action:
  - service: notify.mobile_app_your_phone
    data:
      title: "Unknown Vehicle"
      message: "Plate: {{ trigger.payload_json.after.recognized_license_plate }}"
mode: single
```

## Enabling AI Detection on Other Cameras

To enable car/person detection on front or back cameras, update the configmap:

```yaml
cameras:
  front:
    detect:
      enabled: true
    objects:
      track:
        - car
        - person
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

### Check MQTT connection

```bash
kubectl logs -n frigate deploy/frigate | grep -i mqtt
```

### Check LPR is working

```bash
# Watch for LPR events
kubectl logs -n frigate deploy/frigate -f | grep -i "license\|plate\|lpr"
```

### Verify secrets are set

```bash
kubectl get secret -n frigate frigate-mqtt -o yaml
```

