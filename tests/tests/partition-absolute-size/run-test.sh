#!/usr/bin/bash -x

source "$(dirname ${BASH_SOURCE[0]})"/../../scripts/test-lib.sh

IMG_FILE="out.img"

# Update cleanup function parameters on each test artifact change
trap 'cleanup_path "$IMG_FILE"' 'EXIT'

echo_log "Starting build..."
build \
    --target qemu \
    partition-absolute-size.aib.yml \
    "$NO_CTR_NAME" \
    "$IMG_FILE"
echo_log "Build completed, output: $IMG_FILE"

assert_partition_absolute_size "$IMG_FILE" var 524288000 10240
assert_partition_absolute_size "$IMG_FILE" qm_var 314572800 10240
