#!/usr/bin/bash

# This runs the bootc-system-generator at build-time, allowing the generator
# to be masked at runtime for faster booting.

# The generator mainly creates some multi-user.target wants.d files to ensure
# that the bootc-related tasks are running. It can also modify /etc/fstab,
# and check for /sysroot/etc/destructive-cleanup, but we use neither of these.

ROOT="$1"
if [ -f $ROOT/usr/lib/systemd/system-generators/bootc-systemd-generator ]; then
    echo "Pregenerating bootc generator to /usr/lib/systemd/system"
    # We need to set up the environmen to look like an ostre booted system:
    touch /run/ostree-booted
    mkdir $ROOT/sysroot
    bwrap --bind $ROOT / --bind /run /run --proc /proc \
          /usr/lib/systemd/system-generators/bootc-systemd-generator /usr/lib/systemd/system
fi
