#!/bin/bash -x

source "$(dirname ${BASH_SOURCE[0]})"/../../scripts/test-lib.sh

# Define connection and VM parameters
IMG_NAME="test.img"
MANIFEST=minimal-image-boot.aib.yml
LOGFILE=serial-console.log

test_check_sysusers_uid_collision() {
    local collisions
    collisions=$(grep -E "Suggested (user|group) ID [0-9]+ for [a-zA-Z]+ already used" "${IMG_BUILD_LOG_BOOTC}" || true)

    if [[ -n "$collisions" ]]; then
        echo "${collisions}" > sysusers-uidgid-collisions.txt
        save_to_tmt_data sysusers-uidgid-collisions.txt
        exit 1
    fi
}

# Update cleanup function parameters on each test artifact change
trap 'cleanup_path "$IMG_NAME"' 'EXIT'

# Build the image
echo_log "Building image from $MANIFEST..."
build "$MANIFEST" "$NO_CTR_NAME" "$IMG_NAME"

# Verify no UID collision happened during the build
test_check_sysusers_uid_collision

# Check if image was created
assert_image_exists "$IMG_NAME"

# Start the VM using the built AIB image
$AIR --nographics "$IMG_NAME" >"$LOGFILE" 2>&1 &
VM_PID=$!
echo_log "VM running at pid: $VM_PID"
echo_log $VM_PID

# Wait for the test to finish
retry=90
while ! grep -q '\[RUNNER\] Boot testing finished.' "$LOGFILE" 2>/dev/null; do
    sleep 1
    retry=$((retry-1))
    if [ $retry -le 0 ]; then
        echo_fail "Timeout waiting for VM tests to complete"
        stop_vm "$VM_PID"
        exit 1
    fi
done

# Check logs for success
echo_log "Verifying test output..."

tests=("dmesg" "selinux" "systemd" "rpmdb")
all_passed=true

for test in "${tests[@]}"; do
    if grep -q "\[$test\] PASS" "$LOGFILE"; then
        echo "[$test] PASS"
    else
        echo "[$test] FAIL"
        all_passed=false
    fi
done

if $all_passed; then
    echo_pass "All tests PASSED."
    success=0
else
    echo_fail "Some tests FAILED. See $LOGFILE for details."
    success=1
fi

if [ -n "$TMT_TEST_DATA" ] && [ -f "$LOGFILE" ]; then
    echo_log "Saving serial console log to TMT test data..."
    save_to_tmt_data "$LOGFILE"
fi

# Clean up air process
stop_vm "$VM_PID"

exit $success
