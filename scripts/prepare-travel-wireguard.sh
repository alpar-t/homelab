#!/usr/bin/env bash

set -euo pipefail

namespace="wireguard"
secret_name="wireguard-keys"
keygen_pod="wireguard-keygen"
wireguard_image="docker.io/linuxserver/wireguard:1.0.20260223-r0-ls120@sha256:3abfd4b82212106e357989750b9c0c9859aa511f5305a9a55c18c8de7198b655"

usage() {
  echo "Usage: $0 OUTPUT_CONF" >&2
  echo "Creates the Kubernetes WireGuard secret and a mode-0600 GL client profile." >&2
}

if [[ $# -ne 1 ]]; then
  usage
  exit 2
fi

client_config="$1"
if [[ -e "${client_config}" ]]; then
  echo "Refusing to overwrite existing file: ${client_config}" >&2
  exit 1
fi

if ! kubectl get namespace "${namespace}" >/dev/null 2>&1; then
  kubectl create namespace "${namespace}" >/dev/null
fi

if kubectl -n "${namespace}" get secret "${secret_name}" >/dev/null 2>&1; then
  echo "Secret ${namespace}/${secret_name} already exists; refusing to rotate keys." >&2
  exit 1
fi

task_tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/travel-wireguard.XXXXXX")"
cleanup() {
  kubectl -n "${namespace}" delete pod "${keygen_pod}" \
    --ignore-not-found --wait=false >/dev/null 2>&1 || true
  rm -rf -- "${task_tmp_dir}"
}
trap cleanup EXIT

if kubectl -n "${namespace}" get pod "${keygen_pod}" >/dev/null 2>&1; then
  echo "Temporary pod ${namespace}/${keygen_pod} already exists; remove it first." >&2
  exit 1
fi

kubectl -n "${namespace}" run "${keygen_pod}" \
  --image="${wireguard_image}" \
  --restart=Never \
  --command -- sleep 300 >/dev/null
kubectl -n "${namespace}" wait pod/"${keygen_pod}" \
  --for=condition=Ready --timeout=120s >/dev/null

kubectl -n "${namespace}" exec "${keygen_pod}" -- /bin/sh -ec '
  umask 077
  wg genkey > /tmp/server-private-key
  wg pubkey < /tmp/server-private-key > /tmp/server-public-key
  wg genkey > /tmp/gl-private-key
  wg pubkey < /tmp/gl-private-key > /tmp/gl-public-key
  wg genpsk > /tmp/gl-preshared-key
'

for key_file in server-private-key server-public-key gl-private-key gl-public-key gl-preshared-key; do
  kubectl -n "${namespace}" exec "${keygen_pod}" -- \
    cat "/tmp/${key_file}" >"${task_tmp_dir}/${key_file}"
  chmod 0600 "${task_tmp_dir}/${key_file}"
done

kubectl -n "${namespace}" create secret generic "${secret_name}" \
  --from-file=server-private-key="${task_tmp_dir}/server-private-key" \
  --from-file=gl-public-key="${task_tmp_dir}/gl-public-key" \
  --from-file=gl-preshared-key="${task_tmp_dir}/gl-preshared-key" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

client_private_key="$(<"${task_tmp_dir}/gl-private-key")"
server_public_key="$(<"${task_tmp_dir}/server-public-key")"
gl_preshared_key="$(<"${task_tmp_dir}/gl-preshared-key")"

umask 077
{
  echo "[Interface]"
  echo "PrivateKey = ${client_private_key}"
  echo "Address = 10.77.0.2/32"
  echo "MTU = 1380"
  echo
  echo "[Peer]"
  echo "PublicKey = ${server_public_key}"
  echo "PresharedKey = ${gl_preshared_key}"
  # The home-host /32s beat a directly connected hotel 192.168.1.0/24;
  # the broad route covers all other home addresses when there is no clash.
  echo "AllowedIPs = 10.77.0.1/32, 192.168.1.102/32, 192.168.1.202/32, 192.168.1.203/32, 192.168.1.204/32, 192.168.1.0/24"
  echo "Endpoint = torok.go.ro:41641"
  echo "PersistentKeepalive = 25"
} >"${client_config}"
chmod 0600 "${client_config}"

unset client_private_key gl_preshared_key
echo "Created Kubernetes secret: ${namespace}/${secret_name}"
echo "Created GL.iNet import profile: ${client_config} (mode 0600)"
echo "Server public key: ${server_public_key}"
