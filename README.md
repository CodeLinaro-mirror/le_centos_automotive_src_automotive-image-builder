# Automotive Image Builder

Automotive Image Builder (AIB) is a tool to create various kinds of OS images based on CentOS-derived
distributions. The main tool produces immutable atomically updatable images based on bootc, but there
is also a tool that allows building mutable package-based disk images for development and testing
purposes.

The main tool is called `aib`, and its primary function is to build bootc container images from
manifests, given some highlevel options like what hardware board to target, and what distribution to
use.

Example of how to build a 'bootc' container image:

```shell
 $ aib build --target qemu my-image.aib.yml localhost/my-image:latest
```

And then to build a disk image from it:

```shell
 $ aib to-disk-image localhost/my-image:latest my-image.qcow2
```

You can then run the QCOW2 image in a virtual machine like this:

```shell
 $ air  my-image.qcow2
```

For a hardware based target you would instead flash the disk image to the board and boot it.

Alternatively you can build the bootc container as well as the disk image in one command:

```shell
 $ aib build --target qemu my-image.aib.yml localhost/my-image:latest my-image.qcow2
```

However, creating the disk image is not always needed. Once the system is running it can update directly
from the bootc container using the `bootc switch` and `bootc update` commands. This is much faster than
re-flashing.

Note: When you run `aib build`, it is helpful and time-saving to pass the option `--build-dir some/dir`,
which stores in this directory intermediate data, such as downloaded RPMs, between runs.

## Installation and dependencies

Automotive Image Builder depends on osbuild extensions for automotive use.

To install Automotive Image Builder, refer to the
[AutoSD documentation](https://sigs.centos.org/automotive/getting-started/proc_installing-automotive-image-builder/)

Alternatively, you can also run Automotive Image Builder from
[a container](https://sigs.centos.org/automotive/getting-started/proc_running-automotive-image-builder-from-container/).

## Manifests

Automotive Image Builder manifests have the extension `.aib.yml` and is a high-level,
declarative YAML-based format, for example:
```yaml
name: image-with-vim

content:
  rpms:
    - vim
```

You can find detailed
[schema documentation for the manifest syntax](https://centos.gitlab.io/automotive/src/automotive-image-builder/simple_manifest.html).

You can also experiment with the example manifests in the [examples](examples) directory:

```shell
$ aib build examples/simple.aib.yml example:latest example.qcow2
$ air example.qcow2
```

The sample-images repository
(https://gitlab.com/CentOS/automotive/sample-images) has a larger set
of functional examples.

## Controlling the image built

When building a manifest, there are some core options that control what gets built:

* `--arch`: The hardware architecture to build for (`x86_64` or `aarch64`). If not specified the native
   architecture is used. Note: You can only build an image on the native architecture, but some operations
   like e.g. `list-rpms` work on non-native architectures.

* `--target`: The board to target, defaults to `qemu`. You can get a list of the supported targets from
  `aib list-targets`.

* `--distro`: There are a set of distribution definitions that can be used. These define which package
  repositories to use. The default is "autosd10-sig", but the full list can be obtained with
  `aib list-dist`.  It is also possible to extend the list of distributions
  with your custom ones by placing them in a directory called "/some/dir/distro" and passing
  `--include /some/dir` on the command line.

## Policy System

Automotive Image Builder supports a policy system that allows external policy files to enforce build restrictions and configurations. This replaces hard-coded flags with flexible, external policy definitions.

### Using Policies

Use the `--policy` flag to apply a policy file. The policy argument can be:

- **Policy name**: `--policy security` (searches installed locations only)
- **Policy filename**: `--policy my-policy.aibp.yml` (searches local directory first, then installed)
- **Full path**: `--policy /path/to/policy.aibp.yml`

Installed policy locations (searched in order):
1. `/etc/automotive-image-builder/policies/` (system-wide)
2. `/usr/lib/automotive-image-builder/files/policies/` (package-provided)

```shell
$ aib build --policy security my-image.aib.yml example:latest
```

Policy files use the `.aibp.yml` extension and define restrictions and forced configurations:

```yaml
name: security-policy
description: Security hardening policy for production images

restrictions:
  modes:
    allow:
      - image

  variables:
    force:
      disable_ipv6: true
      ld_so_cache_protected: true

  rpms:
    disallow:
      - dosfstools
      - e2fsprogs

  sysctl:
    force:
      "net.core.busy_poll": "0"
      "net.ipv4.conf.all.mc_forwarding": "0"
```

### Policy Features

Policies can enforce:

- **Target restrictions**: Control which hardware targets are allowed
- **Distribution restrictions**: Limit which distributions can be used
- **Variable enforcement**: Force specific manifest variables
- **Package restrictions**: Block specific RPMs from being installed
- **Kernel module restrictions**: Prevent loading of specific kernel modules
- **Sysctl enforcement**: Set required kernel parameters
- **SELinux boolean enforcement**: Configure SELinux policy settings
- **Manifest validation**: Block specific manifest properties or values

Policy validation happens early in the build process, providing clear error messages when restrictions are violated.

The complete policy file schema is defined in [files/policy_schema.yml](files/policy_schema.yml).

## Manifest variables

Internally, the various options in the manifests are automatically converted to internal
variables in the osbuild templates that are used to build the image. These variables
can also be set directly on the commandline or in the manifest (although such variables
don't have the same stability guarantees as the regular manifest options).
To set these variables on the command line, you can use:

* `--define VAR=VALUE`: Sets the variable to the specified value (YAML format).

* `--define-file PATH`: Loads variables from a YAML dict in a file, where the keys are variable names.

* `--extend-define VAR=VALUE`: Similar to `--define`, but only usable for list-based variables.
  It extends the existing list (or starts a new one if unset). You can specify
  either a list or a single item.

Commonly used supported variables include:

* `extra_rpms`: Adds extra RPMs to the image (supported by any manifests, e.g., in sample-images).
* `image_size`: Specifies the size (in bytes, as a string) of the generated image.
* `use_transient_etc`: If false, changes to `/etc` persist across boots in bootc images. Not recommended for production but useful for testing.
* `use_debug`: If true, enables detailed debugging output during boot.

## Reproducible builds

By default each build gets a random UUID and the current time in `/etc/build-info`,
so two builds from the same manifest differ. Enable reproducible mode to fix that:

```shell
$ aib build --reproducible my-image.aib.yml example:latest
```

In this mode the UUID is derived deterministically from a hash of the manifest
and the build parameters (arch, distro, target, defines, local repo, ostree refs).
Note that it identifies the *build configuration*, not the image content — if the
package repos change you get the same UUID but a different image.

The `TIMESTAMP` field in `/etc/build-info` (format: `%Y-%m-%d %H:%M:%S UTC`) is
set from the first available source:

1. An explicit `timestamp` variable (`--define timestamp=...`).
2. [`SOURCE_DATE_EPOCH`](https://reproducible-builds.org/docs/source-date-epoch/)
   — honored even without reproducible mode.
3. The newest buildtime of the resolved RPM packages (build container excluded).
4. The manifest file's mtime, falling back to the Unix epoch.

Since osbuild is deterministic for a given manifest, two runs that produce the
same manifest will produce identical images. Use `--dry-run --osbuild-manifest PATH`
to export and compare the manifest without building.

## Using QM

Automotive Image Builder supports the [QM](https://github.com/containers/qm/tree/main) package for
isolating quality-managed code in a separate partition. When you enable QM, OSBuild builds two pipelines -
one for the regular filesystem, and one for the QM partition. In the final image, the QM root
filesystem is accessible in `/usr/share/qm/rootfs`.

Example manifest:

```yaml
name: qm-example
content:
  rpms:
    - curl
qm:
  content:
    rpms:
      - httpd
    systemd:
      enabled_services:
        - httpd.service
```

## Embedding containers in images

You can embed container images in the operating system image. These container images are automatically
available to podman in the running system. For example, use the following manifest to
pull the CentOS Stream 9 container image into the operating system:

```yaml
name: embed-container
content:
  rpms:
    - podman
  container_images:
    - source: quay.io/centos/centos
      tag: stream9
```

You can then configure these containers to run automatically in the system by using a
[quadlet.container](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html) file
to start the container from systemd. You can view an example configuration in the
[examples/container.aib.yml](examples/container.aib.yml) file.

## Requesting new AIB manifest options

You can request support for additional AIB options by opening an issue in `the automotive-image-builder` repository:

1. Create an issue to request a new option.
1. Share a link to the issue in the `#automotive-image-builder` Slack channel.
1. Solicit feedback from the AIB team on the legitimacy and prioritization of the request. If accepted, the AIB team
   will triage, prioritize, and complete the work.
1. Track the issue to its resolution and close the ticket when a solution is implemented.
