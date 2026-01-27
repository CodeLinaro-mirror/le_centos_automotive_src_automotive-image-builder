<!-- markdownlint-disable-file MD013 -->

# Automotive Image Builder integration tests

This document describes how to run integration tests for Automotive Image Builder (AIB).

## Prerequisites

### Installing packages using RPM (Fedora / CentOS Stream)

Automotive Image Builder relies on the [tmt](https://tmt.readthedocs.io/en/stable/) framework to manage and run integration tests.

#### Testing infrastructure

Required for managing and executing tests:

```shell
dnf install \
    tmt-all \
    -y
```

#### VM provisioning (optional)

Required only if you plan to create and manage test VMs locally:

```shell
dnf install \
    virt-install \
    -y
```

#### Automotive Image Builder dependencies

Required for running automotive-image-builder:

```shell
dnf install \
    android-tools \
    osbuild \
    osbuild-auto \
    osbuild-luks2 \
    osbuild-lvm2 \
    osbuild-ostree \
    ostree \
    python3-jsonschema \
    python3-pyyaml \
    -y
```

#### Local machine testing

Required only for running tests directly on your local machine (not on a VM):

```shell
dnf install \
    git-gui \
    -y
```

## Running integration tests

There are two main approaches to running integration tests:

- **Local machine**: You run `tmt` directly on your machine and it executes each test on this same machine.
- **Manually provisioned machine**: You run `tmt` directly on your machine and it connects to a remote machine (physical or VM) using SSH and runs the tests there.

### Using local machine

All **automotive-image-builder** dependencies and **tmt** infrastructure must be installed on your local machine to use this testing method.

To run integration tests, please execute the following command in the [tests](./) directory:

```shell
tmt -c arch=$(arch) --feeling-safe run -v plan --name local
```

#### Running tests requiring sudo privileges
Some integration tests also require sudo permissions.
There are two ways to provide these permissions in a non-interactive environment:
1. Using SUDO_ASKPASS
You can use the SUDO_ASKPASS environment variable to provide a script that returns your sudo password.

```shell
cd tests
SUDO_ASKPASS=/usr/libexec/git-core/git-gui--askpass tmt -c arch=$(arch) --feeling-safe run -v \
    -ePROJECT_DIR="Absolute path to your repository clone" plan --name local
```

2. Allow passwordless sudo for Specific Commands
You can configure sudo to run specific commands without asking for a password.
See the Fedora guide for setup:
https://docs.fedoraproject.org/en-US/quick-docs/performing-administration-tasks-using-sudo/


### Using manually provisioned machine

**Prerequisites**
- IP or a hostname of the machine needs to be known
- SSH key authentication must be set up to access this machine

Run the following commands to initiate integration testing:

```shell
cd tests
tmt -c arch=$(arch) run -v -eNODE="IP or hostname" plan --name connect
```

### Using manually provisioned machine with custom AIB package

To use a custom AIB package, upload the source RPM to the testing machine before running tests:

```shell
make srpm
scp -i ~/.ssh/aib-tests automotive-image-builder*.src.rpm root@"IP or hostname":/var/tmp/aib-srpm
```

Run the following commands to initiate integration testing:

```shell
cd tests
tmt -c arch=$(arch) run -v -eNODE="IP or hostname" -eBUILD_AIB_RPM=yes plan --name connect
```

### Running special tests

We have some tests marked with `special` tag, such as
[custom-kernel](https://gitlab.com/CentOS/automotive/src/automotive-image-builder/-/tree/main/tests/tests/custom-kernel?ref_type=heads),
which are not run as a part of `connect` or `local` plan execution.
To run those tests, provide additional parameters on the command line to bypass the default test filter and
specify the test you want to run:

```shell
cd tests
tmt -c arch=$(arch) run -v -eNODE="IP or hostname" -eBUILD_AIB_RPM=yes \
    plan --name connect \
    test --name custom-kernel \
    --filter 'tag:special'
```

### Using parallel test runner

Most of the integration test suite execution time is consumed during the build of the tar archive or image and even
though osbuild supports parallel execution using the same build directory to reuse downloaded artifacts, tmt itself
doesn't provide the ability to run tests parallelly on the same machine. So here comes the
[parallel-test-runner.sh](https://gitlab.com/CentOS/automotive/src/automotive-image-builder/-/blob/main/ci-scripts/parallel-test-runner.sh?ref_type=heads),
which decreases the total integration test suite execution by 60%.

To run tests using 5 parallel execution processes and `local` plan you can use:

```shell
cd tests
../ci-scripts/parallel-test-runner.sh 5 local
```

If you need to pass additional custom parameters, then you can use `TMT_RUN_OPTIONS` environment variable (here are
concrete settings for
[gitlab CI execution](https://gitlab.com/CentOS/automotive/src/automotive-image-builder/-/blob/main/ci-scripts/run_tmt_tests.sh?ref_type=heads#L69)).
For example if you would like to use the manually provisioned machine you can use following command:

```shell
cd tests
export TMT_RUN_OPTIONS='-v -eNODE="IP or hostname" plan --name connect'
../ci-scripts/ci-scripts/parallel-test-runner.sh
```

Please be aware that `parallel-test-runner.sh` is using TMT run predefined directories names under `/var/tmp/tmt` and
if a run directory for a test exists, it will skip this test execution. If you would like to remove any existing TMT
run directories you need to run following command before executing `parallel-test-runner.sh`:

```shell
tmt clean -v
```

### Customizing test execution

The following environment variables exist to customize test execution:

- **`AIB_BASE_REPO`**
   - Contains the URL of the base repository to install `automotive-image-builder` and its dependencies from
   - Default value: `https://autosd.sig.centos.org/AutoSD-10/nightly/repos/AutoSD/compose/AutoSD/\$arch/os/`
- **`AIB_CUSTOM_REPO`**
   - Contains the URL of the custom repository to install `automotive-image-builder` and its dependencies,
     for example, to test the custom `automotive-image-builder` package
   - Default value: _empty_
- **`AIB_DISTRO`**
   - Distribution used inside tests. Available distributions can be listed using `automotive-image-builder list-dist`
     on the relevant platform.
   - Default value: `autosd10-sig`
- **`AIB_SRPM_DIR`**
   - Directory where AIB source RPM should be uploaded before test execution
   - Default value: `/var/tmp/aib-srpm`
- **`BUILD_AIB_RPM`**
   - Enable or disable building AIB package from a source RPM package provided on a machine specified by `NODE` environment
     variable
   - Default value: `no`
   - Possible values: `yes` `no`
- **`REBUILD_BOOTC_BUILDER`**
   - Forces the rebuild of bootc builder container. By default the container is being rebuilt only when it doesn't exist.
   - Default value: `no`
   - Possible values: `yes` `no`
- **`NODE`**
   - IP address or hostname of the machine where integration tests will be run
   - Default value: _empty_
- **`NODE_SSH_KEY`**
   - Path to the SSH key used to connect to the testing machine
   - Default value: `~/.ssh/aib-tests`

## Setting up your machine to run tests locally

Ensure all packages listed in the [Prerequisites](#prerequisites) section are installed on your local machine.

## Setting up a VM to run integration tests

The following sections provide a detailed guide to preparing a VM to run integration tests against your local machine.
Currently, it's possible to run tests on CS9 or CS10 VMs. The overall steps are similar for both versions;
differences are noted.

### Generating SSH keys to access the VM

The following command creates an SSH key pair in the `~/.ssh` directory, which will be used later to access the testing VM:

```shell
cd ~/.ssh
ssh-keygen -t ecdsa -f aib-tests -N "" -C "root@aib-tests"
```

### Preparing the cloud-init configuration file

Configure the testing VM using the following cloud-init user data file:

```yaml
#cloud-config

users:
  - name: root
    ssh_authorized_keys:
      - @PUBLIC SSH KEY@

ssh:
  disable_root: false

yum_repos:
  aib-base-repo:
    name: AIB Base Repository
    baseurl: @AIB BASE REPO URL@
    enabled: true
    gpgcheck: false


# preinstall automotive-image-builder and tests dependencies
packages:
  - android-tools
  - osbuild
  - osbuild-auto
  - osbuild-luks2
  - osbuild-lvm2
  - osbuild-ostree
  - ostree
  - qemu-kvm
  - python3-jsonschema
  - python3-pyyaml
  - expect
  - socat

power_state:
  delay: now
  mode: poweroff
  message: Powering off a-i-b testing VM
  timeout: 2
  condition: true
```

Save the content from the cloud-init user data file into `/tmp/user-data.yml` and replace the following values:

- `@PUBLIC SSH KEY@` with the content of `~/.ssh/aib-tests.pub` file created in the previous section.
- `@AIB BASE REPO URL@` depending on the OS version used
   - CS9: `https://autosd.sig.centos.org/AutoSD-9/nightly/repos/AutoSD/compose/AutoSD/${arch}/os/`
   - CS10: `https://autosd.sig.centos.org/AutoSD-10/nightly/repos/AutoSD/compose/AutoSD/${arch}/os/`


### Creating the VM

Download the CentOS Stream base image:

```shell
sudo curl -o /var/lib/libvirt/images/aib-tests.qcow2 @IMAGE URL@
```

Replace `@IMAGE URL@` with the real URL depending on the OS version used:
- CS9: `https://cloud.centos.org/centos/9-stream/x86_64/images/CentOS-Stream-GenericCloud-x86_64-9-latest.x86_64.qcow2`
- CS10: `https://cloud.centos.org/centos/10-stream/x86_64/images/CentOS-Stream-GenericCloud-x86_64-10-latest.x86_64.qcow2`

Resize the default 10G disk for all tests to pass successfully:

```shell
sudo qemu-img resize /var/lib/libvirt/images/aib-tests.qcow2 +10G
```

Create the VM:

```shell
sudo virt-install  \
     --name aib-tests \
     --memory 16384  --cpu host-model --vcpus 8 --graphics none \
     --os-variant @OS VARIANT@ \
     --import \
     --disk /var/lib/libvirt/images/aib-tests.qcow2,format=qcow2,bus=virtio \
     --network default  \
     --cloud-init disable=on,user-data=/tmp/user-data.yml \
     --noreboot
```

Please replace `@OS VARIANT@` depending on the OS version used:
- CS9: `centos-stream9`
- CS10: `centos-stream10`

The VM stops after it is created.

Save the VM's disk to reuse it after test execution:

```shell
sudo qemu-img convert -c -O qcow2 \
    /var/lib/libvirt/images/aib-tests.qcow2 \
    /var/lib/libvirt/images/aib-tests.qcow2.bck
```

Start the VM:

```shell
sudo virsh start aib-tests
```

Display the VM IP address, which you need for test execution:

```shell
sudo virsh domifaddr aib-tests
```

Access the VM via SSH:

```shell
ssh -i ~/.ssh/aib-tests root@<VM IP ADDRESS>
```


### Starting the VM before running integration tests

1. Make sure the VM is stopped:

   ```shell
   sudo virsh shutdown aib-tests
   ```

2. Use the preconfigured disk for the VM:

   ```shell
   sudo cp /var/lib/libvirt/images/aib-tests.qcow2.bck \
       /var/lib/libvirt/images/aib-tests.qcow2
   ```

3. Start the VM:

   ```shell
   sudo virsh start aib-tests
   ```


## Developing integration tests

### Generating test ID

Every test should be distinctly identified with a unique ID.
When you add a new test, assign an ID to it:

```shell
$ cd tests
$ tmt test id .
New id 'UUID' added to test '/tests/path_to_your_new_test'.
...
```

### Checking for duplicate test IDs and summaries

In addition to having a unique ID, test summaries should also be descriptive and unique.
The CI will perform appropriate linting, but this can also be invoked locally:

```shell
$ cd tests

# requires tmt >= 1.35
$ tmt lint tests
Lint checks on all
fail G001 duplicate id "96aa0e17-5e23-4cc3-bc34-88368b8cc07b" in "/tests/some-test"
fail G001 duplicate id "96aa0e17-5e23-4cc3-bc34-88368b8cc07b" in "/tests/another-test"
```

## Tagging integration tests

Use `tmt` tags to separate test types and scope:

```shell
- `special` - intended for special tests that need to be executed separately from the normal integration test suite
- `upstream-only` - intended for upstream tests, should not run in downstream
- `virt-required` - intended for tests that run the built image as a VM and execute the test inside it
```

### Declaring tags in a test

#### Tagging example of test `main.fmf` file:

```shell
summary: Test example with 'special' and 'upstream-only' tagging
id: <UUID>
duration: 60m
tag: [special, upstream-only]
test: |
  ./test-example.sh
```

### Listing tests by tag examples:

```shell
tmt tests ls --filter tag:virt-required
tmt tests ls --filter tag:special
tmt tests ls --filter tag:upstream-only
```

### How to use in tmt run command:
In order to use `tmt` filtering, `--filter tag:<tag name>` is required. This example shows how to filter on `special` and `upstream-only`:

```shell
tmt run -vvv -eNODE="<IP or hostname>" plan --name connect tests \
  --filter tag:special --filter tag:upstream-only
```
