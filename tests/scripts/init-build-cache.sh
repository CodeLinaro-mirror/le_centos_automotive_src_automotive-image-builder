#!/usr/bin/bash

source "$(dirname ${BASH_SOURCE[0]})"/test-lib.sh

if [ -d "$BUILDDIR" ]; then
    echo "Build cache directory '$BUILDDIR' already exists, skipping"
    exit 0
fi

MIN_IMAGE_MFT="/tmp/minimal-image.aib.yml"
cat > "$MIN_IMAGE_MFT" << EOF
name: minimal-boot

content:
  rpms: []

qm:
  content:
    rpms: []
EOF

echo "Populating build directory '$BUILDDIR' started"
$AIB download \
    --distro="$(get_aib_distro)" \
    --cache $OUTDIR/dnf-cache \
    --build-dir $BUILDDIR \
    "$MIN_IMAGE_MFT"

rm -f "$MIN_IMAGE_MFT"

echo "Populating build directory '$BUILDDIR' finished"
