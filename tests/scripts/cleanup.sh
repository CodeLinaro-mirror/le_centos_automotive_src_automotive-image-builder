#!/usr/bin/bash

echo "Partial cleanup in $OUTDIR..."

rm -rf "$OUTDIR/run" || true
$SUDO rm -rf "$OUTDIR/build" || true
rm -rf "$OUTDIR/dnf-cache" || true

ctr_id=$(podman image ls --format "{{.ID}}" "localhost/aib-build" || true)
if [ -n "$ctr_id" ]; then
    echo "Removing bootc build container"
    podman image rm -f "$ctr_id"
fi

echo "Cleanup done."
