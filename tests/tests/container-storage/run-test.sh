#!/usr/bin/bash -x

source "$(dirname ${BASH_SOURCE[0]})"/../../scripts/test-lib.sh

STORAGE=$PWD/storage
function cleanup()
{
    $SUDO umount $STORAGE/overlay
    $SUDO rm -rf $STORAGE
}

trap cleanup EXIT

SOURCE_IMAGE_ORIGIN=registry.gitlab.com/centos/automotive/sample-images/demo/auto-apps
SOURCE_IMAGE=localhost/auto-apps
BUILT_IMAGE="localhost/container-storage"
INJECTED_IMAGE="localhost/container-storage-injected"

echo_log "Copying source image to local store"
$SUDO skopeo copy docker://$SOURCE_IMAGE_ORIGIN containers-storage:[overlay@$STORAGE]$SOURCE_IMAGE

echo_log "Building bootc image to local store"
build --container-storage $STORAGE container-storage.aib.yml  $BUILT_IMAGE
echo_log "Build completed, "

# separate storage should have both images
# shellcheck disable=SC2024
$SUDO cat storage/overlay-images/images.json | jq -r .[].names[0] > images
assert_file_has_content images $SOURCE_IMAGE
assert_file_has_content images $BUILT_IMAGE

# host storage should have none of the images
# shellcheck disable=SC2024
$SUDO podman images > host-images
assert_file_doesnt_have_content host-images $SOURCE_IMAGE
assert_file_doesnt_have_content host-images $BUILT_IMAGE

$AIB extract-for-signing --container-storage $PWD/storage $BUILT_IMAGE to-sign

assert_has_file to-sign/signing_info.json

$AIB inject-signed --container-storage $PWD/storage $BUILT_IMAGE to-sign $INJECTED_IMAGE

# shellcheck disable=SC2024
$SUDO cat storage/overlay-images/images.json | jq -r .[].names[0] > images
assert_file_has_content images $INJECTED_IMAGE

echo_pass "Container build with custom container store worked"
