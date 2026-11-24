#!/bin/bash -x

LOG_DIR="/var/tmp/tests"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/test-results.txt"

: > "$LOG_FILE"

# Immediately stop and mask getty services so they won't grab the serial console
for svc in getty@tty1.service serial-getty@ttyAMA0.service serial-getty@ttyS0.service; do
    systemctl stop "$svc" >/dev/null 2>&1 || true
    systemctl mask "$svc" >/dev/null 2>&1 || true
done

write_log() {
    local msg="$*"
    echo "$msg" | tee -a "$LOG_FILE"
    for tty in /dev/ttyAMA0 /dev/ttyS0 /dev/console /dev/tty0; do
        if [ -w "$tty" ] 2>/dev/null; then
            echo "$msg" >"$tty" 2>/dev/null || true
        fi
    done
}

run_test() {
    local script="$1"
    local tag="$2"
    local test_log="$LOG_DIR/$tag.log"
    write_log "[TEST] Running $tag..."
    if "$script" >"$test_log" 2>&1; then
        cat "$test_log" >>"$LOG_FILE"
        write_log "[$tag] PASS"
    else
        cat "$test_log" >>"$LOG_FILE"
        # Preserve guest diagnostics in the serial-console artifact before the
        # VM is stopped and its disk is deleted by the host test.
        for tty in /dev/ttyAMA0 /dev/ttyS0 /dev/console /dev/tty0; do
            if [ -w "$tty" ] 2>/dev/null; then
                cat "$test_log" >"$tty" 2>/dev/null || true
            fi
        done
        write_log "[$tag] FAIL"
    fi
}

write_log "[RUNNER] Starting boot testing..."

run_test /usr/tests/dmesg_clean.sh dmesg
run_test /usr/tests/selinux_check.sh selinux
run_test /usr/tests/systemd_running.sh systemd
run_test /usr/tests/qm_running.sh qm
run_test /usr/tests/rpmdb_initialized.sh rpmdb

write_log "[RUNNER] Boot testing finished."

grep "^\[.*\] PASS\|\[.*\] FAIL" "$LOG_FILE" | tee -a "$LOG_FILE"

if grep -q "\[.*\] FAIL" "$LOG_FILE"; then
    write_log "### TEST RUNNER: FAILED ###"
    exit 1
else
    write_log "### TEST RUNNER: PASSED ###"
    exit 0
fi
