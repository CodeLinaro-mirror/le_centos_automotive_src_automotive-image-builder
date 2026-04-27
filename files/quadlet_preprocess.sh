#!/usr/bin/bash
ROOT="$1"
if [ -f $ROOT/usr/lib/systemd/system-generators/podman-system-generator ]; then
    echo "Pregenerating quadlets to /usr/lib/systemd/system"
    # Convert [] to {} to avoid the log parser complains about "[/run/..." not matching an open tag
    chroot $ROOT /usr/lib/systemd/system-generators/podman-system-generator \
           -no-kmsg-log -v /usr/lib/systemd/system 2>&1 | tr '[]' '{}'
fi
