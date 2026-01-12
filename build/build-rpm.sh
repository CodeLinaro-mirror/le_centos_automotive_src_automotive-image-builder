#!/bin/bash
set -e

PACKAGE_NAME="automotive-image-builder"
SPEC=$(realpath $PACKAGE_NAME.spec.in)
POSITIONAL_ARGS=()
GENERATE_SPEC=false
BUILD_SOURCE=false
BUILD_BINARY=false
DEV_RELEASE=true
PRINT_SOURCE_PATH=false
DEV_RELEASE_SUFFIX=""
SOURCE_FILENAME=""
OUTPUT_DIR=$(pwd)

usage() {
  echo "Usage: build-rpm.sh [--generate-spec|--build-source|--build-binary] [--release] [--print-source-path] [output_dir]"
}

while [[ $# -gt 0 ]]; do
  case $1 in
    -gs|--generate-spec)
      GENERATE_SPEC=true
      shift
      ;;
    -bs|--build-source)
      GENERATE_SPEC=true
      BUILD_SOURCE=true
      shift
      ;;
    -bb|--build-binary)
      GENERATE_SPEC=true
      BUILD_SOURCE=true
      BUILD_BINARY=true
      shift
      ;;
    -psp|--print-source-path)
      PRINT_SOURCE_PATH=true
      shift
      ;;
    --release)
      DEV_RELEASE=false
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "Unknown option $1"
      exit 1
      ;;
    *)
      POSITIONAL_ARGS+=("$1") # save positional arg
      shift # past argument
      ;;
  esac
done

# Store OUTPUT_DIR variable from positional arg
if [ ${#POSITIONAL_ARGS[@]} -ge 1 ]
then
  OUTPUT_DIR=${POSITIONAL_ARGS[0]}
  # Create directory if it doesn't exist
  if [ ! -d "$OUTPUT_DIR" ]
  then
    mkdir -p "$OUTPUT_DIR"
  fi
fi

if [ $GENERATE_SPEC = false ] && [ $BUILD_SOURCE = false ]
then
  echo "No action specified"
  usage
  exit 1
fi

if [ -z "$PACKAGE_VERSION" ] && [ -f ./aib/version.py ]
then
  PACKAGE_VERSION=$(python3 ./aib/version.py)
fi
PACKAGE_RELEASE=1
if [ $DEV_RELEASE = true ]
then
  DEV_RELEASE_SUFFIX=".$(date +%04Y%02m%02d%02H%02M).git$(git rev-parse --short HEAD)"
  PACKAGE_RELEASE="0$DEV_RELEASE_SUFFIX"
fi

if [ $GENERATE_SPEC = true ]
then
  rm -rf .rpmbuild
  mkdir -p .rpmbuild/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}

  # Copy spec file to the SPECS directory
  cp "$SPEC" .rpmbuild/SPECS/$PACKAGE_NAME.spec

  # Set package version and release to the spec file
  sed -e "s/@@VERSION@@/$PACKAGE_VERSION/g" -i .rpmbuild/SPECS/$PACKAGE_NAME.spec
  sed -e "s/@@RELEASE@@/$PACKAGE_RELEASE/g" -i .rpmbuild/SPECS/$PACKAGE_NAME.spec
  sed -e "s/.tar.gz/$DEV_RELEASE_SUFFIX.tar.gz/g" -i .rpmbuild/SPECS/$PACKAGE_NAME.spec
fi

if [ $BUILD_SOURCE = true ]
then
  make generate-manifest-doc
  SOURCE_FILENAME="$PACKAGE_NAME-$PACKAGE_VERSION$DEV_RELEASE_SUFFIX.tar.gz"
  cp -f .rpmbuild/SPECS/$PACKAGE_NAME.spec .
  git archive \
    -o ".rpmbuild/SOURCES/$SOURCE_FILENAME" \
    --prefix="$PACKAGE_NAME-$PACKAGE_VERSION/docs/" \
    --add-file docs/manifest.html \
    --add-file docs/manifest.md \
    --prefix="$PACKAGE_NAME-$PACKAGE_VERSION/" \
    --add-file $PACKAGE_NAME.spec \
    HEAD
  rm $PACKAGE_NAME.spec
fi

if [ $BUILD_BINARY = true ]
then
  rpmbuild --define "_topdir $(pwd)/.rpmbuild" -ba .rpmbuild/SPECS/$PACKAGE_NAME.spec
elif [ $BUILD_SOURCE = true ] && [ $BUILD_BINARY = false ]; then
  rpmbuild --define "_topdir $(pwd)/.rpmbuild" -bs .rpmbuild/SPECS/$PACKAGE_NAME.spec
fi

#Copy spec file to the output_dir
cp -f .rpmbuild/SPECS/$PACKAGE_NAME.spec "$OUTPUT_DIR"

#Copy rpm packages to the output_dir
find .rpmbuild -name "*.rpm" -exec cp {} "$OUTPUT_DIR" \;

#Copy tar file to the output_dir
find .rpmbuild -name "*.tar.gz" -exec cp {} "$OUTPUT_DIR" \;
if [ $PRINT_SOURCE_PATH = true ]
then
  echo "$OUTPUT_DIR/$SOURCE_FILENAME"
fi

# Clean .rpmbuild directory
rm -fr .rpmbuild
