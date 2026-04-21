#!/usr/bin/bash -x

source "$(dirname ${BASH_SOURCE[0]})"/../../scripts/test-lib.sh

TAR_FILE="out.tar"

# Update cleanup function parameters on each test artifact change
trap 'cleanup_path "$TAR_FILE" "etc" "usr"' 'EXIT'

echo_log "Starting build for static network configuration..."
build --tar \
    --extend-define "tar_paths=['etc/hostname','etc/main.nmstate','etc/main-initrd.nmstate','usr/lib/boot-check.d/nmstate.conf','usr/lib/modules-load.d/auto-modules.conf']" \
    network-static.aib.yml \
    "$TAR_FILE"
echo_log "Build completed, output: $TAR_FILE"

echo_log "Extracting $TAR_FILE..."
tar xvf "$TAR_FILE"

# Expected hostname configuration
HOSTNAME_FILE_PATH="./etc/hostname"
EXPECTED_HOSTNAME='test-host-name-automotive'

# Validate /etc/hostname contains the expected value
assert_has_file "$HOSTNAME_FILE_PATH"
assert_file_has_content "$HOSTNAME_FILE_PATH" "$EXPECTED_HOSTNAME"

# Check for static IP config
NMSTATE_FILE="./etc/main.nmstate"
NMSTATE_INITRD_FILE="./etc/main-initrd.nmstate"
BOOTCONF_FILE="./usr/lib/boot-check.d/nmstate.conf"
MODULES_FILE="./usr/lib/modules-load.d/auto-modules.conf"

# Check the main-initrd.nmstate file
assert_has_file "$NMSTATE_INITRD_FILE"
assert_file_has_content "$NMSTATE_INITRD_FILE" "name: eth0"
assert_file_has_content "$NMSTATE_INITRD_FILE" "ip: 192.168.0.10"
assert_file_has_content "$NMSTATE_INITRD_FILE" "prefix-length: 24"
assert_file_has_content "$NMSTATE_INITRD_FILE" "next-hop-address: 192.168.0.1"

# Check the main.nmstate file
assert_has_file "$NMSTATE_FILE"
assert_file_has_content "$NMSTATE_FILE" "server:"
assert_file_has_content "$NMSTATE_FILE" "192.168.0.53"

# Check boot helper file
assert_has_file "$BOOTCONF_FILE"
assert_file_has_content "$BOOTCONF_FILE" "ip 192.168.0.10 24"
assert_file_has_content "$BOOTCONF_FILE" "default_gw 192.168.0.1"
assert_file_has_content "$BOOTCONF_FILE" "nameserver 192.168.0.53"

# Check module load config
assert_has_file "$MODULES_FILE"
assert_file_has_content "$MODULES_FILE" "e1000"

echo_pass "Hostname and static network configuration validated successfully."

