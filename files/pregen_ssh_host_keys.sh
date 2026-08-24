#!/usr/bin/bash

# This script generates static ssh host keys embedded in the image, so
# that they don't have to be regenerated on each boot (with transient /etc).

ROOT="$1"

KEYGEN=/usr/libexec/openssh/sshd-keygen
if [ -x "$ROOT$KEYGEN" ]; then
    for type in rsa ecdsa ed25519; do
        chroot "$ROOT" "$KEYGEN" "$type"
    done
fi
