#!/usr/bin/bash

source "$(dirname ${BASH_SOURCE[0]})"/../../scripts/test-lib.sh

TAR_FILE="out.tar"

# Update cleanup function parameters on each test artifact change
trap 'cleanup_path "$TAR_FILE" "etc" "usr" "error.txt" "error2.txt"' 'EXIT'

echo_log "Starting build..."
build --tar \
    systemd-services.aib.yml \
    "$TAR_FILE"
echo_log "Build completed, output: $TAR_FILE"

echo_log "Extracting $TAR_FILE..."
tar xvf "$TAR_FILE" > /dev/null

echo_log "Checking symlinks for content section"
assert_service_enabled sshd.service content
assert_service_disabled httpd.service content
assert_service_masked kdump.service content

echo_log "Checking symlinks for qm section"
assert_service_enabled crond.service qm
assert_service_disabled cups.service qm
assert_service_masked chronyd.service qm

echo_pass "systemd services symlink verification completed!"
