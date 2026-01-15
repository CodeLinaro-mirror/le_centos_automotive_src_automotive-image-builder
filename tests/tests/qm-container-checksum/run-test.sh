#!/usr/bin/bash -x

source "$(dirname ${BASH_SOURCE[0]})"/../../scripts/test-lib.sh

IMG_NAME="test.img"
PASSWORD="password"
LOGIN_TIMEOUT=40
success=0

# Build image
echo_log "Building AIB image..."
build --target qemu --policy qm-container-checksum-policy.aibp.yml qm-container-checksum.aib.yml "$NO_CTR_NAME" "$IMG_NAME"

# Verify image exists
assert_image_exists "$IMG_NAME"

# Run VM
VM_PID=$(run_vm "$IMG_NAME")

# Wait for VM to be up
if ! wait_for_vm_up "$LOGIN_TIMEOUT" "$PASSWORD"; then
    stop_vm "$VM_PID"
    exit 1
fi

# Check the status of auto-boot-check
CHECK_OUTPUT=$(run_vm_command "systemctl is-active auto-boot-check || true")
echo_log "auto-boot-check status: $CHECK_OUTPUT"

if [[ "$CHECK_OUTPUT" == "active" ]]; then
    echo_pass "auto-boot-check is active"
    success=0
else
    echo_fail "auto-boot-check is NOT active"
    echo_log "Fetching journal output..."

    LOG_FILE="auto-boot-check.log"

    run_vm_command "journalctl -u auto-boot-check -n 500 --no-pager" > "$LOG_FILE" || true
    save_to_tmt_test_data "$LOG_FILE"

    CHK_LINE=$(grep -m1 -E "config checksum was .* expected" "$LOG_FILE" || true)
    if [ -n "$CHK_LINE" ]; then
        echo_log "Checksum mismatch:"
        echo "$CHK_LINE"
        ACTUAL=$(echo "$CHK_LINE"   | sed -n "s/.*checksum was '\([0-9a-f]\{40,64\}\)'.*/\1/p")
        EXPECTED=$(echo "$CHK_LINE" | sed -n "s/.*expected '\([0-9a-f]\{40,64\}\)'.*/\1/p")
        [ -n "$ACTUAL" ] && [ -n "$EXPECTED" ] && echo_log "actual=$ACTUAL expected=$EXPECTED"
    else
        echo_log "Checksum line not found, showing last 10 lines:"
        tail -n 10 "$LOG_FILE" || true
    fi

    QM_JSON_FILE="qm-json-file.log"
    run_vm_command "auto-boot-check-tool container-display qm" > "$QM_JSON_FILE" || true
    save_to_tmt_test_data "$QM_JSON_FILE"
    success=1
fi

# Cleanup
stop_vm "$VM_PID"
exit $success
