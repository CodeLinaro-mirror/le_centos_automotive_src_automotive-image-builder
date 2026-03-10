#!/usr/bin/bash -x

source "$(dirname ${BASH_SOURCE[0]})"/../../scripts/test-lib.sh

set -euo pipefail

AVB_UNSIGNED="localhost/avb:unsigned"
AVB_PREPARED="localhost/avb:prepared"
AVB_SIGNED="localhost/avb:signed"
AVB_UPD_UNSIGNED="localhost/secureboot-update:unsigned"
AVB_UPD_PREPARED="localhost/avb-update:prepared"
AVB_UPD_SIGNED="localhost/avb-update:signed"
IMG_SIGNED="bootc-signed.img"
UPDATE_TAR="update.tar"

# Update cleanup function parameters on each test artifact change
trap 'cleanup_path "$IMG_SIGNED" "$UPDATE_TAR"; cleanup_container "$AVB_UNSIGNED" "$AVB_PREPARED" "$AVB_SIGNED" "$AVB_UPD_UNSIGNED" "$AVB_UPD_PREPARED" "$AVB_UPD_SIGNED"' 'EXIT'

#########################################
### Build base bootc image and disk image
#########################################

echo_log "Starting bootc build..."
build --target abootqemukvm \
    avb.aib.yml \
    "$AVB_UNSIGNED"
echo_log "Build completed, output: $AVB_UNSIGNED"

echo_log "AVB Signing bootc image..."
# Generate a throwaway key (no password) and prepare for resealing with it
openssl genpkey -algorithm ed25519 -outform PEM -out private.pem
$AIB prepare-reseal --key=private.pem "$AVB_UNSIGNED" "$AVB_PREPARED"

# Extract aboot files to sign
$AIB extract-for-signing "$AVB_PREPARED" to-sign

# Sign aboot files
./sign.sh to-sign/

# Inject signed aboot files and reseal
$AIB inject-signed --reseal-with-key=private.pem "$AVB_PREPARED" to-sign "$AVB_SIGNED"

echo_pass "Built signed bootc container"

echo_log "Building bootc disk image..."
$AIB to-disk-image --verbose "$AVB_SIGNED" "$IMG_SIGNED"
echo_pass "Built signed bootc disk image"

############################################
### Build bootc image that we will update to
############################################

echo_log "Starting bootc build of update..."
build --target abootqemukvm \
    avb-update.aib.yml \
    "$AVB_UPD_UNSIGNED"
echo_log "Build completed, output: $AVB_UPD_UNSIGNED"

echo_log "AVB Signing bootc update image..."
# Generate a throwaway key (no password) and prepare for resealing with it
openssl genpkey -algorithm ed25519 -outform PEM -out private2.pem
$AIB prepare-reseal --key=private2.pem "$AVB_UPD_UNSIGNED" "$AVB_UPD_PREPARED"

# Extract aboot files to sign
$AIB extract-for-signing "$AVB_UPD_PREPARED" to-sign

# Sign aboot files
./sign.sh to-sign/

# Inject signed aboot files and reseal
$AIB inject-signed --reseal-with-key=private2.pem "$AVB_UPD_PREPARED" to-sign "$AVB_UPD_SIGNED"

# Export file
$SUDO podman save --format=oci-archive -o "$UPDATE_TAR" "$AVB_UPD_SIGNED"

echo_pass "Built signed bootc update container"

################################
### Boot the image and update it
################################

echo_log "Running bootc disk image..."
VM_PID=$(run_vm "$IMG_SIGNED" "serial-console.log" --avb --sharedir .)

PASSWORD="password"
LOGIN_TIMEOUT=40
if ! wait_for_vm_up "$LOGIN_TIMEOUT" "$PASSWORD"; then
    stop_vm "$VM_PID"
    exit 1
fi

assert_file_has_content serial-console.log "AVB verification OK for slot a"

# We should not have less installed yet
if run_vm_command "stat /usr/bin/less" ; then
    echo_fail "less unexpectedly installed before update"
    stop_vm "$VM_PID"
    exit 1
fi

echo_pass "Booted signed bootc disk image with AVC enabled"
run_vm_command "rpm-ostree status"

echo_log "bootc switching to $UPDATE_TAR..."
run_vm_command "mount -t virtiofs host /mnt"
run_vm_command "bootc switch --transport oci-archive /mnt/$UPDATE_TAR"
run_vm_command "reboot now"

echo_log "Waiting for reboot..."
# Wait for reboot
if ! wait_for_vm_up "$LOGIN_TIMEOUT" "$PASSWORD"; then
    stop_vm "$VM_PID"
    exit 1
fi

run_vm_command "rpm-ostree status"

# Check that we have the new update with less in
if ! run_vm_command "stat /usr/bin/less" ; then
    echo_fail "less not installed in update"
    stop_vm "$VM_PID"
    exit 1
fi

echo_pass "Booted into updated image"

stop_vm "$VM_PID"
