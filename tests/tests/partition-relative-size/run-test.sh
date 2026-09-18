#!/usr/bin/bash -x

source "$(dirname "${BASH_SOURCE[0]}")"/../../scripts/test-lib.sh

IMG_NAME="out.img"
LOGIN_TIMEOUT=120

# Update cleanup function parameters on each test artifact change
trap 'cleanup_path "$IMG_NAME" ;
      stop_vm "$VM_PID"' \
    EXIT

echo_log "Starting build..."
build partition-relative-size.aib.yml "$NO_CTR_NAME" "$IMG_NAME"
echo_log "Build completed, output: $IMG_NAME"

IMG_SIZE="$(stat -c %s "$IMG_NAME")" || fatal "FAIL: Failed to stat image file"
EXP_VAR_SIZE="$( echo "$IMG_SIZE * 0.1 / 1" | bc)"
EXP_VAR_QM_SIZE="$( echo "$IMG_SIZE * 0.05 / 1" | bc)"

# Start the VM using the built AIB image
VM_PID=$(run_vm "$IMG_NAME")

# Wait until VM becomes available or fail fast
if ! wait_for_vm_up "$LOGIN_TIMEOUT"; then
    stop_vm "$VM_PID"
    exit 1
fi

# The difference between requested relative size and real size can be 1%
assert_block_partition_size /var "$EXP_VAR_SIZE" 1
assert_block_partition_size /var/qm "$EXP_VAR_QM_SIZE" 1


