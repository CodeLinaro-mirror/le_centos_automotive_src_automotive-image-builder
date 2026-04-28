#!/usr/bin/bash

# This scripts does some post-processing of the ostree tree and is run
# just before the org.osbuild.ostree.preptree stage. It fixes up some
# things that modern ostree/bootc expects but our rpm-ostree based
# preptree doesn't do.

ROOT="$1"
if [ -d $ROOT/usr/lib/sysimage/rpm ]; then
    mv $ROOT/usr/lib/sysimage/rpm $ROOT/usr/share/rpm
    ln -s ../../share/rpm $ROOT/usr/lib/sysimage/rpm
fi
mkdir -p $ROOT/usr/lib/rpm/macros.d
echo "%_dbpath /usr/share/rpm" > $ROOT/usr/lib/rpm/macros.d/macros.rpm-ostree
