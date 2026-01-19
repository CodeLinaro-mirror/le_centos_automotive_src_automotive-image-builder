#!/usr/bin/bash -x

source "$(dirname ${BASH_SOURCE[0]})"/../../scripts/test-lib.sh

# Define connection and VM parameters
IMG_NAME="test.img"
PASSWORD="password"
LOGIN_TIMEOUT=40

EXPECTED_KERNEL_OPTIONS=("panic=1" "quiet" "loglevel=5" "debug")

# Update cleanup function parameters on each test artifact change
trap 'cleanup_path "$IMG_NAME"' 'EXIT'

# Build the image
echo_log "Building AIB image..."
build kernel-cmdline-options.aib.yml "$NO_CTR_NAME" "$IMG_NAME"

# Check if image was created
assert_image_exists "$IMG_NAME"

# Start the VM using the built AIB image
VM_PID=$(run_vm "$IMG_NAME")

# Wait until VM becomes available or fail fast
if ! wait_for_vm_up "$LOGIN_TIMEOUT" "$PASSWORD"; then
    stop_vm "$VM_PID"
    exit 1
fi

# Retrieve the VM's /proc/cmdline to check active kernel boot parameters
CMDLINE=$(run_vm_command "cat /proc/cmdline")
echo_log "Kernel cmdline inside VM: $CMDLINE"

# Verify that all expected kernel options are present in the VM's boot parameters
missing_opts=()
all_present=true
for opt in "${EXPECTED_KERNEL_OPTIONS[@]}"; do
    echo "$CMDLINE" | grep -q "$opt"
    if [ $? -eq 0 ]; then
        echo_log "Found kernel option: $opt"
    else
        echo_fail "Missing kernel option: $opt"
        missing_opts+=("$opt")
        all_present=false
    fi
done

# Report test result
if $all_present; then
    echo_pass "All kernel options verified successfully (cmdline, loglevel, debug_logging, quiet)"
    success=0
else
    echo_fail "Missing kernel options: ${missing_opts[*]}"
    success=1
fi

# Clean up air process
stop_vm "$VM_PID"

exit $success

