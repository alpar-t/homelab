# OTMonitor

OpenTherm Gateway Monitor for heating system monitoring.

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   ConfigMap     │────▶│  Init Container  │────▶│   OTMonitor     │
│ (config template)     │  (envsubst)      │     │   Container     │
└─────────────────┘     └──────────────────┘     └─────────────────┘
        │                        │
        │               ┌────────┴────────┐
        │               │     Secret      │
        │               │   (passwords)   │
        │               └─────────────────┘
        │                        │
        └────────────────────────┘
                    │
                    ▼
            /config/otmonitor.conf
              (generated at startup)
```

## Building the Container Image

### Prerequisites

- Docker installed locally
- GitHub account with a Personal Access Token (PAT) with `write:packages` scope

### Build Steps

1. **Navigate to the build directory:**
   ```bash
   cd config/otmonitor/build
   ```

2. **Build and push the image:**
   ```bash
   # Build for x86_64 and push (required when building from ARM Mac)
   ./build.sh push
   
   # Or manually with buildx:
   docker buildx build --platform linux/amd64 \
     -t ghcr.io/alpar-t/otmonitor:latest --push .
   ```

3. **Login to GitHub Container Registry:**
   ```bash
   # Create a PAT at: https://github.com/settings/tokens/new
   # Select scope: write:packages
   
   export GITHUB_TOKEN="ghp_your_token_here"
   echo $GITHUB_TOKEN | docker login ghcr.io -u alpar-t --password-stdin
   ```

4. **Verify the image:**
   ```bash
   # Check it was pushed
   docker buildx imagetools inspect ghcr.io/alpar-t/otmonitor:latest
   ```

5. **Make the package public (required):**
   Go to https://github.com/users/alpar-t/packages/container/otmonitor/settings
   and change visibility to **Public** (the cluster is not authenticated to pull private images).

## Deployment

### 1. Create the Secret (one-time)

Run this command to create the secret with your MQTT credentials:

```bash
kubectl create namespace otmonitor

kubectl create secret generic otmonitor-secrets \
  --namespace=otmonitor \
  --from-literal=EMAIL_RECIPIENT="..." \
  --from-literal=EMAIL_SENDER="..." \
  --from-literal=MQTT_USERNAME="otmonitor" \
  --from-literal=MQTT_PASSWORD_BASE64="..." \
  --from-literal=MQTT_CLIENT_ID="k8s-otmonitor" \
  --from-literal=MQTT_BROKER="192.168.1.102"
```

### 2. Deploy via ArgoCD

The application is automatically deployed by ArgoCD. Just ensure:
1. The secret exists in the namespace
2. The container image is pushed to the registry

### 3. Access

Once deployed: **https://otmonitor.newjoy.ro**

## Configuration

### Ports

| Port | Description |
|------|-------------|
| 5800 | Web GUI (VNC via browser) |
| 7686 | OTMonitor native port |

### Secret Variables

| Variable | Description |
|----------|-------------|
| `EMAIL_RECIPIENT` | Email recipient for alerts |
| `EMAIL_SENDER` | Email sender address |
| `MQTT_USERNAME` | MQTT broker username |
| `MQTT_PASSWORD_BASE64` | MQTT password (base64 encoded, as OTMonitor expects) |
| `MQTT_CLIENT_ID` | MQTT client identifier |
| `MQTT_BROKER` | MQTT broker IP/hostname |

### Display Settings (in Deployment)

| Variable | Default | Description |
|----------|---------|-------------|
| `DISPLAY_WIDTH` | 1800 | VNC display width |
| `DISPLAY_HEIGHT` | 950 | VNC display height |

## Updating Configuration

To update the configuration:

1. **Update ConfigMap** - Edit `manifests/configmap.yaml` and commit
2. **Update Secrets** - Use `kubectl` to update the secret:
   ```bash
   kubectl create secret generic otmonitor-secrets \
     --namespace=otmonitor \
     --from-literal=... \
     --dry-run=client -o yaml | kubectl apply -f -
   ```

The [Reloader](https://github.com/stakater/Reloader) will automatically restart 
the pod when ConfigMap or Secret changes are detected.

## Troubleshooting

### Check generated config
```bash
kubectl exec -n otmonitor deploy/otmonitor -c otmonitor -- cat /config/otmonitor.conf
```

### View logs
```bash
kubectl logs -n otmonitor deploy/otmonitor -c otmonitor
kubectl logs -n otmonitor deploy/otmonitor -c generate-config
```

### Verify secret values
```bash
kubectl get secret otmonitor-secrets -n otmonitor -o jsonpath='{.data}' | jq
```
