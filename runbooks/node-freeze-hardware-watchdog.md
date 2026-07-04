# Node hard-freezes and the hardware watchdog

Alder Lake-N nodes (`buksi`, `pamacs`, `pufi`) occasionally hard-freeze:
the whole box locks up instantly, unreachable by ping/SSH, with **no
kernel trace at all**. This runbook records what's known about the cause
and the watchdog mitigation that turns a freeze into a fast auto-reboot
instead of a manual power-cycle.

## Mitigations in place

Two kernel args (in `genesis/ignition-template.bu`, live on all nodes):

- `intel_idle.max_cstate=1` — blocks deep CPU C-states (C6/C8/C10),
  which caused lockups on these CPUs.
- `i915.enable_dc=0` — disables i915 Display Core power states
  (DC5/DC6); the headless GPU aggressively entering DC states caused
  lockups on `buksi`. Added 2026-04-12.

**Hardware watchdog** (added 2026-07-04) — the iTCO watchdog
(`intel_oc_wdt`, `/dev/watchdog0`) exists on these boards but ships
**unarmed**, so a freeze sits dead until someone physically resets it.
We now feed it from PID1 via `/etc/systemd/system.conf.d/watchdog.conf`:

```ini
[Manager]
RuntimeWatchdogSec=60
RebootWatchdogSec=5min
```

Live on all three nodes and baked into `genesis/ignition-template.bu`.
A freeze now auto-reboots in ~60 s. Verify:

```bash
ssh core@<node>.local 'cat /sys/class/watchdog/watchdog0/state'   # -> active
# systemd's own confirmation:
ssh core@<node>.local 'sudo journalctl -b 0 | grep "Watchdog running"'
```

To apply on a running node without reprovisioning:

```bash
ssh core@<node>.local
sudo mkdir -p /etc/systemd/system.conf.d
sudo tee /etc/systemd/system.conf.d/watchdog.conf >/dev/null <<'EOF'
[Manager]
RuntimeWatchdogSec=60
RebootWatchdogSec=5min
EOF
sudo systemctl daemon-reexec   # re-reads manager config, opens /dev/watchdog0
```

## 2026-07-04: pamacs froze despite the i915 fix — cause is hardware

`pamacs` hard-froze at ~05:41 UTC **with `i915.enable_dc=0` already
active**. It stayed dead ~3 h (watchdog was not yet armed) until a manual
power-cycle. Because its `openclaw-state` PVC was single-replica and
pinned to pamacs, Baloo went fully offline until the node returned — the
volume is now replicated (see below).

Diagnosis found **no positive fault signal anywhere**:

- No MCE, no EDAC/ECC error, no thermal throttle (pkg temp 58 °C).
- No `hung_task` / soft-lockup / RCU stall / OOM / call trace.
- No firmware error record (APEI/BERT/GHES/ERST empty), empty pstore.
- NMI watchdog enabled but did **not** fire — a software CPU lockup
  normally trips it, so this looks like a power/SoC-level halt.

The prior-boot journal just stops mid-operation after a routine k3s
compaction. (Ignore the `publish-cluster-alias` restart spam near the
end — that unit is separately broken: `avahi-publish-alias: command not
found`, failing every 10 s. Cosmetic, not the cause.)

**Decisive evidence it is not software/kernel/i915:** `buksi` and `pufi`
run the *identical* FCOS image (44.20260607, kernel 7.0.11), Alder
Lake-N hardware, and the same kargs, and had 8+ days uptime while pamacs
froze after 3. A software cause would hit all three equally. Conclusion:
**hardware fault specific to the pamacs unit** (suspect RAM / VRM / PSU).

### Diagnostic commands (for the next freeze)

```bash
# Boot history — LAST ENTRY of each boot = when it froze/rebooted.
# A freeze shows the log stopping mid-stream (no clean shutdown lines).
ssh core@<node>.local 'sudo journalctl --list-boots'
# Firmware/hardware fault signals in the prior boot and this one:
ssh core@<node>.local 'sudo journalctl -k -b -1 | grep -iE "mce|machine check|EDAC|thermal|throttl|hung task|soft lockup|rcu.*stall|BUG:|call trace"'
ssh core@<node>.local 'sudo journalctl -k -b 0  | grep -iE "BERT|GHES|APEI|ERST|hardware error"'
ssh core@<node>.local 'sudo ls -la /sys/fs/pstore/'   # firmware-captured panic, if any
# Current temps:
ssh core@<node>.local 'cat /sys/class/thermal/thermal_zone*/type; cat /sys/class/thermal/thermal_zone*/temp'
```

### Open follow-ups for pamacs

- Run **memtest86+** overnight; reseat / swap-test the RAM.
- Swap-test the PSU against a known-good spare.
- If freezes persist and hardware checks clean, consider draining
  critical singletons off pamacs.

## Related

- Baloo's `openclaw-state` was moved from `longhorn-ssd-noreplica` to
  `longhorn-ssd` (2 replicas + weekly B2 backup) on 2026-07-04 precisely
  because this freeze took it offline — see `config/baloo/manifests/state-pvc.yaml`.
- Node drain/maintenance procedure: `runbooks/node-maintenance.md`.
