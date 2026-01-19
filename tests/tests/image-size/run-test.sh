#!/usr/bin/bash -x

source "$(dirname ${BASH_SOURCE[0]})"/../../scripts/test-lib.sh

IMAGE_NAME="test-image.qcow2"

# Update cleanup function parameters on each test artifact change
trap 'cleanup_path "$IMAGE_NAME"' 'EXIT'

for YML_NAME in image-size-*.aib.yml; do
    # Extract image_size value
    IMAGE_SIZE=$(grep -E "^[[:space:]]*image_size:" "$YML_NAME" | awk -F': *' '{ print $2 }' | tr -d '"')

    # Parse image_size and expected size in bytes based on unit
    UNIT=$(echo "$IMAGE_SIZE" | grep -oEi '(GiB|MB)$')
    NUM=$(echo "$IMAGE_SIZE" | sed 's/[^0-9]//g')

    case "$UNIT" in
      GiB) MULT=1073741824 ;;
      MB)  MULT=1000000 ;;
      *)   echo_fail "Unsupported unit in $IMAGE_SIZE"; exit 1 ;;
    esac

    EXPECTED_BYTES=$((NUM * MULT))

    # Build image
    echo_log "Building image: $YML_NAME"
    build \
        "$YML_NAME" \
        "$NO_CTR_NAME" \
        "$IMAGE_NAME" || {
        echo_fail "Build failed for $YML_NAME"
        exit 1
    }

    # Compare actual vs expected image size
    ACTUAL_BYTES=$(qemu-img info --output=json "$IMAGE_NAME" | jq '.["virtual-size"]')

    # bootc image sizes requires bigger tolerance
    # TOLERANCE=4096
    TOLERANCE=65536

    DELTA=$(( ACTUAL_BYTES - EXPECTED_BYTES ))
    ABS_DELTA=${DELTA#-}  # absolute value

    echo_log "Testing image: $YML_NAME"
    if [ "$ABS_DELTA" -le "$TOLERANCE" ]; then
        echo_pass "$YML_NAME matched ($IMAGE_SIZE)"
    else
        echo_fail "$YML_NAME mismatched. Got $ACTUAL_BYTES, expected $EXPECTED_BYTES"
        exit 1
    fi
done

