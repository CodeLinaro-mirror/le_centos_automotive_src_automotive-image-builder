#!/usr/bin/bash -x

source "$(dirname ${BASH_SOURCE[0]})"/../../scripts/test-lib.sh

set -euo pipefail


EFI_SIGNER="localhost/test-efi-signer"
SB_UNSIGNED="localhost/secureboot:unsigned"
SB_PREPARED="localhost/secureboot:prepared"
SB_SIGNED="localhost/secureboot:signed"
SB_UPD_UNSIGNED="localhost/secureboot-update:unsigned"
SB_UPD_PREPARED="localhost/secureboot-update:prepared"
SB_UPD_SIGNED="localhost/secureboot-update:signed"
IMG_SIGNED="bootc-signed.img"
UPDATE_TAR="update.tar"

# Update cleanup function parameters on each test artifact change
trap 'cleanup_path "$IMG_SIGNED" "$UPDATE_TAR"; cleanup_container "$EFI_SIGNER" "$SB_UNSIGNED" "$SB_PREPARED" "$SB_SIGNED" "$SB_UPD_UNSIGNED" "$SB_UPD_PREPARED" "$SB_UPD_SIGNED"' 'EXIT'

echo_log "Building helpers..."
# Build EFI signer helper
sudo podman build signer -t "$EFI_SIGNER"

# Download EFI firmware that is guaranteed to work with the stored enrolled key
curl -L https://gitlab.com/CentOS/automotive/src/automotive-image-builder/-/releases/1.1.3/downloads/OVMF_CODE.secboot.fd -o OVMF_CODE.secboot.fd
curl -L https://gitlab.com/CentOS/automotive/src/automotive-image-builder/-/releases/1.1.3/downloads/OVMF_VARS.secboot.fd -o OVMF_VARS.secboot.fd

echo_log "Helpers built"

#########################################
### Build base bootc image and disk image
#########################################

echo_log "Starting bootc build..."
build secureboot.aib.yml "$SB_UNSIGNED"
echo_log "Build completed, output: $SB_UNSIGNED"

echo_log "EFI Signing bootc image..."
# Generate a throwaway key (no password) and prepare for resealing with it
openssl genpkey -algorithm ed25519 -outform PEM -out private.pem
$AIB prepare-reseal --key=private.pem "$SB_UNSIGNED" "$SB_PREPARED"

# Extract EFI files to sign
$AIB extract-for-signing "$SB_PREPARED" to-sign

# Sign EFI files
sudo podman run --rm -ti --privileged -v .:/work "$EFI_SIGNER" --certificates db.p12 --password-file password to-sign/efi/*

# Inject signed EFI files and reseal
$AIB inject-signed --reseal-with-key=private.pem "$SB_PREPARED" to-sign "$SB_SIGNED"

echo_pass "Built signed bootc container"

echo_log "Building bootc disk image..."
$AIB to-disk-image --verbose "$SB_SIGNED" "$IMG_SIGNED"
echo_pass "Built signed bootc disk image"

############################################
### Build bootc image that we will update to
############################################

echo_log "Starting bootc build of update..."
build secureboot-update.aib.yml "$SB_UPD_UNSIGNED"
echo_log "Build completed, output: $SB_UPD_UNSIGNED"

echo_log "EFI Signing bootc update image..."
# Generate a throwaway key (no password) and prepare for resealing with it
openssl genpkey -algorithm ed25519 -outform PEM -out private2.pem
$AIB prepare-reseal --key=private2.pem "$SB_UPD_UNSIGNED" "$SB_UPD_PREPARED"

# Extract EFI files to sign
$AIB extract-for-signing "$SB_UPD_PREPARED" to-sign

# Sign EFI files
sudo podman run --rm -ti --privileged -v .:/work "$EFI_SIGNER" --certificates db.p12 --password-file password to-sign/efi/*

# Inject signed EFI files and reseal
$AIB inject-signed --reseal-with-key=private2.pem "$SB_UPD_PREPARED" to-sign "$SB_UPD_SIGNED"

# Export file
sudo podman save --format=oci-archive -o "$UPDATE_TAR" "$SB_UPD_SIGNED"

echo_pass "Built signed bootc update container"

################################
### Boot the image and update it
################################

echo_log "Running bootc disk image..."
VM_PID=$(run_vm "$IMG_SIGNED" "serial-console.log" --ovmf-dir=. --secureboot-vars=secboot_vars.fd --sharedir .)

PASSWORD="password"
LOGIN_TIMEOUT=40
if ! wait_for_vm_up "$LOGIN_TIMEOUT" "$PASSWORD"; then
    stop_vm "$VM_PID"
    exit 1
fi

assert_file_has_content serial-console.log "UEFI Secure Boot is enabled"

run_vm_command "rpm-ostree status"

# We should not have less installed yet
if run_vm_command "stat /usr/bin/less" ; then
    echo_fail "less unexpectedly installed before update"
    stop_vm "$VM_PID"
    exit 1
fi

echo_pass "Booted signed bootc disk image with Secure Boot enabled"

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
