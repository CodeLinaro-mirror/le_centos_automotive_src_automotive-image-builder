#!/usr/bin/bash -x

source "$(dirname ${BASH_SOURCE[0]})"/../../scripts/test-lib.sh

IMG_FILE="out.img"

# Update cleanup function parameters on each test artifact change
trap 'cleanup_path "$IMG_FILE"' 'EXIT'

echo_log "Starting build..."
build partition-relative-size.aib.yml "$NO_CTR_NAME" "$IMG_FILE"
echo_log "Build completed, output: $IMG_FILE"

assert_partition_relative_size "$IMG_FILE" var 0.2
assert_partition_relative_size "$IMG_FILE" qm_var 0.1


