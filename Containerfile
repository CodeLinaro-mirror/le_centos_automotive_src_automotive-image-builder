FROM quay.io/centos/centos:stream10 AS base

RUN dnf update -y && \
    dnf install -y 'dnf-command(config-manager)' 'dnf-command(copr)' && \
    dnf clean all

# TODO: If newer osbuild version than the one available in CS10 is required, osbuild-stable COPR needs to be enabled
#       (osbuild-copr repo needs to provide relevant EPEL10 build)
#RUN dnf copr enable -y @osbuild/osbuild-stable

RUN dnf copr enable -y @centos-automotive-sig/osbuild-auto && \
    rpm --import https://www.centos.org/keys/RPM-GPG-KEY-CentOS-SIG-Automotive && \
    dnf config-manager --add-repo 'https://mirror.stream.centos.org/SIGs/10-stream/autosd/$basearch/packages-main'


FROM base as builder

ARG MAKE_WHAT="rpm_dev"

COPY --exclude=_build --exclude=*.qcow2 --exclude=*.img . /build
RUN  dnf install -y git rpm-build make && \
     cd /build && make "$MAKE_WHAT"

FROM base as runtime

VOLUME /var/tmp
VOLUME /var/log
LABEL name="Automotive Image Builder" \
      usage="This image can be used with rootful privileged containers, https://gitlab.com/CentOS/automotive/src/automotive-image-builder/" \
      summary="Base image for composing Red Hat In-Vehicle Operating System or CentOS Automotive Stream Distribution images"

COPY --from=builder /build/automotive-image-builder-*.noarch.rpm .

# Fix /dev/shm for bootc install-to-filesystem, can be removed once
# https://github.com/osbuild/osbuild/pull/2494 is in the osbuild package
COPY contrib/osbuild-bootc-fix.patch /tmp/osbuild-bootc-fix.patch

RUN dnf install -y qemu-kvm-core virtiofsd qemu-img patch && \
    dnf localinstall -y automotive-image-builder-*.noarch.rpm && \
    dnf clean all && \
    cd /usr/lib/osbuild && \
    patch -p1 --forward -r /dev/null < /tmp/osbuild-bootc-fix.patch || true && \
    rm /tmp/osbuild-bootc-fix.patch
