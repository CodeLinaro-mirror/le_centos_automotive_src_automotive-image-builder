#!/usr/bin/bash -x

source "$(dirname ${BASH_SOURCE[0]})"/../../scripts/test-lib.sh

TAR_FILE="out.tar"

# Update cleanup function parameters on each test artifact change
trap 'cleanup_path "$TAR_FILE" "etc" "usr" "error.txt" "error2.txt"' 'EXIT'

echo_log "Starting build..."
tar_paths="[\
'etc/custom-files',\
'etc/test-glob',\
'etc/test-glob-preserve',\
'etc/test-glob-preserve-log',\
'usr/lib/qm/rootfs/etc/qm-custom',\
'usr/lib/qm/rootfs/usr/sbin',\
'usr/sbin',\
'usr/share/containers/systemd'\
]"
build --tar \
    --extend-define tar_paths="$tar_paths" \
    custom-files.aib.yml \
    "$TAR_FILE"
echo_log "Build completed, output: $TAR_FILE"

echo_log "Extracting $TAR_FILE..."
tar xvf "$TAR_FILE"

echo_log "Checking file contents..."
assert_file_has_content etc/custom-files/file1.txt "name: add_files"
assert_file_has_content etc/custom-files/file2.txt "This is the file content"
assert_file_has_content etc/custom-files/file3.txt "Automotive Image Builder"
assert_file_has_content usr/lib/qm/rootfs/etc/qm-custom/file4.txt "This is the qm file content"

echo_log "Checking flattened glob files..."
# Test that files were copied and flattened to /etc/test-glob
assert_file_has_content etc/test-glob/file1.txt "This is test file 1"
assert_file_has_content etc/test-glob/file2.txt "This is test file 2"

echo_log "Checking flattened recursive glob files..."
# Test that files were copied without directory structure
assert_not_has_file etc/test-glob/subdir1/app.log
assert_file_has_content etc/test-glob-preserve-log/app.log "App log from subdir1"
assert_not_has_file etc/test-glob/subdir2/system.log
assert_file_has_content etc/test-glob-preserve-log/system.log "System log from subdir2"

echo_log "Checking path-preserved glob full copy..."
# Test that files were copied with full preserved directory structure
assert_file_has_content etc/test-glob-preserve/file1.txt "This is test file 1"
assert_file_has_content etc/test-glob-preserve/file2.txt "This is test file 2"
assert_file_has_content etc/test-glob-preserve/subdir1/app.log "App log from subdir1"
assert_file_has_content etc/test-glob-preserve/subdir2/system.log "System log from subdir2"

# Test that files were copied to /usr/ with preserved paths
# This verifies that directories are created with exist_ok=True
assert_file_has_content usr/share/containers/systemd/test.container "# Test container configuration"

echo_pass "Image contains all required files"

echo_log "Checking permissions and ownership (content)..."
# file1.txt - custom permissions and ownership
assert_file_has_permission etc/custom-files/file1.txt "777"
assert_file_has_owner etc/custom-files/file1.txt "65534:65534"
# file2.txt - default permissions and ownership
assert_file_has_permission etc/custom-files/file2.txt "644"
assert_file_has_owner etc/custom-files/file2.txt "0:0"

echo_log "Checking permissions and ownership (QM)..."
# file4.txt - custom permissions and ownership
assert_file_has_permission usr/lib/qm/rootfs/etc/qm-custom/file4.txt "777"
assert_file_has_owner usr/lib/qm/rootfs/etc/qm-custom/file4.txt "65534:65534"
# file5.txt - default permissions and ownership
assert_file_has_permission usr/lib/qm/rootfs/etc/qm-custom/file5.txt "644"
assert_file_has_owner usr/lib/qm/rootfs/etc/qm-custom/file5.txt "0:0"

echo_log "Checking symlinks (content)..."
assert_symlink_target "etc/custom-files/link-absolute" "/etc/custom-files/file1.txt"
assert_symlink_target "etc/custom-files/link-relative" "file2.txt"

echo_log "Checking symlinks (QM)..."
assert_symlink_target "usr/lib/qm/rootfs/etc/qm-custom/qm-link-absolute" "/etc/qm-custom/file4.txt"
assert_symlink_target "usr/lib/qm/rootfs/etc/qm-custom/qm-link-relative" "file5.txt"

echo_pass "All file permissions, ownerships, and symlinks are correctly set."

echo_log "Checking removed files in content section..."
assert_not_has_file "usr/sbin/crond"

echo_log "Checking files in qm.content section..."
assert_not_has_file "usr/lib/qm/rootfs/usr/sbin/cupsd"

echo_pass "Files marked for removal are not present in the image."

echo_log "Testing invalid custom top-level directory..."
if trybuild --tar invalid-custom-dir.aib.yml invalid-out.tar 2> error.txt; then
    echo_fail "Build should have failed for custom top-level directory /custom-dir"
    exit 1
else
    echo_pass "Build failed as expected for custom top-level directory"
fi

echo_log "Checking error message content..."
assert_file_has_content error.txt "Path '/custom-dir' is not allowed"

echo_log "Testing invalid root-level file..."
if trybuild --tar invalid-root-path.aib.yml invalid-out2.tar 2> error2.txt; then
    echo_fail "Build should have failed for file directly in root /"
    exit 1
else
    echo_pass "Build failed as expected for root-level file"
fi

echo_log "Checking error message content..."
assert_file_has_content error2.txt "Path '/test.txt' is not allowed"

echo_pass "Path validation correctly rejects invalid paths"

