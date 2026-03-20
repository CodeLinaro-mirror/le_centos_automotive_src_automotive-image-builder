# Automotive Image Builder — AI Code Review Context

## Project Overview

**Purpose:** Build tool for automotive OS images supporting both bootc/OSTree immutable systems (production) and traditional package-based disk images (development/testing).
**Type:** CLI tool suite — `aib` (bootc builds), `aib-dev` (package builds), `air` (QEMU runner)
**Domain:** Automotive Linux / Embedded Systems / Image Building
**Key Dependencies:** `osbuild` (image pipeline), `bootc`/`ostree` (immutable images), `podman` (containers), `image-builder` (disk conversion)

## Technology Stack

### Versions (current as of 2026-03-10)
- **Python** 3.x (no specific constraint in pyproject.toml)
- **osbuild** >=172 - Core image build pipeline engine
- **osbuild-auto** - Automotive-specific osbuild extensions
- **osbuild-ostree** - OSTree integration for osbuild
- **ostree** - Immutable filesystem tree for bootc images
- **image-builder** - NEW (commit 969a8354): Replaces bootc-image-builder container by default
- **bootc** - Container-based OS image format (for `aib` tool)
- **podman** - Container runtime for bootc images and running builds
- **python3-jsonschema** - Manifest schema validation
- **python3-pyyaml** - YAML manifest parsing
- **android-tools** - For `simg` (Android sparse image) format support
- **qemu-kvm-core** + **virtiofsd** - VM-based builds and testing

### Build Tools
- **Testing:** pytest (unit tests in `aib/tests/`), TMT framework (integration tests in `tests/`)
- **Linting:** yamllint, flake8, black
- **CI:** GitLab CI/CD
- **Package:** RPM (spec file: `automotive-image-builder.spec.in`)

## Architecture & Code Organization

### Structure
```
aib/
├── main.py              # Entry point for `aib` (bootc builds)
├── main_dev.py          # Entry point for `aib-dev` (package builds)
├── list_ops.py          # Shared list commands (list-rpms, list-targets, etc.)
├── simple.py            # High-level .aib.yml manifest parser
├── runner.py            # Execution context abstraction (sudo, containers, VMs)
├── osbuild.py           # OSBuild pipeline execution
├── podman.py            # Podman/container operations and bootc-image-builder
├── policy.py            # Policy file loading and manifest validation
├── ostree.py            # OSTree repository management
├── utils.py             # DiskFormat enum, sparse file handling, CPIO archives, key management
├── arguments.py         # CLI argument parsing with shared argument groups
└── progress.py          # OSBuild log pretty-printing

distro/                  # Distribution definitions (autosd10-sig, cs9, rhivos, etc.)
targets/                 # Hardware target configs (qemu, rpi4, ebbr, etc.)
include/                 # Core osbuild-mpp template includes
examples/                # Sample .aib.yml manifests
files/
├── manifest_schema.yml  # Schema for .aib.yml files
├── policy_schema.yml    # Schema for .aibp.yml policy files
└── bootc-builder.aib.yml # Manifest for build-builder command
tests/                   # TMT-based integration tests
```

### Key Patterns
- **Two-tier manifest system**: User writes `.aib.yml` → converted to `.mpp.yml` (osbuild-mpp format) → becomes `osbuild.json` pipeline
- **Runner abstraction** (`runner.py`): Unifies execution across contexts (host/container, root/user, sudo/VM). Uses volumes tracking for podman mounts.
- **Container storage modes**: Root storage (default) vs user storage (`--user-container`). Storage config path varies by mode. Important for `skopeo` and `podman` operations.
- **Disk format handling** (`utils.py`): `DiskFormat` enum handles image format detection and conversion (qcow2, raw, simg). Supports parsing from filename extensions or `--format` arg.
- **Sparse image handling** (`utils.py`): Android sparse images use SEEK_DATA/SEEK_HOLE to preserve holes. Functions: `convert_to_simg()`, `extract_part_of_file()`, `truncate_partition_size()`
- **Secure boot workflow**: `extract-for-signing` → external signing → `inject-signed` → `reseal`. Signing info in `/etc/signing_info.json` inside container.
- **Policy system**: `.aibp.yml` files enforce restrictions (allowed targets, forced variables, disallowed RPMs, sysctl settings). Applied with `--policy` flag.

### Critical Files
- **`aib/runner.py`** — Execution context manager. All command execution goes through this. Handles sudo, container mounting, and privilege requirements for osbuild.
- **`aib/podman.py`** — Bootc-image-builder integration. Recent change (e89ba3eb): now uses `image-builder` CLI by default instead of bootc-image-builder container.
- **`aib/simple.py`** — Parses `.aib.yml` manifests and generates includes for osbuild-mpp. Path validation enforced for `add_files`, `make_dirs`, `add_symlinks`.
- **`aib/utils.py`** — Sparse file utilities critical for simg format. SEEK_DATA/SEEK_HOLE logic must preserve holes (DONT_CARE chunks).
- **`files/manifest_schema.yml`** — JSON schema for user manifests. Any new manifest options must update this schema.

## Review Guidance

### What Reviewers Must Know
- **Tool selection matters**: `aib` builds bootc containers (immutable, OSTree-based) for production. `aib-dev` builds package-based images (mutable, traditional) for development. Don't conflate them.
- **Container storage is dual-mode**: Root storage (rootful podman) vs user storage (rootless). The `ContainerStorage` class handles config path differences. Don't suggest hardcoding paths.
- **image-builder is now default** (commit e89ba3eb): Prefer `image-builder` CLI over bootc-image-builder container unless `--vm` is used. The code has fallback logic for containers.
- **Sparse images require hole preservation**: When reviewing simg-related code, `SEEK_DATA`/`SEEK_HOLE` is essential. Don't suggest simpler file copying — it breaks Android sparse format.
- **Temporary paths have length constraints** (commit bacf873a): Use short prefixes like `bib-out--` instead of descriptive names. Nested containers hit pathname limits.
- **Reseal modifies initramfs**: Bootc images are "sealed" (signed root filesystem). Any modification requires reseal. The `prepare-reseal` + `reseal` workflow is for secureboot compatibility.
- **Policy validation happens early**: Policy files (`.aibp.yml`) validate before build starts. Don't suggest moving validation later — early failure is intentional.

### Do NOT Flag
- **Direct `subprocess.run()` calls in podman.py** — Intentional for skopeo, buildah operations that don't need Runner abstraction.
- **Root-owned file cleanup with sudo** — Many operations produce root-owned files. `SudoTemporaryDirectory` and `rm_rf()` with sudo are necessary, not security issues.
- **Random container names** (`random_container_name()`) — Temporary bootc builds use random names to avoid conflicts. Not a code smell.
- **Missing type hints in some modules** — Legacy code. New code should use types, but don't flag existing untyped functions unless you're already modifying them.
- **Long functions in main.py commands** — CLI command functions (decorated with `@command`) are intentionally procedural. Don't suggest extracting helpers unless there's duplication.

### Common Pitfalls
- **Container name prefixing** (commit 73328f85): Always use `localhost/` prefix for temporary containers to avoid registry confusion. Reviewers might suggest removing it.
- **Rootless container workarounds** (commit 3b413030): The `bootc-image-builder-local` path check handles rootless-in-rootless containers. Don't suggest simplifying — it's a real constraint.
- **grub2-tools-minimal for bootc** (commit 82a85972): Bootc builds need grub2-tools-minimal even though bootc itself doesn't depend on it. Needed for disk image conversion.
- **Path validation bypasses** — `simple.py` enforces allowed directories (`/etc/`, `/usr/`, `/var/`) and disallows `/usr/local/`. Don't accept PRs that bypass `ValidatedPathOperation` checks.
- **State machine violations in signing workflow** — extract-for-signing → inject-signed → reseal must happen in order. Can't skip steps or reorder.

---

<!-- MANUAL SECTIONS - DO NOT MODIFY THIS LINE -->

## Architecture & Design Decisions

- **Dual-tool approach** (`aib` vs `aib-dev`): Bootc images (immutable, atomic updates) are production-ready but slower to iterate. Package-based images (mutable, dnf-managed) enable rapid development cycles. Separate tools prevent mode confusion.
- **Policy system external to manifests**: Replaced hardcoded flags with flexible `.aibp.yml` policy files. Allows centralized enforcement without modifying every manifest.
- **QM partition isolation**: Quality Management (QM) code runs in separate partition (`/usr/share/qm/rootfs`) for functional safety requirements. OSBuild builds two pipelines (rootfs + QM) in parallel.

## Business Logic

- **Secure boot signing is two-phase**: Phase 1 (prepare-reseal) injects public key into initramfs for external signing. Phase 2 (reseal) signs rootfs with private key. Split allows HSM/3rd-party signing workflows.
- **Build-builder helper images**: Minimal automotive images lack disk creation tools (mkfs.ext4, etc.). `build-builder` creates per-distro helper containers with required tooling.
- **Sealing by default**: Bootc images include signed ostree commits. Initramfs validates signature on boot. Any modification (including injection of signed files) breaks seal — must reseal.

## Domain-Specific Context

- **OSBuild pipeline**: Declarative JSON manifest describes image build stages. Automotive Image Builder generates these manifests from high-level `.aib.yml` files.
- **OSTree vs package-based**: OSTree uses content-addressed storage with atomic updates. Package-based uses traditional RPM with dnf/yum. Fundamentally different update models.
- **Aboot**: Android boot format used on some automotive boards. Requires vbmeta signing. The `aboot` export creates partition images compatible with aboot bootloader.
- **Android sparse image (simg)**: Optimized for flashing large images to embedded storage. Chunks: RAW (data), FILL (repeated pattern), DONT_CARE (holes). Flashing tools skip DONT_CARE regions.
- **Automotive distributions**: AutoSD (Automotive SIG Distribution), RHIVOS (Red Hat In-Vehicle OS), CentOS Stream. Each has specific package repos and versions.

## Special Cases

- **automotive-image-runner (air)**: Companion QEMU wrapper tool for easily running images built with `qemu` or `abootqemu` targets. Simple usage: `air my-image.qcow2`. Not part of the build pipeline — purely for local testing.
- **Manifest variables on command line**: `--define VAR=VALUE` allows overriding internal osbuild-mpp variables. Not stable API — prefer manifest options when possible.
- **Image size calculation**: Partition sizes auto-calculated from content + 10% overhead. Manual `image_size` variable available for override but rarely needed.
- **Transient /etc mode**: `use_transient_etc=true` makes /etc changes persist across bootc updates. Contradicts immutability model — only for testing, never production.
