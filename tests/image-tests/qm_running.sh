#!/bin/bash

echo "[qm] Checking QM service and command execution..."

qm_ready() {
    if command -v qmc >/dev/null 2>&1; then
        systemctl is-enabled --quiet qm.service &&
            qmc exec systemctl is-active --quiet basic.target
    else
        podman exec qm systemctl is-active --quiet basic.target
    fi
}

# Legacy Quadlets notify readiness through conmon before QM's systemd is ready.
for ((attempt = 0; attempt < 30; attempt++)); do
    if systemctl is-active --quiet qm.service && qm_ready; then
        echo "[qm] PASS: QM is active and accepting commands."
        exit 0
    fi
    sleep 1
done

echo "[qm] FAIL: QM was not enabled, active, and accepting commands within 30 seconds."
systemctl status qm.service --no-pager || true
journalctl --boot --unit=qm.service --no-pager || true
if ! command -v qmc >/dev/null 2>&1; then
    podman logs --tail=100 qm || true
fi
exit 1
