#!/bin/sh
# Recover the GL travel router's split WireGuard tunnel when an upstream Wi-Fi
# change leaves the interface configured but unable to handshake.

set -u

interface="${WG_HOME_INTERFACE:-wg_home}"
probe_address="${WG_HOME_PROBE_ADDRESS:-10.77.0.1}"
max_age="${WG_HOME_MAX_AGE:-180}"
cooldown="${WG_HOME_COOLDOWN:-600}"
force_restart="${WG_HOME_FORCE_RESTART:-false}"
state_file="/tmp/gl-wireguard-watchdog.last-restart"
log_tag="gl-wireguard-watchdog"

latest_handshake() {
  wg show "${interface}" latest-handshakes 2>/dev/null |
    awk 'NR == 1 { print $2 }'
}

is_nonnegative_integer() {
  case "$1" in
    ''|*[!0-9]*) return 1 ;;
    *) return 0 ;;
  esac
}

interface_up="$(ifstatus "${interface}" 2>/dev/null |
  jsonfilter -e '@.up' 2>/dev/null)"
[ "${interface_up}" = "true" ] || exit 0

now="$(date +%s)"
handshake="$(latest_handshake)"
is_nonnegative_integer "${handshake}" || handshake=0

if [ "${force_restart}" != "true" ] &&
   [ "${handshake}" -gt 0 ] &&
   [ "$((now - handshake))" -le "${max_age}" ]; then
  exit 0
fi

# Generate traffic and give WireGuard a chance to re-handshake on its own.
# This is normally sufficient; restarting is only the fallback for a stale
# socket or route after the upstream Wi-Fi changes.
ping -c 1 -W 2 "${probe_address}" >/dev/null 2>&1 || true
sleep 5

now="$(date +%s)"
handshake="$(latest_handshake)"
is_nonnegative_integer "${handshake}" || handshake=0

if [ "${force_restart}" != "true" ] &&
   [ "${handshake}" -gt 0 ] &&
   [ "$((now - handshake))" -le "${max_age}" ]; then
  exit 0
fi

last_restart=0
if [ -r "${state_file}" ]; then
  last_restart="$(sed -n '1p' "${state_file}")"
  is_nonnegative_integer "${last_restart}" || last_restart=0
fi

if [ "$((now - last_restart))" -lt "${cooldown}" ]; then
  exit 0
fi

printf '%s\n' "${now}" >"${state_file}"
logger -t "${log_tag}" \
  "${interface} handshake is stale; restarting the interface"

ifdown "${interface}"
sleep 2

if ! ifup "${interface}"; then
  logger -t "${log_tag}" "failed to start ${interface}"
  exit 1
fi

sleep 8
now="$(date +%s)"
handshake="$(latest_handshake)"
is_nonnegative_integer "${handshake}" || handshake=0

if [ "${handshake}" -gt 0 ] &&
   [ "$((now - handshake))" -le "${max_age}" ]; then
  logger -t "${log_tag}" "${interface} recovered with a fresh handshake"
  exit 0
fi

logger -t "${log_tag}" \
  "${interface} restarted but the peer still does not respond"
exit 1
