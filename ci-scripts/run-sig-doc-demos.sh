#!/bin/bash

source "$(dirname "${BASH_SOURCE[0]}")"/aws-lib.sh

function section_start () {
  local section_title="${1}"
  local section_description="${2:-$section_title}"

  echo -e "section_start:$(date +%s):${section_title}[collapsed=true]\r\e[0K${section_description}"
}

function section_end () {
  local section_title="${1}"

  echo -e "section_end:$(date +%s):${section_title}\r\e[0K"
}

section_start duffy_setup "Attaching to AWS"

export SESSION_FILE="$PWD/duffy.session"

if [ ! -f "$SESSION_FILE" ]; then
    echo "Retrieving an AWS host ..."
    if ! get_aws_session "metal-ec2-c5n-centos-10s-x86_64" "$SESSION_FILE"; then
        exit 1
    fi
fi

trap 'release_aws_session "$SESSION_FILE"' EXIT

ip=$(get_ip_from_session "$SESSION_FILE")
echo "IP address: $ip"

SRC_RPM=$(find . -name '*.src.rpm' | head -n 1)

if [ -z "$SRC_RPM" ]; then
    echo "SRPM not found! Exiting."
    exit 1
fi

echo "Found SRPM: $SRC_RPM"

SRPM_DIR="/var/tmp/sig-docs-srpm"

ssh \
    -o StrictHostKeyChecking=no \
    -i "$PWD/automotive_sig.ssh" \
    root@"$ip" \
    "mkdir -p '$SRPM_DIR'"

scp \
    -o StrictHostKeyChecking=no \
    -i "$PWD/automotive_sig.ssh" \
    "$SRC_RPM" \
    root@"$ip":"$SRPM_DIR"/

ssh \
    -o StrictHostKeyChecking=no \
    -i "$PWD/automotive_sig.ssh" \
    root@"$ip" \
    dnf upgrade -y libsepol

section_end duffy_setup

rm -rf sig-docs
git clone https://gitlab.com/CentOS/automotive/sig-docs.git

env -i \
    HOME="$HOME" \
    LC_CTYPE="${LC_ALL:-${LC_CTYPE:-$LANG}}" \
    PATH="$PATH" \
    USER="$USER" \
    TMT_RUN_OPTIONS="-q \
        -eNODE=$ip \
        -eNODE_SSH_KEY=$PWD/automotive_sig.ssh \
        -eBUILD_LOCAL_RPM=yes \
        -eSRPM_DIR=$SRPM_DIR \
        plan --name connect" \
    bash -c "( cd sig-docs/tests && ../ci-scripts/parallel-test-runner.sh 5 connect )"

success=$?

mkdir -p tmt-run
cp -r /var/tmp/tmt/* tmt-run/ 2>/dev/null || true

for d in tmt-run/* ; do
    rm -rf "$d"/tests/plans/connect/tree
done

exit $success
