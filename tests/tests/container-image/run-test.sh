#!/usr/bin/bash -x

source "$(dirname ${BASH_SOURCE[0]})"/../../scripts/test-lib.sh

TAR_FILE="out.tar"

# Update cleanup function parameters on each test artifact change
trap 'cleanup_path "$TAR_FILE" "usr"' 'EXIT'

echo_log "Starting build for container_images and qm.content.container_images test..."
build --tar \
    --extend-define tar_paths="['usr/lib/containers/storage/overlay-images', 'usr/lib/qm/rootfs/usr/lib/containers/storage/overlay-images']" \
    container-image.aib.yml \
    "$TAR_FILE"
echo_log "Build completed, output: $TAR_FILE"

echo_log "Extracting $TAR_FILE..."
tar xvf "$TAR_FILE" > /dev/null

BASE_IMAGE_JSON="./usr/lib/containers/storage/overlay-images/images.json"
QM_IMAGE_JSON="./usr/lib/qm/rootfs/usr/lib/containers/storage/overlay-images/images.json"

# Check both images.json files exist
assert_has_file "$BASE_IMAGE_JSON"
assert_has_file "$QM_IMAGE_JSON"

# Validate container from base section
assert_file_has_content "$BASE_IMAGE_JSON" "localhost/auto-apps:latest"

# Validate container from QM section
assert_file_has_content "$QM_IMAGE_JSON" "localhost/qm-apps:latest"

echo_pass "Custom container is properly installed in the image"
