#!/usr/bin/env bash
# Synthetic installer for issue #90 integration test.
#
# Exercises the systemd-PID-1 surface without needing a real installer:
#   * loginctl  -- requires systemd-logind to be running, which requires
#                  systemd-as-PID-1 + a working system DBus.
#   * systemctl status -- proves the system bus is reachable.
#
# Exits 0 on success so the orchestrator marks the trace COMPLETE.
set -euo pipefail

echo "[loginctl-installer] checking systemd-logind reachability..."
loginctl show-user 0 || loginctl list-users
echo "[loginctl-installer] systemd-logind OK"

echo "[loginctl-installer] checking system bus..."
systemctl status systemd-logind.service --no-pager
echo "[loginctl-installer] system bus OK"

# Touch a path the open.bt collector will pick up, so the trace has at
# least one observable event the analyzer can verify post-mortem.
touch /tmp/loginctl-installer.done
echo "[loginctl-installer] complete"
