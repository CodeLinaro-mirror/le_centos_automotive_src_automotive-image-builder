#!/usr/bin/bash -x

source "$(dirname ${BASH_SOURCE[0]})"/../../scripts/test-lib.sh

TAR_FILE="out.tar"

# Update cleanup function parameters on each test artifact change
trap 'cleanup_path "$TAR_FILE" "etc" "usr"' 'EXIT'

echo_log "Starting build for auth users and groups test..."
build --tar \
    --extend-define "tar_paths=['etc','usr/lib']" \
    users-and-groups.aib.yml \
    "$TAR_FILE"
echo_log "Build completed, output: $TAR_FILE"

echo_log "Extracting $TAR_FILE..."
tar xvf "$TAR_FILE" --no-same-owner --no-same-permissions

# Native bootc keeps accounts in /etc instead of splitting them for OSTree.
if test -f ./usr/lib/composefs/setup-root-conf.toml; then
    PASSWD_PATH="./etc/passwd"
    GROUP_PATH="./etc/group"
else
    PASSWD_PATH="./usr/lib/passwd"
    GROUP_PATH="./usr/lib/group"
fi
SHADOW_PATH="./etc/shadow"
EXPECTED_HASH='$6$xoLqEUz0cGGJRx01$H3H/bFm0myJPULNMtbSsOFd/2BnHqHkMD92Sfxd.EKM9hXTWSmELG8cf205l6dktomuTcgKGGtGDgtvHVXSWU.'

# Validate expected users
assert_has_file "$PASSWD_PATH"
assert_file_has_content "$PASSWD_PATH" "guest:x:2000:2000::/var/guest:/bin/bash"
assert_file_has_content "$PASSWD_PATH" "foo:x:2042:2042::/home/foo:/sbin/nologin"

# Validate expected groups
assert_has_file "$GROUP_PATH"
assert_file_has_content "$GROUP_PATH" "guest:x:2000:"
assert_file_has_content "$GROUP_PATH" "foo:x:2042:"
assert_file_has_content "$GROUP_PATH" "devs:x:2050:guest"

# Validate presence of /etc/shadow and expected password hash entry
assert_has_file "$SHADOW_PATH"
chmod a+r "$SHADOW_PATH"
assert_file_has_content "$SHADOW_PATH" "guest:$EXPECTED_HASH"

echo_pass "users and groups validated successfully."

