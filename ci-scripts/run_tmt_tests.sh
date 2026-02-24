#!/bin/bash

source "$(dirname ${BASH_SOURCE[0]})"/aws-lib.sh

function section_start () {
  local section_title="${1}"
  local section_description="${2:-$section_title}"

  echo -e "section_start:`date +%s`:${section_title}[collapsed=true]\r\e[0K${section_description}"
}

# Function for ending the section
function section_end () {
  local section_title="${1}"

  echo -e "section_end:`date +%s`:${section_title}\r\e[0K"
}

AIB_DISTRO=${1:-autosd10-sig}
# Base repository for AIB packages needs to be aligned with requested distro
if [[ "${AIB_DISTRO}" == *"autosd9"* ]]; then
    AIB_BASE_REPO="https://autosd.sig.centos.org/AutoSD-9/nightly/repos/AutoSD/compose/AutoSD/\$arch/os/"
    CS_VERSION=9
else
    AIB_BASE_REPO="https://autosd.sig.centos.org/AutoSD-10/nightly/repos/AutoSD/compose/AutoSD/\$arch/os/"
    CS_VERSION=10
fi

section_start duffy_setup "Attaching to AWS"

export SESSION_FILE="$PWD/duffy.session"

if [ ! -f "$SESSION_FILE" ]; then
    echo "Retrieving an AWS host ..."
    get_aws_session "metal-ec2-c5n-centos-${CS_VERSION}s-x86_64" "$SESSION_FILE"
    if [ $? -ne 0 ]; then
        exit 1
    fi
fi

# Release AWS session on exit
trap 'release_aws_session $SESSION_FILE' EXIT

ip=$(get_ip_from_session $SESSION_FILE)
echo "IP address: $ip"

# Copy SRPM from previous job artifacts into remote host
# Assuming the CI job passed it as an artifact
SRC_RPM=$(find .. -name '*.src.rpm' | head -n 1)

if [ -z "$SRC_RPM" ]; then
  echo "SRPM not found! Exiting."
  exit 1
fi

echo "Found SRPM: $SRC_RPM"

# Create target directory for SRPM files on the AWS machine
ssh -o StrictHostKeyChecking=no -i $PWD/automotive_sig.ssh root@$ip <<EOF
  mkdir -p /var/tmp/aib-srpm
EOF

# Copy the SRPM to the remote AWS instance (provisioned with Duffy)
scp -o StrictHostKeyChecking=no -i $PWD/automotive_sig.ssh *.src.rpm root@$ip:/var/tmp/aib-srpm/

# Make sure libsepol is up to date
ssh -o StrictHostKeyChecking=no -i $PWD/automotive_sig.ssh root@$ip dnf upgrade -y libsepol

section_end duffy_setup

# Run tests with 5 parallel test executions
export TMT_RUN_OPTIONS="-q \
  -eNODE=$ip \
  -eNODE_SSH_KEY=$PWD/automotive_sig.ssh \
  -eBUILD_AIB_RPM=yes \
  -eAIB_DISTRO=$AIB_DISTRO \
  -eAIB_BASE_REPO=$AIB_BASE_REPO \
  plan --name connect"
( cd tests && ../ci-scripts/parallel-test-runner.sh 5 )

success=$?

mkdir -p tmt-run
cp -r /var/tmp/tmt/* tmt-run/

exit $success
