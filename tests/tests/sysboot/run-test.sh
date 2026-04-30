#!/usr/bin/bash -x

source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/test-lib.sh"

# Update cleanup function parameters on each test artifact change
trap 'cleanup_path "out*" "*.json"' 'EXIT'

# Helper to select osbuild stages by type
_build_stage_selector() {
    local stage_type="$1"
    echo ".pipelines[] | .stages[] | select(.type == \"$stage_type\")"
}

# Assert that an org.osbuild.mkdir stage contains a path entry
assert_mkdir_path() {
    local json_file="$1"
    local expected_path="$2"
    local stage_selector
    stage_selector=$(_build_stage_selector "org.osbuild.mkdir")
    assert_jq "$json_file" "$stage_selector | .options.paths[] | select(.path == \"$expected_path\")"
}

# Assert that an org.osbuild.mkdir stage does NOT contain a path entry
assert_no_mkdir_path() {
    local json_file="$1"
    local expected_path="$2"
    local stage_selector
    stage_selector=$(_build_stage_selector "org.osbuild.mkdir")
    assert_jq_not "$json_file" "$stage_selector | .options.paths[] | select(.path == \"$expected_path\")"
}

# Assert that a systemd service is in the enabled_services list
assert_systemd_service_enabled() {
    local json_file="$1"
    local service="$2"
    local stage_selector
    stage_selector=$(_build_stage_selector "org.osbuild.systemd")
    assert_jq "$json_file" "$stage_selector | .options.enabled_services[] | select(. == \"$service\")"
}

# Assert that a systemd service is NOT in any enabled_services list
assert_systemd_service_not_enabled() {
    local json_file="$1"
    local service="$2"
    local stage_selector
    stage_selector=$(_build_stage_selector "org.osbuild.systemd")
    assert_jq_not "$json_file" "$stage_selector | .options.enabled_services[] | select(. == \"$service\")"
}

# Assert that an org.osbuild.ln stage contains a symlink entry
assert_symlink_ln() {
    local json_file="$1"
    local expected_target="$2"
    local expected_link="$3"
    local stage_selector
    stage_selector=$(_build_stage_selector "org.osbuild.ln")
    assert_jq "$json_file" "$stage_selector | .options.paths[] | select(.target == \"$expected_target\" and .link_name == \"$expected_link\")"
}

set -eu

echo_log "=== Testing sysboot integration ==="

# Test 1: Verify system_boot_check variable is set when boot_checks are configured
echo_log "Test 1: Verifying system_boot_check variable is enabled..."
build --dry-run --dump-variables sysboot.aib.yml "$NO_CTR_NAME" out
assert_file_has_content build-bootc.log '"system_boot_check": true'
echo_log "system_boot_check variable correctly set to true"

# Test 2: Full sysboot manifest - verify mkdir stages for command drop-in directories
echo_log "Test 2: Verifying mkdir stages for boot check command drop-in directories..."
build --dry-run --osbuild-manifest out2.json sysboot.aib.yml "$NO_CTR_NAME" out
assert_has_file out2.json

assert_mkdir_path out2.json "/usr/lib/systemd/system/sysboot-check@success.service.d"
assert_mkdir_path out2.json "/usr/lib/systemd/system/sysboot-check@check-network.service.d"
echo_log "mkdir stages for command drop-in directories are present"

# Test 3: Verify mkdir stage for systemd unit drop-in directory
echo_log "Test 3: Verifying mkdir stage for systemd unit drop-in directory..."
assert_mkdir_path out2.json "/usr/lib/systemd/system/httpd.service.d"
echo_log "mkdir stage for systemd unit drop-in directory is present"

# Test 4: Verify systemd services are enabled
echo_log "Test 4: Verifying sysboot services are enabled..."
assert_systemd_service_enabled out2.json "sysboot-check@success.service"
assert_systemd_service_enabled out2.json "sysboot-check@check-network.service"
assert_systemd_service_enabled out2.json "sysboot-health.target"
echo_log "All sysboot services are correctly enabled"

# Test 5: Verify symlink for systemd unit sysboot drop-in
echo_log "Test 5: Verifying symlink for systemd unit sysboot drop-in..."
assert_symlink_ln out2.json "/usr/share/sysboot/service.d/sysboot.conf" "tree:///usr/lib/systemd/system/httpd.service.d/sysboot.conf"
echo_log "Symlink for systemd unit sysboot drop-in is present"

# Test 6: Verify mkdir stage properties (mode, parents, exist_ok)
echo_log "Test 6: Verifying mkdir stage properties..."
stage_selector=$(_build_stage_selector "org.osbuild.mkdir")
assert_jq out2.json "$stage_selector | .options.paths[] | select(.path == \"/usr/lib/systemd/system/sysboot-check@success.service.d\" and .mode == 493 and .parents == true and .exist_ok == true)"
echo_log "mkdir stage properties (mode=0o755/493, parents=true, exist_ok=true) are correct"

# Test 7: Commands-only manifest - verify only command-related stages are present
echo_log "Test 7: Testing commands-only boot_checks..."
build --dry-run --osbuild-manifest out7.json sysboot-commands-only.aib.yml "$NO_CTR_NAME" out
assert_has_file out7.json

assert_mkdir_path out7.json "/usr/lib/systemd/system/sysboot-check@success.service.d"
assert_systemd_service_enabled out7.json "sysboot-check@success.service"
assert_systemd_service_enabled out7.json "sysboot-health.target"
# No systemd unit drop-ins should be present
assert_no_mkdir_path out7.json "/usr/lib/systemd/system/httpd.service.d"
echo_log "Commands-only boot_checks produce correct stages"

# Test 8: Systemd-only manifest - verify only systemd-related stages are present
echo_log "Test 8: Testing systemd-only boot_checks..."
build --dry-run --osbuild-manifest out8.json sysboot-systemd-only.aib.yml "$NO_CTR_NAME" out
assert_has_file out8.json

assert_mkdir_path out8.json "/usr/lib/systemd/system/httpd.service.d"
assert_symlink_ln out8.json "/usr/share/sysboot/service.d/sysboot.conf" "tree:///usr/lib/systemd/system/httpd.service.d/sysboot.conf"
assert_systemd_service_enabled out8.json "sysboot-health.target"
assert_no_mkdir_path out8.json "/usr/lib/systemd/system/sysboot-check@success.service.d"
echo_log "Systemd-only boot_checks produce correct stages"

# Test 9: No sysboot manifest - verify system_boot_check is false and no sysboot stages
echo_log "Test 9: Testing manifest without boot_checks..."
build --dry-run --dump-variables --osbuild-manifest out9.json no-sysboot.aib.yml "$NO_CTR_NAME" out
assert_has_file out9.json

assert_file_has_content build-bootc.log '"system_boot_check": false'
assert_no_mkdir_path out9.json "/usr/lib/systemd/system/sysboot-check@success.service.d"
assert_systemd_service_not_enabled out9.json "sysboot-health.target"
echo_log "Manifest without boot_checks correctly omits sysboot stages"

echo_pass "All sysboot integration tests passed successfully"
