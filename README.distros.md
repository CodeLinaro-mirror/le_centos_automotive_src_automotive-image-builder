# Automotive Image Builder – distro

When you build an image, a distro option is specified. This selects
what distribution version is used and affects what package
repositories are used, and various other version related options.

There are two "main" families of distros: "autosd" and
"rhivos".

## AutoSD distros

AutoSD is an upstream, community supported version, based on centos
stream. Being based on centos stream means there are no individual
minor versions, just one stream of changes.

There are several different repositories used for AutoSD:

 * CentOS stream - The upstream centos base repository with the
   absolutely latest version
 * Automotive - Contains supported automotive specific packages on top
   of centos
 * Nightly compose - Each night the CentOS stream and the automotive
   repos are composed into one repository and tested. Only composes
   that pass testing are published.
 * automotive sig repo - Contains some extra packages like raspberry
   pi support. and tools for test and development.

These are used to define these distros:

 * autosd - Symlink to the latest version (currently autosd10)
 * autosd10 - Latest nightly validated AutoSD snapshot based on CentOS
   10
 * autosd10-sig - Same as autosd10, but with the automotive sig repo
   added
 * autosd10-latest-sig - Uses centos and automotive repos, which can
   contain newer packages than the nightly compose (autosd10), but is
   not as tested.

## RHIVOS distros:

These are distros for the downstream RHIVOS product, and as such they
are only useful if you have the RHIVOS product packages, which are
available separately.

RHIVOS is based on RHEL, not CentOS stream, so it has stable version
streams like 10.0, 10.1, etc.

Here are the available distros:

 * rhivos-2 - Latest RHIVOS 2.x release
 * rhivos-2.0 - RHIVOS 2.0 release
 * rhivos-core-2 - Latest RHIVOS Core 2.x release
 * rhivos-core-2.0 - RHIVOS Core 2.0 release

## Other distros

There are also some other, less supported distros that are sometimes
useful for testing and development:

* f43 - Fedora 43. Uses the regular fedora kernel.
* eln - Fedora ELN based version. This is based on the very latest Fedora development snapshot.
