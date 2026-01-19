#!/usr/bin/bash -x

source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/test-lib.sh"

# Set up cleanup trap for policy resolution tests
cleanup_policy_tests() {
    rm -f installed-test.aibp.yml
    rm -f system-test.aibp.yml
    rm -f "${AIB_BASEDIR}/files/policies/installed-test.aibp.yml"
    rm -f "${AIB_BASEDIR}/files/policies/system-test.aibp.yml"
    sudo rm -f /etc/automotive-image-builder/policies/system-test.aibp.yml
    # Only remove directories if they're empty (i.e., we didn't break existing setup)
    sudo rmdir /etc/automotive-image-builder/policies 2>/dev/null || true
    sudo rmdir /etc/automotive-image-builder 2>/dev/null || true
}

# Update cleanup function parameters on each test artifact change
trap 'cleanup_path "out*" "*error.txt" "*.json" ; cleanup_policy_tests' 'EXIT'

# Helper functions for Compliance policy testing
_build_stage_selector() {
    local stage_type="$1"
    echo ".pipelines[] | .stages[] | select(.type == \"$stage_type\")"
}

assert_kernel_cmdline_option() {
    local json_file="$1"
    local option="$2"
    local stage_selector
    stage_selector=$(_build_stage_selector "org.osbuild.kernel-cmdline")
    assert_jq "$json_file" "$stage_selector | .options.kernel_opts | contains(\"$option\")"
}

assert_systemd_service_enabled() {
    local json_file="$1"
    local service="$2"
    local stage_selector
    stage_selector=$(_build_stage_selector "org.osbuild.systemd")
    assert_jq "$json_file" "$stage_selector | .options.enabled_services[] | select(. == \"$service\")"
}

assert_sysctl_config() {
    local json_file="$1"
    local key="$2"
    local value="$3"
    local stage_selector
    stage_selector=$(_build_stage_selector "org.osbuild.sysctld")
    assert_jq "$json_file" "$stage_selector | .options.config[] | select(.key == \"$key\" and .value == \"$value\")"
}

assert_sysctl_key_not_present() {
    local json_file="$1"
    local key="$2"
    local stage_selector
    stage_selector=$(_build_stage_selector "org.osbuild.sysctld")
    assert_jq_not "$json_file" "$stage_selector | .options.config[] | select(.key == \"$key\")"
}

assert_kernel_module_removed() {
    local json_file="$1"
    local module="$2"
    local stage_selector
    stage_selector=$(_build_stage_selector "org.osbuild-auto.kernel.remove-modules")
    assert_jq "$json_file" "$stage_selector | .options.remove | contains([\"$module\"])"
}

assert_kernel_module_not_removed() {
    local json_file="$1"
    local module="$2"
    local stage_selector
    stage_selector=$(_build_stage_selector "org.osbuild-auto.kernel.remove-modules")
    assert_jq_not "$json_file" "$stage_selector | .options.remove | contains([\"$module\"])"
}

set -eu

echo_log "=== Testing compliance policy enforcement ==="

# Test 1: Verify via variables dump that --policy flag enables policy correctly
echo_log "Test 1: Verifying --policy flag enables compliance policy..."
build --dry-run --policy compliance.aibp.yml --dump-variables simple-rpms.aib.yml "$NO_CTR_NAME" out
assert_file_has_content build-bootc.log '"disable_ipv6": true'
echo_log "Compliance policy variables correctly set"

# Test 2: Verify compliance policy denies forbidden RPMs
echo_log "Test 2: Testing compliance policy denies forbidden RPMs..."
if trybuild --dry-run --policy compliance.aibp.yml --extend-define extra_rpms=nano simple-rpms.aib.yml "$NO_CTR_NAME" out 2> rpm_error.txt; then
    echo_fail "Compliance policy should deny nano RPM"
    fatal "Compliance policy should have blocked nano"
else
    echo_log "Compliance policy correctly blocked forbidden RPM"
fi
assert_file_has_content rpm_error.txt "denied rpms"

# Test 4: Verify Compliance policy includes forbidden kernel modules in denylist
echo_log "Test 4: Testing Compliance policy includes forbidden kernel modules in denylist..."
# build with Compliance policy to generate OSBuild JSON
build --dry-run --policy compliance.aibp.yml --osbuild-manifest out4.json simple-rpms.aib.yml "$NO_CTR_NAME" out
assert_has_file out4.json
# Check for kernel module removal stage with specific modules in OSBuild JSON
assert_jq out4.json '.pipelines[] | .stages[]? | select(.type == "org.osbuild-auto.kernel.remove-modules")'
# Use jq to verify that the remove array contains the specific modules
assert_kernel_module_removed out4.json "bluetooth"
assert_kernel_module_removed out4.json "btusb"
echo_log "Compliance policy correctly includes forbidden kernel modules in denylist"

# Test 5: Verify --policy flag works with explicit compliance policy file
echo_log "Test 5: Testing explicit compliance policy file..."
build --dry-run --policy compliance.aibp.yml --dump-variables simple-rpms.aib.yml "$NO_CTR_NAME" out
assert_file_has_content build-bootc.log '"disable_ipv6": true'
echo_log "Explicit Compliance policy file works correctly"

# Test 6: Verify Compliance policy allows image mode but denies package mode
echo_log "Test 6: Testing Compliance policy mode restrictions..."
build --dry-run --policy compliance.aibp.yml simple-rpms.aib.yml "$NO_CTR_NAME" out
echo_log "Compliance policy allows bootc"

if trybuild_dev --dry-run --policy compliance.aibp.yml simple-rpms.aib.yml out.img 2> mode_error.txt; then
    echo_fail "Compliance policy should deny development build"
    fatal "Compliance policy should have blocked development build"
else
    echo_log "Compliance policy correctly blocked development build"
fi
assert_file_has_content mode_error.txt "mode 'package' is not in allowed list"


# Test 7: Verify Compliance policy manifest restrictions
echo_log "Test 7: Testing Compliance policy manifest restrictions..."

# Test that containers-storage transport is disallowed
echo_log "  Testing containers-storage transport restriction..."
if trybuild --dry-run --policy compliance.aibp.yml containers-storage.aib.yml "$NO_CTR_NAME" out 2> containers_error.txt; then
    echo_fail "Compliance policy should deny containers-storage transport"
    fatal "Compliance policy should have blocked containers-storage transport"
else
    echo_log "Compliance policy correctly blocked containers-storage transport"
fi
assert_file_has_content containers_error.txt "forbidden value 'containers-storage'"

# Test that experimental properties are disallowed
echo_log "  Testing experimental property restriction..."
if trybuild --policy compliance.aibp.yml experimental.aib.yml "$NO_CTR_NAME" out 2> experimental_error.txt; then
    echo_fail "Compliance policy should deny experimental properties"
    fatal "Compliance policy should have blocked experimental properties"
else
    echo_log "Compliance policy correctly blocked experimental properties"
fi
assert_file_has_content experimental_error.txt "forbidden property 'experimental'"

echo_log "Compliance policy manifest restrictions correctly enforced"

# Test 8: Comprehensive comparison of build output with and without compliance
echo_log "Test 8: Comprehensive comparison of build output with and without compliance..."

# Build without Compliance policy
echo_log "  Building without Compliance policy..."
build --dry-run --osbuild-manifest no_compliance_out.json simple-rpms.aib.yml "$NO_CTR_NAME" out
assert_has_file no_compliance_out.json

# Build with Compliance policy
echo_log "  Building with Compliance policy..."
build --dry-run --osbuild-manifest compliance_out.json --policy compliance.aibp.yml simple-rpms.aib.yml "$NO_CTR_NAME" out
assert_has_file compliance_out.json

# Check compliance-specific kernel command line options are present
echo_log "  Verifying compliance kernel options..."
assert_kernel_cmdline_option compliance_out.json "ipv6.disable=1"
assert_kernel_cmdline_option compliance_out.json "module.sig_enforce=1"

# Check compliance-specific systemd configurations
echo_log "  Verifying compliance systemd configurations..."
assert_systemd_service_enabled compliance_out.json "selinux-bools.service"

# Check compliance-specific sysctl values
echo_log "  Verifying compliance sysctl configurations..."
assert_sysctl_config compliance_out.json "net.ipv4.ip_forward" "0"
assert_sysctl_config compliance_out.json "net.ipv6.conf.all.forwarding" "0"
assert_sysctl_config compliance_out.json "kernel.dmesg_restrict" "1"

# Check compliance-specific SELinux booleans
echo_log "  Verifying compliance SELinux configurations..."
assert_jq compliance_out.json '.pipelines[] | .stages[] | select(.type == "org.osbuild.systemd.unit.create") | .options.config.Service.ExecStart[] | contains("httpd_can_network_connect=false")'

# Check that non-compliance build does NOT have compliance-specific sysctl configurations
echo_log "  Verifying non-compliance build does not have compliance-specific sysctl configurations..."
assert_sysctl_key_not_present no_compliance_out.json "net.ipv4.ip_forward"
assert_sysctl_key_not_present no_compliance_out.json "net.ipv6.conf.all.forwarding"
assert_sysctl_key_not_present no_compliance_out.json "kernel.dmesg_restrict"

# Verify that compliance build DOES have these specific sysctl values
echo_log "  Verifying compliance build has all required sysctl values..."
assert_jq compliance_out.json '.pipelines[] | .stages[] | select(.type == "org.osbuild.sysctld") | .options.config[] | select(.value == "0")'

echo_log "Compliance policy configuration verification passed"

echo_log "=== Testing policy resolution behavior ==="

# Test 9: Create a different policy in the base directory's policies folder
echo_log "Test 9: Testing policy name resolution from base directory..."
mkdir -p "${AIB_BASEDIR}/files/policies"

# Create a unique policy that will be installed in the base directory
cat > "${AIB_BASEDIR}/files/policies/installed-test.aibp.yml" << 'EOF'
name: installed-policy
description: Policy installed in base directory
restrictions:
  variables:
    force:
      from_installed_policy: true
EOF

# Test that policy name resolution works (should find it in files/policies)
build --dry-run --policy installed-test --dump-variables simple-rpms.aib.yml "$NO_CTR_NAME" out
assert_file_has_content build-bootc.log '"from_installed_policy": true'
echo_log "Policy name resolution from base directory works correctly"

# Test 10: Test that local file takes precedence
echo_log "Test 10: Testing local file precedence..."
# Create a local policy file with same name but different content
cat > installed-test.aibp.yml << 'EOF'
name: local-override-policy
description: Local policy that overrides installed one
restrictions:
  variables:
    force:
      from_local_policy: true
EOF

# This should use the local file, not the one in files/policies
build --dry-run --policy installed-test.aibp.yml --dump-variables simple-rpms.aib.yml "$NO_CTR_NAME" out
assert_file_has_content build-bootc.log '"from_local_policy": true'
# Should NOT contain the installed policy's variable
if grep -q '"from_installed_policy": true' build-bootc.log; then
    echo_fail "Local policy should override installed policy"
    fatal "Local file should take precedence over installed policy"
fi
echo_log "Local file precedence works correctly"

# Test 11: Test system-wide policy location (/etc/)
echo_log "Test 11: Testing system-wide policy location..."
# Create a system-wide policy
sudo mkdir -p /etc/automotive-image-builder/policies
cat > system-test.aibp.yml << 'EOF'
name: system-policy
description: System-wide policy in /etc/
restrictions:
  variables:
    force:
      from_system_policy: true
EOF
sudo cp system-test.aibp.yml /etc/automotive-image-builder/policies/

# Test that policy name resolution finds the system policy
build --dry-run --policy system-test --dump-variables simple-rpms.aib.yml "$NO_CTR_NAME" out
assert_file_has_content build-bootc.log '"from_system_policy": true'
echo_log "System-wide policy location works correctly"

# Test 12: Test that /etc/ takes precedence over package-provided
echo_log "Test 12: Testing /etc/ precedence over package-provided..."
# Create a package policy with same name but different content
cat > "${AIB_BASEDIR}/files/policies/system-test.aibp.yml" << 'EOF'
name: package-policy
description: Package-provided policy
restrictions:
  variables:
    force:
      from_package_policy: true
EOF

# This should use the /etc/ policy, not the package one
build --dry-run --policy system-test --dump-variables --osbuild-manifest out.json simple-rpms.aib.yml "$NO_CTR_NAME" out
assert_file_has_content build-bootc.log '"from_system_policy": true'
# Should NOT contain the package policy's variable
if grep -q '"from_package_policy": true' build-bootc.log; then
    echo_fail "System policy should override package policy"
    fatal "/etc/ policy should take precedence over package policy"
fi
echo_log "/etc/ policy correctly takes precedence over package policy"

echo_log "Policy resolution tests completed successfully"

# Test 13: Test target-specific policy configuration using compliance policy
echo_log "Test 13: Testing target-specific policy configuration..."

# Test with rcar_s4 target - should get global + rcar_s4-specific kernel module restrictions
echo_log "  Testing rcar_s4 target-specific kernel module restrictions..."
build --dry-run --policy compliance.aibp.yml --target rcar_s4 --osbuild-manifest rcar_s4_out.json simple-rpms.aib.yml "$NO_CTR_NAME" out

# Check that global modules are denied for rcar_s4
assert_kernel_module_removed rcar_s4_out.json "bluetooth"
assert_kernel_module_removed rcar_s4_out.json "btusb"

# Check that rcar_s4-specific modules are also denied
assert_kernel_module_removed rcar_s4_out.json "rcar_can"
assert_kernel_module_removed rcar_s4_out.json "rcar_thermal"
assert_kernel_module_removed rcar_s4_out.json "rcar_dmac"

# Test with qemu target - should only get global kernel module restrictions
echo_log "  Testing qemu target does not get rcar_s4-specific restrictions..."
build --dry-run --osbuild-manifest qemu_out.json --policy compliance.aibp.yml simple-rpms.aib.yml "$NO_CTR_NAME" out

# Check that global modules are denied for qemu
assert_kernel_module_removed qemu_out.json "bluetooth"
assert_kernel_module_removed qemu_out.json "btusb"

# Verify that qemu build does NOT have rcar_s4-specific module restrictions
assert_kernel_module_not_removed qemu_out.json "rcar_can"
assert_kernel_module_not_removed qemu_out.json "rcar_thermal"
assert_kernel_module_not_removed qemu_out.json "rcar_dmac"

echo_log "Target-specific policy configuration working correctly"

# Test 14: Test require_simple_manifest restriction
echo_log "Test 14: Testing require_simple_manifest restriction..."

# Test that compliance policy blocks low-level manifests
echo_log "  Testing compliance policy blocks low-level manifests..."
if trybuild_dev --dry-run --policy compliance.aibp.yml lowlevel.mpp.yml out.img 2> manifest_type_error.txt; then
    echo_fail "Compliance policy should deny low-level manifests"
    fatal "Compliance policy should have blocked low-level manifest"
else
    echo_log "Compliance policy correctly blocked low-level manifest"
fi
assert_file_has_content manifest_type_error.txt "simple manifest (.aib.yml)"
assert_file_has_content manifest_type_error.txt "low-level manifest (.mpp.yml)"

# Test that minimal policy (without require_simple_manifest) allows low-level manifests
echo_log "  Testing minimal policy allows low-level manifests..."
build --dry-run --policy minimal.aibp.yml --osbuild-manifest lowlevel_allowed_out.json lowlevel.mpp.yml "$NO_CTR_NAME" out
assert_has_file lowlevel_allowed_out.json
echo_log "Minimal policy correctly allows low-level manifest"

echo_log "require_simple_manifest restriction working correctly"

echo_pass "All Compliance policy tests passed successfully"

