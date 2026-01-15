#!/usr/bin/bash -x

source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/test-lib.sh"

IMG_NAME="test.img"
YML_NAME="custom-kernel.aib.yml"
STREAM_NUMBER=""

if [[ -f /etc/os-release ]]; then
    . /etc/os-release  # this loads variables like VERSION_ID
    case "$VERSION_ID" in
        10*) STREAM_NUMBER=10 ;;
        9*)  STREAM_NUMBER=9  ;;
        *)  echo_fail "Unsupported version: $VERSION_ID"; exit 1 ;;
    esac
fi

ARCH=$(uname -m)

echo_log "Installing required packages..."
dnf install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-$STREAM_NUMBER.noarch.rpm

# Enable CRB repository
if command -v crb >/dev/null 2>&1; then
    crb enable
else
    dnf config-manager --set-enabled crb 2>/dev/null || echo_log "CRB repository not available, continuing..."
fi

dnf -y update \
 && dnf -y groupinstall "Development Tools" \
 && dnf -y install ncurses-devel bison flex elfutils-libelf-devel openssl-devel dwarves createrepo osbuild mock

# Configure YAML with kernel package
sed -i "s|^\(\s*kernel_package:\).*|\1 kernel-automotive|" "$YML_NAME"

# Setup mock build environment
if getent group mock >/dev/null; then
    usermod -aG mock "${USER:-$(whoami)}" || \
        echo_log "Warning: could not add user to mock group"
fi

mkdir -p /etc/mock
MOCK_CONFIG="/etc/mock/centos-stream+epel-${STREAM_NUMBER}-${ARCH}.cfg"
if [[ -f "$MOCK_CONFIG" ]]; then
    ln -sf "$MOCK_CONFIG" /etc/mock/default.cfg
fi

echo_log "Building custom kernel..."

# Set kernel repository parameters based on stream version
if [[ "$STREAM_NUMBER" -eq 10 ]]; then
    KERNEL_REPO="centos-stream-10"
    KERNEL_BRANCH="main"
    KERNEL_BUILD_ARGS="DISTLOCALVERSION=_custom AUTOMOTIVE_BUILD=1 dist-srpm"
else
    KERNEL_REPO="centos-stream-9"
    KERNEL_BRANCH="main-automotive"
    KERNEL_BUILD_ARGS="DISTLOCALVERSION=_custom dist-srpm"
fi

KERNEL_REPO_URL="https://gitlab.com/redhat/centos-stream/src/kernel/${KERNEL_REPO}.git"

# Clone kernel source
git clone --depth 1 --branch "$KERNEL_BRANCH" "$KERNEL_REPO_URL"
pushd "$KERNEL_REPO" || exit 1

# Build kernel SRPM
make -j"$(nproc)" $KERNEL_BUILD_ARGS

# Locate built SRPM
SRPM_FILE=$(find redhat/rpm/SRPMS/ -name "kernel-*.src.rpm" | head -1)
if [[ ! -f "$SRPM_FILE" ]]; then
    echo_fail "Error: SRPM not found!"
    exit 1
fi

# Extract kernel version from SRPM
KERNEL_VERSION=$(rpm -qp --queryformat '%{VERSION}-%{RELEASE}' "$SRPM_FILE" | sed 's/\.[^.]*$//')
EXPECTED_KERNEL_VERSION="${KERNEL_VERSION}"

# Build kernel RPMs using mock
DIST_TAG=".el${STREAM_NUMBER}iv"
MOCK_RESULT_DIR="/var/lib/mock/centos-stream+epel-${STREAM_NUMBER}-${ARCH}/result"
mock --define "dist $DIST_TAG" --resultdir "$MOCK_RESULT_DIR" "$SRPM_FILE"

popd || exit

# Update kernel version in YAML
sed -i "s|^\(\s*kernel_version:\).*|\1 ${EXPECTED_KERNEL_VERSION}.el${STREAM_NUMBER}iv|" "$YML_NAME"

# Create local repository
REPO_DIR="$(pwd)/my_repo"
MOCK_RESULT_DIR="/var/lib/mock/centos-stream+epel-${STREAM_NUMBER}-${ARCH}/result"

mkdir -p "$REPO_DIR"
cp -rp "${MOCK_RESULT_DIR}/." "$REPO_DIR/"
createrepo "$REPO_DIR"

# Update YAML configuration with repository path
sed -i "s|^\(\s*baseurl:\).*|\1 file://${REPO_DIR}|" "$YML_NAME"

# Build AIB image
echo_log "Building AIB image..."
build --target qemu "$YML_NAME" "$NO_CTR_NAME" "$IMG_NAME"

# Check if image was created
assert_image_exists "$IMG_NAME"

# Start the VM using the built AIB image
VM_PID=$(run_vm "$IMG_NAME")

# Wait until VM becomes available or fail fast
PASSWORD="password"
LOGIN_TIMEOUT=40
if ! wait_for_vm_up "$LOGIN_TIMEOUT" "$PASSWORD"; then
    stop_vm "$VM_PID"
    exit 1
fi

# Check kernel version in VM
echo_log "Checking kernel version in VM..."
VM_KERNEL_VERSION=$(run_vm_command "uname -r")

# Verify it matches our expected kernel version
if [[ "$VM_KERNEL_VERSION" == *"$EXPECTED_KERNEL_VERSION"* ]]; then
    echo_pass "Expected kernel version $EXPECTED_KERNEL_VERSION detected in VM!"
    success=0
else
    echo_fail "Expected kernel version $EXPECTED_KERNEL_VERSION, but got: $VM_KERNEL_VERSION"
    success=1
fi

# Clean up air process
stop_vm "$VM_PID"

exit $success
