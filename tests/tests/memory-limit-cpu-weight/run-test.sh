#!/usr/bin/bash -x

source "$(dirname ${BASH_SOURCE[0]})"/../../scripts/test-lib.sh

TAR_FILE="out.tar"

# Define expected config path and values
RESOURCE_CONF_PATH_QM1="usr/share/containers/systemd/qm.container.d/10-automotive.conf"
RESOURCE_CONF_PATH_QM2="usr/lib/systemd/system/qm.service.d/10-automotive.conf"
EXPECTED_MEMORY_MAX="MemoryMax=100M"
EXPECTED_MEMORY_HIGH="MemoryHigh=80M"
EXPECTED_CPU_WEIGHT="CPUWeight=50"

# Update cleanup function parameters on each test artifact change
trap 'cleanup_path "$TAR_FILE" "$RESOURCE_CONF_PATH_QM1" "$RESOURCE_CONF_PATH_QM2"' 'EXIT'

echo_log "Starting build..."
build --tar \
    --extend-define "tar_paths=['usr/lib/systemd/system','usr/share/containers']" \
    memory-limit-cpu-weight.aib.yml \
    "$TAR_FILE"
echo_log "Build completed, output: $TAR_FILE"

echo_log "Extracting $TAR_FILE..."
if tar tf "$TAR_FILE" "$RESOURCE_CONF_PATH_QM1" > /dev/null 2>&1; then
    RESOURCE_CONF_PATH="$RESOURCE_CONF_PATH_QM1"
else
    RESOURCE_CONF_PATH="$RESOURCE_CONF_PATH_QM2"
fi
tar xvf "$TAR_FILE" "$RESOURCE_CONF_PATH" > /dev/null

assert_has_file "$RESOURCE_CONF_PATH"
assert_file_has_content "$RESOURCE_CONF_PATH" \
  "^$EXPECTED_MEMORY_MAX" \
  "^$EXPECTED_MEMORY_HIGH" \
  "^$EXPECTED_CPU_WEIGHT"

echo_pass "memory_limit and cpu_weight successfully verified in the QM image."
