#!/usr/bin/bash

source "$(dirname ${BASH_SOURCE[0]})"/setup-lib.sh

# Path where local a-i-b repository will be create
AIB_LOCAL_REPO=/var/tmp/aib-local-repo

if [ "${BUILD_AIB_RPM}" != "yes" ]; then
    echo "Building a-i-b package not requested, skipping ..."
    exit 0
fi

if [ ! -d "${AIB_SRPM_DIR}" ]; then
    echo "Directory '${AIB_SRPM_DIR}' does not exist"
    exit 1
fi

if [[ $(ls -1q ${AIB_SRPM_DIR}/*.src.rpm 2> /dev/null | wc -l) -lt 1 ]]; then
    echo "Directory '${AIB_SRPM_DIR}' does not contain any source RPM packages"
    exit 2
fi

# Clean local repository path
if [ -d ${AIB_LOCAL_REPO} ]; then
    rm -rf ${AIB_LOCAL_REPO}
fi
mkdir -p ${AIB_LOCAL_REPO}

# Install required packages for RPM builds
dnf install -y \
    createrepo_c \
    rpm-build

# Rebuild existing SRPMs
for srpm in ${AIB_SRPM_DIR}/*.src.rpm ; do
    dnf builddep -y ${srpm}
    rpmbuild --rebuild --define "_rpmdir $AIB_LOCAL_REPO" ${srpm}
done

# Create repositoru for built RPMs
createrepo_c ${AIB_LOCAL_REPO}


# TODO: Once switching to CS10 we can create repo file using dnf config-manager
add_repo "aib-local-repo" "file://${AIB_LOCAL_REPO}"

# TODO: Remove following issue is fixed: https://gitlab.com/CentOS/automotive/src/automotive-image-builder/-/issues/35
echo "excludepkgs=automotive-image-builder" >> /etc/yum.repos.d/aib-base-repo.repo
