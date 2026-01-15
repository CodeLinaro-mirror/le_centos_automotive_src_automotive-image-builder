#!/usr/bin/bash -x

source "$(dirname ${BASH_SOURCE[0]})"/../../scripts/test-lib.sh

# Define connection and VM parameters
IMG_NAME="test.img"
PASSWORD="password"
LOGIN_TIMEOUT=40

SE_MODE_EXPECTED="enforcing"
SE_POL_NAME_EXPECTED="targeted"
EXPECTED_SELINUX_BOOLEANS=(
    "selinuxuser_tcp_server=on"
    "httpd_can_network_connect=on"
    "selinuxuser_ping=off"
    "deny_bluetooth=on"
)

# Update cleanup function parameters on each test artifact change
trap 'cleanup_path "$IMG_NAME"' 'EXIT'

# Build the image
echo_log "Building AIB image..."
build \
    --target qemu \
    selinux-config.aib.yml \
    "$NO_CTR_NAME" \
    "$IMG_NAME"

# Check if image was created
assert_image_exists "$IMG_NAME"

# Start the VM using the built AIB image
VM_PID=$(run_vm "$IMG_NAME")

# Wait until VM becomes available or fail fast
if ! wait_for_vm_up "$LOGIN_TIMEOUT" "$PASSWORD"; then
    stop_vm "$VM_PID"
    exit 1
fi

# Retrieve the SELinux configuration
SE_MODE=$(run_vm_command "sestatus | awk -F ':' '/Current mode/ { gsub(\" \",\"\"); print \$2}'")
echo_log "Detected SELinux mode: '$SE_MODE'"
SE_POL_NAME=$(run_vm_command "sestatus | awk -F ':' '/Loaded policy name/ { gsub(\" \",\"\"); print \$2}'")
echo_log "Detected SELinux policy name: '$SE_POL_NAME'"
SEBOOLS=$(run_vm_command "getsebool -a")
echo_log "SELinux booleans inside VM: $SEBOOLS"

# Verify the SELinux configuration
assert_streq "$SE_MODE" "$SE_MODE_EXPECTED" "SELinux mode set to '$SE_MODE' but expected '$SE_MODE_EXPECTED'"
assert_streq "$SE_POL_NAME" "$SE_POL_NAME_EXPECTED" "SELinux policy name is '$SE_POL_NAME' but expected '$SE_POL_NAME_EXPECTED'"


# Verify that all expected SELinux booleans are present and set correctly
missing_opts=()
all_present=1
for opt in "${EXPECTED_SELINUX_BOOLEANS[@]}"; do
    boolean_name="${opt%%=*}"
    expected_value="${opt##*=}"
    actual_value=$(run_vm_command "getsebool $boolean_name" | awk '{print $3}')
    if [ "$actual_value" == "$expected_value" ]; then
        echo_log "SELinux boolean $boolean_name is set correctly to $actual_value"
    else
        echo_fail "SELinux boolean $boolean_name is not set correctly. Expected: $expected_value, Found: $actual_value"
        missing_opts+=("$boolean_name")
        all_present=0
    fi
done

# Clean up air process
stop_vm "$VM_PID"

# Report test result
if [ $all_present -ne 1 ]; then
    echo_fail "Missing SELinux booleans: ${missing_opts[*]}"
    exit 1
fi

echo_pass "SELinux configuration verified successfully"
