#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HA_SRC="$REPO_ROOT/config/homeassistant/ha"
HA_HOST="hass"
HA_URL="http://192.168.1.102:8123"
HA_TOKEN="$(tr -d '\n\r' < "$HOME/.secret.ha")"

reload() {
  local service="$1"
  curl -sf -X POST "$HA_URL/api/services/$service" \
    -H "Authorization: Bearer $HA_TOKEN" \
    -H "Content-Type: application/json" \
    -o /dev/null
}

echo "==> Copying config to HA..."
# automations / scripts / scenes
for f in automations.yaml scripts.yaml scenes.yaml; do
  scp -q "$HA_SRC/$f" "$HA_HOST:/config/$f"
done
# packages
for f in "$HA_SRC/packages/"*.yaml; do
  scp -q "$f" "$HA_HOST:/config/packages/$(basename "$f")"
done
# dashboards
for f in "$HA_SRC/dashboards/"*.yaml; do
  scp -q "$f" "$HA_HOST:/config/dashboards/$(basename "$f")"
done

echo "==> Reloading automations..."
reload "automation/reload"

echo "==> Reloading core config (packages)..."
reload "homeassistant/reload_core_config"

echo "==> Done."
