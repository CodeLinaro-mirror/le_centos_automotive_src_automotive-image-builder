#!/usr/bin/env bash
#
# Host-side wrapper that runs automotive-image-builder inside a container.
#
# It is meant to behave as if you were running `aib` directly on the host: all
# arguments are forwarded unchanged. When invoked through the aib-dev.sh symlink
# it runs `aib-dev` instead.
#
# This exact script is shipped inside the container image and printed when the
# image is run with no command, so you can install a matching launcher with:
#
#   podman run --rm quay.io/centos-sig-automotive/automotive-image-builder > aib
#   chmod +x aib
#
# The only wrapper-specific argument is:
#
#   --volume PATH   Also bind-mount PATH (at the same path) into the build
#                   container. The current working directory and the container
#                   image store are always mounted, which covers almost every
#                   use case; use --volume for inputs/outputs that live
#                   elsewhere, e.g. a --build-dir, --include, --out or
#                   --local-repo on another filesystem. May be repeated.
#                   (aib itself accepts and ignores --volume.)
#
# Configuration via environment variables:
#   AIB_IMAGE            Container image
#                        (default: quay.io/centos-sig-automotive/automotive-image-builder:latest)
#   AIB_PULL             podman --pull policy (default: newer; set empty to disable pulling)
#   AIB_BUILDDIR         Directory for osbuild intermediary files (default: ./_build).
#                        It is created if needed and bind-mounted into the container.
#   AIB_SRC_DIR          Host checkout of automotive-image-builder to run instead
#                        of the copy preinstalled in the image (for development)
#   AIB_PODMAN_OPTIONS   Extra options passed to `podman run` (word-split)
#
# Configuration files, read if present, providing DEFAULTS for the variables
# above. They contain simple KEY=VALUE lines (without the AIB_ key prefix)
#   ~/.config/aib.env    user-global config
#   ./aib.env            project-local config

set -eo pipefail

self="$(basename "$0")"

die() { echo "$self: $*" >&2; exit 1; }

# Portable realpath (macOS has no coreutils realpath by default).
abspath() {
    if [ -d "$1" ]; then
        (cd "$1" && pwd)
    else
        local d b
        d="$(cd "$(dirname "$1")" && pwd)"
        b="$(basename "$1")"
        case "$d" in
            */) printf '%s%s\n' "$d" "$b" ;;
            *)  printf '%s/%s\n' "$d" "$b" ;;
        esac
    fi
}

# Read KEY=VALUE lines from a config file (if it exists). Each KEY is
# prefixed with AIB_ before use. A variable is set only if it
# is not already set, so the environment and any earlier file win.
load_env_file() {
    local file="$1" line key val
    [ -r "$file" ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
        # Strip leading whitespace.
        line="${line#"${line%%[![:space:]]*}"}"
        case "$line" in
            ''|'#'*) continue ;;
            *=*) ;;
            *) continue ;;
        esac
        key="${line%%=*}"
        val="${line#*=}"
        # Trim trailing whitespace from the key and require a valid identifier.
        key="${key%"${key##*[![:space:]]}"}"
        case "$key" in
            [!A-Za-z_]*|*[!A-Za-z0-9_]*) continue ;;
        esac
        # Namespace the key so config files only ever touch AIB_* variables.
        key="AIB_$key"
        # Strip one layer of matching surrounding quotes from the value.
        case "$val" in
            \"*\") val="${val#\"}"; val="${val%\"}" ;;
            \'*\') val="${val#\'}"; val="${val%\'}" ;;
        esac
        # Only set if not already set ($key is a validated identifier, so eval is safe).
        if ! eval "[ -n \"\${$key+x}\" ]"; then
            printf -v "$key" '%s' "$val"
        fi
    done < "$file"
}

load_env_file "$PWD/aib.env"
load_env_file "$HOME/.config/aib.env"

DEFAULT_IMAGE="quay.io/centos-sig-automotive/automotive-image-builder:latest"
IMAGE="${AIB_IMAGE:-$DEFAULT_IMAGE}"
PULL="${AIB_PULL-newer}"

RUNTIME="$(command -v podman || command -v docker || true)"
[ -n "$RUNTIME" ] || die "podman or docker is required"
runtime_name="$(basename "$RUNTIME")"

if [ -n "${container:-}" ] || [ -f /.dockerenv ] || [ -f /run/.containerenv ]; then
    die "this wrapper must not be run from within a container"
fi

# docker uses a different --pull vocabulary than podman.
if [ "$runtime_name" = "docker" ] && [ "$PULL" = "newer" ]; then
    PULL="missing"
fi

# Bind mounts, de-duplicated by container target path so we never pass the same
# mount twice (e.g. a --volume that coincides with cwd or the build dir).
VOLUMES=()
MOUNT_TARGETS=()
add_mount() {
    # add_mount HOST [TARGET] [OPTS]
    #   TARGET defaults to HOST (a same-path mount); OPTS are extra -v options
    #   (e.g. "exec"), appended as HOST:TARGET:OPTS.
    local host="$1" target="${2:-$1}" opts="${3:-}" t spec
    for t in "${MOUNT_TARGETS[@]}"; do
        [ "$t" = "$target" ] && return 0
    done
    MOUNT_TARGETS+=("$target")
    spec="$host:$target"
    [ -n "$opts" ] && spec="$spec:$opts"
    VOLUMES+=(-v "$spec")
}

add_mount_for() {
    # Mount the parent directory of FILE at the same path, so a host file (e.g. a
    # config pointed at by an env var) is reachable inside the container. Mirrors
    # Python's Runner.add_volume_for.
    add_mount "$(dirname "$(abspath "$1")")"
}

add_mount /dev
add_mount "$PWD"

# Bind-mount the host image store so built images land in the user's real store.
if [ "$runtime_name" = "podman" ]; then
    STORE="$("$RUNTIME" info --format '{{.Store.GraphRoot}}')"
    [ -n "$STORE" ] && add_mount "$STORE" /var/lib/containers/storage
fi

ENTRYPOINT_DIR=/usr/libexec
ENTRYPOINT_ARGS=()
if [ -n "${AIB_SRC_DIR:-}" ]; then
    src="$(abspath "$AIB_SRC_DIR")"
    [ -x "$src/bin/aib" ] || die "AIB_SRC_DIR=$src does not look like an aib checkout"
    # exec: the entrypoint execs bin/aib from this mount; podman mounts volumes
    # noexec by default. (docker's -v has no such option.)
    srcopts=""
    [ "$runtime_name" = "podman" ] && srcopts="exec"
    add_mount "$src" /run/aib-src "$srcopts"
    ENTRYPOINT_ARGS=(--src /run/aib-src)
fi

case "$self" in
    *-dev*) ENTRYPOINT_NAME=aib-dev-entrypoint ;;
    *)      ENTRYPOINT_NAME=aib-entrypoint ;;
esac
ENTRYPOINT="$ENTRYPOINT_DIR/$ENTRYPOINT_NAME"

# Scan only for our own --volume flag; everything else is forwarded to aib untouched.
args=("$@")
n=${#args[@]}
for ((i=0; i<n; i++)); do
    case "${args[i]}" in
        --volume=*)
            add_mount "$(abspath "${args[i]#--volume=}")"
            ;;
        --volume)
            j=$((i+1))
            if [ "$j" -lt "$n" ]; then
                add_mount "$(abspath "${args[j]}")"
            fi
            ;;
    esac
done

# Forward host container/registry configuration and files so private registries and
# custom container config reach the build. 
ENVS=()
for e in REGISTRY_AUTH_FILE CONTAINERS_CONF CONTAINERS_REGISTRIES_CONF CONTAINERS_STORAGE_CONF; do
    val="${!e:-}"
    [ -n "$val" ] || continue
    # Pass NAME=VALUE (not just NAME) so it works whether or not the variable is
    # exported (config files set plain shell variables).
    ENVS+=(--env "$e=$val")
    [ -e "$val" ] && add_mount_for "$val"
done

if [ -n "${AIB_BUILDDIR:-}" ]; then
    # Explicit build dir: make sure it exists and bind-mount it at the same path.
    mkdir -p "$AIB_BUILDDIR"
    BUILDDIR="$(abspath "$AIB_BUILDDIR")"
    add_mount "$BUILDDIR"
else
    BUILDDIR="$PWD/_build"

    # macOS / podman-machine: the container sees the VM, not the host. cwd is
    # shared through the machine's home mount, but the build-dir must live on the
    # VM's own filesystem.
    if [ "$(uname -s)" = "Darwin" ] || \
       [ "$(cat /sys/devices/virtual/dmi/id/product_name 2>/dev/null || true)" = "Apple Virtualization Generic Platform" ]; then
        add_mount /root
        BUILDDIR=/root/aib-work
    fi
fi
ENVS+=(--env "OSBUILD_BUILDDIR=$BUILDDIR")

# Allocate a TTY only when we have one on both ends, so progress bars work
# interactively without breaking piped/captured output.
TTY=()
if [ -t 0 ] && [ -t 1 ]; then
    TTY=(-ti)
fi

# shellcheck disable=SC2086 # AIB_PODMAN_OPTIONS is intentionally word-split
exec "$RUNTIME" run --rm \
    --privileged \
    --cap-add=MAC_ADMIN \
    --security-opt label=type:unconfined_t \
    --read-only=true \
    --workdir "$PWD" \
    "${TTY[@]}" \
    "${VOLUMES[@]}" \
    "${ENVS[@]}" \
    ${PULL:+--pull="$PULL"} \
    ${AIB_PODMAN_OPTIONS:-} \
    "$IMAGE" \
    "$ENTRYPOINT" "${ENTRYPOINT_ARGS[@]}" "$@"
