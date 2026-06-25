#!/usr/bin/bash

source "$(dirname ${BASH_SOURCE[0]})"/test-lib.sh

if [ "$PTR_PREPARE_FINISHED" == "yes" ]; then
    echo "Prepare phase was already executed by parallel-test-runner.sh, skipping"
    exit 0
fi

IF_NEEDED="--if-needed"
if [ "$REBUILD_BOOTC_BUILDER" == "yes" ]; then
    # Force the rebuild of bootc builder container
    IF_NEEDED=""
fi

build_bootc_builder "$IF_NEEDED"
