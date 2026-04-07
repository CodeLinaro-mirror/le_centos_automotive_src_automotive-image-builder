#!/usr/bin/bash

source "$(dirname ${BASH_SOURCE[0]})"/setup-lib.sh

# Configure a-i-b base repository
echo "AIB_BASE_REPO='${AIB_BASE_REPO}'"

if [ -n "${AIB_BASE_REPO}" ]; then
    add_repo "aib-base-repo" ${AIB_BASE_REPO}
fi

# Configure a-i-b custom repository when specified
echo "AIB_CUSTOM_REPO='${AIB_CUSTOM_REPO}'"

if [ -n "${AIB_CUSTOM_REPO}" ]; then
    add_repo "aib-custom-repo" ${AIB_CUSTOM_REPO}
fi
