#!/usr/bin/env bash
set -euo pipefail

readonly KUBECTL_BIN="${KUBECTL_BIN:-/opt/homebrew/bin/kubectl}"
readonly NPX_BIN="${NPX_BIN:-/opt/homebrew/bin/npx}"
readonly ACTUAL_NAMESPACE="actual-budget"
readonly ACTUAL_SERVICE="actual-budget-mcp"
readonly ACTUAL_SERVICE_PORT="3000"

task_tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/actual-mcp-codex.XXXXXX")"
task_port_forward_log="${task_tmp_dir}/port-forward.log"
task_port_forward_pid=""

cleanup() {
  trap - EXIT HUP INT TERM
  if [[ -n "${task_port_forward_pid}" ]] && kill -0 "${task_port_forward_pid}" 2>/dev/null; then
    kill "${task_port_forward_pid}" 2>/dev/null || true
    wait "${task_port_forward_pid}" 2>/dev/null || true
  fi
  rm -f -- "${task_port_forward_log}"
  rmdir "${task_tmp_dir}" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

for required_command in "${KUBECTL_BIN}" "${NPX_BIN}"; do
  if [[ ! -x "${required_command}" ]]; then
    echo "actual-mcp: required command is unavailable: ${required_command}" >&2
    exit 1
  fi
done

# Let kubectl allocate a free local port. Binding only to loopback keeps the
# MCP private even while the tunnel is active.
"${KUBECTL_BIN}" -n "${ACTUAL_NAMESPACE}" port-forward \
  --address 127.0.0.1 \
  "service/${ACTUAL_SERVICE}" \
  ":${ACTUAL_SERVICE_PORT}" >"${task_port_forward_log}" 2>&1 &
task_port_forward_pid=$!

task_local_port=""
for _ in {1..100}; do
  if ! kill -0 "${task_port_forward_pid}" 2>/dev/null; then
    echo "actual-mcp: kubectl port-forward exited during startup" >&2
    sed 's/^/actual-mcp: /' "${task_port_forward_log}" >&2
    exit 1
  fi

  task_local_port="$(
    sed -nE 's/^Forwarding from 127\.0\.0\.1:([0-9]+) -> [0-9]+$/\1/p' \
      "${task_port_forward_log}" | head -n 1
  )"
  [[ -n "${task_local_port}" ]] && break
  sleep 0.1
done

if [[ -z "${task_local_port}" ]]; then
  echo "actual-mcp: timed out waiting for the local port-forward" >&2
  sed 's/^/actual-mcp: /' "${task_port_forward_log}" >&2
  exit 1
fi

task_api_key="$(
  "${KUBECTL_BIN}" -n "${ACTUAL_NAMESPACE}" get secret actual-mcp-credentials \
    -o jsonpath='{.data.mcp_api_key}' | /usr/bin/base64 -d
)"
if [[ -z "${task_api_key}" ]]; then
  echo "actual-mcp: mcp_api_key is missing from actual-mcp-credentials" >&2
  exit 1
fi

# mcp-remote expands the placeholder from the environment, keeping the bearer
# token out of its command line. Its stdout remains reserved for MCP framing.
export ACTUAL_MCP_AUTH_HEADER="Bearer ${task_api_key}"
unset task_api_key

"${NPX_BIN}" --yes mcp-remote@0.1.38 \
  "http://127.0.0.1:${task_local_port}/http" \
  --allow-http \
  --transport http-only \
  --header 'Authorization:${ACTUAL_MCP_AUTH_HEADER}' \
  --silent
