#!/usr/bin/bash -x

source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/test-lib.sh"

# Update cleanup function parameters on each test artifact change
trap 'cleanup_path "out*" "*.json"' 'EXIT'

# Helper to select osbuild stages by type
_build_stage_selector() {
    local stage_type="$1"
    echo ".pipelines[] | .stages[] | select(.type == \"$stage_type\")"
}

assert_has_stage() {
    local json_file="$1"
    local stage_selector
    stage_selector=$(_build_stage_selector "$2")
    assert_jq "$json_file" "$stage_selector"
}

assert_has_no_stage() {
    local json_file="$1"
    local stage_selector
    stage_selector=$(_build_stage_selector "$2")
    assert_jq_not "$json_file" "$stage_selector"
}

assert_idmap_stage() {
    local json_file="$1"
    local stage_selector
    stage_selector=$(_build_stage_selector "org.osbuild.idmap")
    assert_jq "$json_file" "$stage_selector | .options.items[] | select(.user==\"qm_root\" and .group==\"qm_root\")"
}


set -eu

echo_log "=== Testing QM user namespaces ==="

# Test 1: Verify user namespaces disabled by default (no configuration)
echo_log "Test 1: Verifying qm_use_userns variable default..."
build --dry-run --dump-variables --osbuild-manifest build-default.json userns-default.aib.yml "$NO_CTR_NAME" out
assert_file_has_content build-bootc.log '"qm_use_userns": false'
echo_log "qm_use_userns variable correctly set to false by default"
assert_has_no_stage "build-default.json" "org.osbuild-auto.qm.userns"
assert_has_no_stage "build-default.json" "org.osbuild.idmap"

# Test 2: Verify user namespaces enabled when configured
echo_log "Test 2: Verifying qm_use_userns variable set to true..."
build --dry-run --dump-variables --osbuild-manifest build-enabled.json userns-enabled.aib.yml "$NO_CTR_NAME" out
assert_file_has_content build-bootc.log '"qm_use_userns": true'
echo_log "qm_use_userns variable correctly set to false by default"
assert_has_stage "build-enabled.json" "org.osbuild-auto.qm.userns"
assert_has_stage "build-enabled.json" "org.osbuild.idmap"
assert_idmap_stage "build-enabled.json"

echo_pass "All userns integration tests passed successfully"
