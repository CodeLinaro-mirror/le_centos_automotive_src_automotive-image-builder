import pytest
import os
from pathlib import Path

from aib.policy import PolicyLoader, PolicyError, PolicyValidationError, Policy


def create_policy_test_setup(tmp_path, policy_content):
    """Helper function to create policy loader with real schema.

    Args:
        tmp_path: Pytest tmp_path fixture
        policy_content: YAML content for the policy file

    Returns:
        tuple: (policy_loader, policy_file_path)
    """
    # Create policy file in tmp_path
    policy_file = tmp_path / "policy.aibp.yml"
    policy_file.write_text(policy_content)

    # Use real project directory for schema
    project_root = os.path.join(os.path.dirname(__file__), "../..")
    loader = PolicyLoader(project_root)
    return loader, policy_file


def create_test_policy(restrictions):
    """Helper function to create a test policy with standard name/description.

    Args:
        restrictions: Dict of restrictions to apply

    Returns:
        Policy: Policy object with test metadata and given restrictions
    """
    policy_data = {
        "name": "test",
        "description": "Test policy",
        "restrictions": restrictions,
    }
    return Policy(policy_data, "rpi4")


def validate_standard_build_args(
    policy,
    mode="image",
    target="qemu",
    distribution="autosd9-sig",
    architecture="x86_64",
    repositories=None,
):
    """Helper function to validate build args with standard test values.

    Args:
        policy: Policy object to validate against
        mode: Build mode (default: "image")
        target: Build target (default: "qemu")
        distribution: Distribution (default: "autosd9-sig")
        architecture: Architecture (default: "x86_64")
        repositories: List of repositories (default: None)

    Returns:
        List of validation errors
    """
    return policy.validate_build_args(
        mode, target, distribution, architecture, repositories
    )


def test_policy_loader_valid_policy(tmp_path):
    """Test loading a valid policy file."""
    policy_content = """
name: test-policy
description: A test policy
restrictions:
  modes:
    allow:
      - image
  targets:
    disallow:
      - aws
"""

    loader, policy_file = create_policy_test_setup(tmp_path, policy_content)
    policy = loader.load_policy(policy_file, "rpi4")

    assert policy.name == "test-policy"
    assert policy.description == "A test policy"
    assert policy.mode_restrictions == {"allow": ["image"]}
    assert policy.target_restrictions == {"disallow": ["aws"]}


def test_policy_loader_missing_file():
    """Test loading a non-existent policy file."""
    loader = PolicyLoader("/tmp")

    with pytest.raises(PolicyError, match="Policy file not found"):
        loader.load_policy(Path("/nonexistent/policy.aibp.yml"), "rpi4")


def test_policy_loader_invalid_yaml(tmp_path):
    """Test loading a policy file with invalid YAML."""
    policy_file = tmp_path / "invalid.aibp.yml"
    policy_file.write_text("invalid: yaml: content: [")

    loader = PolicyLoader(str(tmp_path))

    with pytest.raises(PolicyError, match="Invalid YAML"):
        loader.load_policy(policy_file, "rpi4")


def test_policy_loader_missing_name(tmp_path):
    """Test loading a policy file without required name field."""
    policy_content = """
description: Missing name field
restrictions: {}
"""

    loader, policy_file = create_policy_test_setup(tmp_path, policy_content)
    with pytest.raises(PolicyValidationError, match="'name' is a required property"):
        loader.load_policy(policy_file, "rpi4")


def test_policy_loader_not_dict(tmp_path):
    """Test loading a policy file that's not a dictionary."""
    policy_content = "- this\n- is\n- a\n- list"

    loader, policy_file = create_policy_test_setup(tmp_path, policy_content)
    with pytest.raises(PolicyValidationError, match="must contain a YAML dictionary"):
        loader.load_policy(policy_file, "rpi4")


def test_policy_enforcer_mode_allow():
    """Test mode restrictions with allow list."""
    policy = create_test_policy({"modes": {"allow": ["image"]}})

    # Should pass
    errors = validate_standard_build_args(policy)
    assert errors == []

    # Should fail
    errors = validate_standard_build_args(policy, mode="package")
    assert len(errors) == 1
    assert "mode 'package' is not in allowed list" in errors[0]


def test_policy_enforcer_target_disallow():
    """Test target restrictions with disallow list."""
    policy = create_test_policy({"targets": {"disallow": ["aws"]}})

    # Should pass
    errors = validate_standard_build_args(policy)
    assert errors == []

    # Should fail
    errors = validate_standard_build_args(policy, target="aws")
    assert len(errors) == 1
    assert "target 'aws' is in disallowed list" in errors[0]


def test_policy_enforcer_multiple_restrictions():
    """Test enforcer with multiple restriction types."""
    policy_data = {
        "name": "test",
        "description": "Test policy",
        "restrictions": {
            "modes": {"allow": ["image"]},
            "distributions": {"allow": ["autosd9-sig"]},
            "architectures": {"disallow": ["s390x"]},
        },
    }
    policy = Policy(policy_data, "rpi4")

    # Should pass
    errors = policy.validate_build_args("image", "qemu", "autosd9-sig", "x86_64")
    assert errors == []

    # Should fail on multiple restrictions
    errors = policy.validate_build_args("package", "qemu", "cs9", "s390x")
    assert len(errors) == 3  # mode, distribution, architecture
    assert any("mode 'package'" in error for error in errors)
    assert any("distribution 'cs9'" in error for error in errors)
    assert any("architecture 's390x'" in error for error in errors)


def test_policy_enforcer_no_restrictions():
    """Test enforcer with no restrictions (should allow everything)."""
    policy = create_test_policy({})

    # Should pass
    errors = validate_standard_build_args(
        policy, mode="package", target="aws", distribution="cs9", architecture="s390x"
    )
    assert errors == []


def test_policy_enforcer_allowlist_properties():
    """Test enforcer with property allowlist restrictions."""
    policy_data = {
        "name": "test",
        "description": "Test policy",
        "restrictions": {
            "manifest_restrictions": {
                "allow": {"properties": ["name", "content", "content.rpms"]}
            }
        },
    }
    policy = Policy(policy_data, "rpi4")

    # Test allowed properties
    manifest = {"name": "test-manifest", "content": {"rpms": ["bash", "systemd"]}}
    errors = policy.validate_manifest(manifest)
    assert errors == []

    # Test forbidden property
    manifest_forbidden = {
        "name": "test-manifest",
        "content": {"rpms": ["bash"]},
        "experimental": {"feature": True},
    }
    errors = policy.validate_manifest(manifest_forbidden)
    assert len(errors) == 1
    assert "experimental" in errors[0]
    assert "not in allowed list" in errors[0]


def test_policy_enforcer_allowlist_values():
    """Test enforcer with value allowlist restrictions."""
    policy_data = {
        "name": "test",
        "description": "Test policy",
        "restrictions": {
            "manifest_restrictions": {
                "allow": {
                    "values": {
                        "content.container_images[].containers-transport": ["docker"]
                    }
                }
            }
        },
    }
    policy = Policy(policy_data, "rpi4")

    # Test allowed value
    manifest = {
        "name": "test",
        "content": {
            "container_images": [
                {"source": "registry.io/test:latest", "containers-transport": "docker"}
            ]
        },
    }
    errors = policy.validate_manifest(manifest)
    assert errors == []

    # Test forbidden value
    manifest_forbidden = {
        "name": "test",
        "content": {
            "container_images": [
                {
                    "source": "registry.io/test:latest",
                    "containers-transport": "containers-storage",
                }
            ]
        },
    }
    errors = policy.validate_manifest(manifest_forbidden)
    assert len(errors) == 1
    assert "containers-storage" in errors[0]
    assert "not in allowed list" in errors[0]


def test_policy_schema_validation_extended_features(tmp_path):
    """Test schema validation with all extended features."""
    policy_content = """
name: extended-policy
description: Policy with all features

restrictions:
  modes:
    allow:
      - image

  repositories:
    disallow:
      - untrusted-repo

  manifest_restrictions:
    disallow:
      properties:
        - experimental
      values:
        "content.container_images.containers-transport": ["containers-storage"]

  variables:
    force:
      disable_ipv6: true
      policy_test_var: "test_value"

  rpms:
    disallow:
      - telnet
      - dosfstools

  kernel_modules:
    disallow:
      - dccp
      - fat

  selinux_booleans:
    force:
      deny_ptrace: true
      httpd_can_network_connect: false

  sysctl:
    force:
      "net.ipv4.ip_forward": "0"
      "kernel.dmesg_restrict": "1"

"""

    # Use real schema - this test validates that all features can be loaded
    loader, policy_file = create_policy_test_setup(tmp_path, policy_content)
    policy = loader.load_policy(policy_file, "rpi4")

    assert policy.name == "extended-policy"
    assert policy.description == "Policy with all features"
    assert policy.mode_restrictions == {"allow": ["image"]}
    assert policy.repository_restrictions == {"disallow": ["untrusted-repo"]}
    assert policy.forced_variables == {
        "disable_ipv6": True,
        "policy_test_var": "test_value",
    }
    assert policy.disallowed_rpms == ["telnet", "dosfstools"]
    assert policy.disallowed_kernel_modules == ["dccp", "fat"]
    assert policy.forced_selinux_booleans == {
        "deny_ptrace": True,
        "httpd_can_network_connect": False,
    }
    assert policy.forced_sysctl == {
        "net.ipv4.ip_forward": "0",
        "kernel.dmesg_restrict": "1",
    }


def test_policy_schema_validation_mutual_exclusivity(tmp_path):
    """Test that schema correctly rejects allow+disallow combinations."""
    policy_content = """
name: bad-policy
description: Policy with both allow and disallow

restrictions:
  modes:
    allow:
      - image
    disallow:
      - package
"""

    loader, policy_file = create_policy_test_setup(tmp_path, policy_content)
    with pytest.raises(
        PolicyValidationError, match="cannot have both 'allow' and 'disallow' keys"
    ):
        loader.load_policy(policy_file, "rpi4")


def test_policy_schema_validation_rpms_disallow_only(tmp_path):
    """Test that RPMs only supports disallow, not allow."""
    policy_content = """
name: bad-rpm-policy
description: Policy with RPM allow list

restrictions:
  rpms:
    allow:
      - bash
      - systemd
"""

    loader, policy_file = create_policy_test_setup(tmp_path, policy_content)
    with pytest.raises(PolicyValidationError, match="Policy validation failed"):
        loader.load_policy(policy_file, "rpi4")


def test_policy_schema_validation_kernel_modules_disallow_only(tmp_path):
    """Test that kernel_modules only supports disallow, not allow."""
    policy_content = """
name: bad-module-policy
description: Policy with kernel module allow list

restrictions:
  kernel_modules:
    allow:
      - ext4
      - xfs
"""

    loader, policy_file = create_policy_test_setup(tmp_path, policy_content)
    with pytest.raises(PolicyValidationError, match="Policy validation failed"):
        loader.load_policy(policy_file, "rpi4")


def test_policy_schema_validation_missing_description(tmp_path):
    """Test that schema validation catches missing description."""
    policy_content = """
name: policy-without-description

restrictions:
  modes:
    allow:
      - image
"""

    loader, policy_file = create_policy_test_setup(tmp_path, policy_content)
    with pytest.raises(
        PolicyValidationError, match="'description' is a required property"
    ):
        loader.load_policy(policy_file, "rpi4")


def test_policy_properties_default_values():
    """Test that policy properties return empty defaults when not specified."""
    policy_data = {
        "name": "minimal-policy",
        "description": "Minimal policy with no restrictions",
        "restrictions": {},
    }
    policy = Policy(policy_data, "rpi4")

    # All properties should return empty defaults
    assert policy.mode_restrictions == {}
    assert policy.target_restrictions == {}
    assert policy.distribution_restrictions == {}
    assert policy.architecture_restrictions == {}
    assert policy.repository_restrictions == {}
    assert policy.manifest_restrictions == {}
    assert policy.forced_variables == {}
    assert policy.disallowed_rpms == []
    assert policy.disallowed_kernel_modules == []
    assert policy.forced_selinux_booleans == {}
    assert policy.forced_sysctl == {}


def test_policy_enforcer_get_forced_variables():
    """Test getting forced variables."""
    policy = create_test_policy(
        {
            "variables": {
                "force": {
                    "disable_ipv6": True,
                    "debug_mode": False,
                    "test_var": "test_value",
                }
            }
        }
    )

    forced_vars = policy.get_forced_variables()
    assert forced_vars == {
        "disable_ipv6": True,
        "debug_mode": False,
        "test_var": "test_value",
    }


def test_policy_enforcer_validate_manifest():
    """Test manifest validation."""
    policy_data = {
        "name": "test",
        "description": "Test policy",
        "restrictions": {
            "manifest_restrictions": {
                "disallow": {
                    "properties": ["experimental"],
                    "values": {"content.type": ["forbidden_type"]},
                }
            }
        },
    }
    policy = Policy(policy_data, "rpi4")

    # Should pass - no forbidden content
    manifest = {"content": {"type": "allowed_type"}, "other": "data"}
    errors = policy.validate_manifest(manifest)
    assert errors == []

    # Should fail - forbidden property
    manifest_experimental = {
        "experimental": True,
        "content": {"type": "allowed_type"},
    }
    errors = policy.validate_manifest(manifest_experimental)
    assert len(errors) == 1
    assert "forbidden property 'experimental' found" in errors[0]

    # Should fail - forbidden value
    manifest_forbidden_value = {"content": {"type": "forbidden_type"}}
    errors = policy.validate_manifest(manifest_forbidden_value)
    assert len(errors) == 1
    assert "has forbidden value 'forbidden_type'" in errors[0]


def test_policy_enforcer_repository_validation():
    """Test repository validation in build args."""
    policy = create_test_policy({"repositories": {"disallow": ["untrusted-repo"]}})

    # Should pass - no repositories or allowed repositories
    errors = validate_standard_build_args(policy)
    assert errors == []

    errors = validate_standard_build_args(policy, repositories=["official", "extras"])
    assert errors == []

    # Should fail - disallowed repository
    errors = validate_standard_build_args(
        policy, repositories=["official", "untrusted-repo"]
    )
    assert len(errors) == 1
    assert "repository 'untrusted-repo' is in disallowed list" in errors[0]


def test_policy_enforcer_array_element_validation():
    """Test manifest validation with array element paths using [] syntax."""
    policy_data = {
        "name": "test",
        "description": "Test policy",
        "restrictions": {
            "manifest_restrictions": {
                "disallow": {
                    "values": {
                        "content.container_images[].containers-transport": [
                            "containers-storage"
                        ]
                    }
                }
            }
        },
    }
    policy = Policy(policy_data, "rpi4")

    # Should pass - allowed transport
    manifest_allowed = {
        "content": {
            "container_images": [
                {"source": "quay.io/test/image1", "containers-transport": "docker"},
                {"source": "quay.io/test/image2", "containers-transport": "docker"},
            ]
        }
    }
    errors = policy.validate_manifest(manifest_allowed)
    assert errors == []

    # Should fail - forbidden transport in one element
    manifest_forbidden = {
        "content": {
            "container_images": [
                {"source": "quay.io/test/image1", "containers-transport": "docker"},
                {
                    "source": "quay.io/test/image2",
                    "containers-transport": "containers-storage",
                },
            ]
        }
    }
    errors = policy.validate_manifest(manifest_forbidden)
    assert len(errors) == 1
    assert "element 1" in errors[0]
    assert "containers-storage" in errors[0]

    # Should fail - forbidden transport in multiple elements
    manifest_multiple_forbidden = {
        "content": {
            "container_images": [
                {
                    "source": "quay.io/test/image1",
                    "containers-transport": "containers-storage",
                },
                {
                    "source": "quay.io/test/image2",
                    "containers-transport": "containers-storage",
                },
            ]
        }
    }
    errors = policy.validate_manifest(manifest_multiple_forbidden)
    assert len(errors) == 2
    assert "element 0" in errors[0]
    assert "element 1" in errors[1]


def test_policy_variable_generation():
    """Test that policy variables are correctly generated for MPP defines."""
    policy_data = {
        "name": "test-policy",
        "description": "Test policy for variable generation",
        "restrictions": {
            "variables": {"force": {"test_var": "test_value", "policy_enabled": True}},
            "rpms": {"disallow": ["bad-package", "another-bad-package"]},
            "kernel_modules": {"disallow": ["bad-module"]},
            "sysctl": {"force": {"test.setting": "1", "another.setting": "0"}},
            "selinux_booleans": {
                "force": {"test_boolean": False, "another_boolean": True}
            },
        },
    }
    policy = Policy(policy_data, "rpi4")

    # Test individual methods
    assert policy.get_forced_variables() == {
        "test_var": "test_value",
        "policy_enabled": True,
    }
    assert policy.disallowed_rpms == ["bad-package", "another-bad-package"]
    assert policy.disallowed_kernel_modules == ["bad-module"]
    assert policy.get_forced_sysctl() == {"test.setting": "1", "another.setting": "0"}
    assert policy.get_forced_selinux_booleans() == {
        "test_boolean": False,
        "another_boolean": True,
    }


def test_main_policy_variable_integration():
    """Test the policy variable integration logic from main.py."""

    policy_data = {
        "name": "integration-test",
        "description": "Integration test policy",
        "restrictions": {
            "variables": {"force": {"disable_ipv6": True}},
            "rpms": {"disallow": ["telnet"]},
            "kernel_modules": {"disallow": ["dccp"]},
            "sysctl": {"force": {"net.ipv4.ip_forward": "0"}},
            "selinux_booleans": {"force": {"deny_ptrace": True}},
        },
    }

    policy = Policy(policy_data, "rpi4")

    # Simulate the args object with policy
    class MockArgs:
        def __init__(self):
            self.policy = policy

    args = MockArgs()

    # Simulate the defines dictionary and policy variable addition from main.py
    defines = {"_basedir": "/test", "exports": []}

    # Copy the exact logic from main.py
    if args.policy:
        policy = args.policy

        # Add forced variables from policy
        forced_vars = policy.get_forced_variables()
        defines.update(forced_vars)

        # Add denylist variables
        defines["policy_denylist_rpms"] = policy.disallowed_rpms
        defines["policy_denylist_modules"] = policy.disallowed_kernel_modules

        # Add sysctl options
        sysctl_options = []
        for key, value in policy.get_forced_sysctl().items():
            sysctl_options.append({"key": key, "value": value})
        defines["policy_systemctl_options"] = sysctl_options

        # Add SELinux booleans
        selinux_booleans = []
        for key, value in policy.get_forced_selinux_booleans().items():
            bool_str = "true" if value else "false"
            selinux_booleans.append(f"{key}={bool_str}")
        defines["policy_selinux_booleans"] = selinux_booleans

    # Verify all variables are set correctly
    assert defines["disable_ipv6"] is True
    assert defines["policy_denylist_rpms"] == ["telnet"]
    assert defines["policy_denylist_modules"] == ["dccp"]
    assert defines["policy_systemctl_options"] == [
        {"key": "net.ipv4.ip_forward", "value": "0"}
    ]
    assert defines["policy_selinux_booleans"] == ["deny_ptrace=true"]


def test_policy_target_specific_restrictions(tmp_path):
    """Test that target-specific restrictions are merged correctly."""
    policy_content = """
name: target-test-policy
description: Policy with target-specific restrictions

restrictions:
  kernel_modules:
    disallow:
      - fat
      - nfs
    disallow@ebbr:
      - ufs-renesas
      - at24
    disallow@rpi4:
      - bcm2835-dma

  variables:
    force:
      global_var: true
    force@ebbr:
      ebbr_specific_var: "ebbr_value"
    force@rpi4:
      rpi_specific_var: "rpi_value"
"""

    # Test with rpi4 target
    loader, policy_file = create_policy_test_setup(tmp_path, policy_content)
    policy_rpi4 = loader.load_policy(policy_file, "rpi4")

    # Should have global + rpi4-specific modules
    assert set(policy_rpi4.disallowed_kernel_modules) == {"fat", "nfs", "bcm2835-dma"}
    # Should NOT have ebbr-specific modules
    assert "ufs-renesas" not in policy_rpi4.disallowed_kernel_modules
    assert "at24" not in policy_rpi4.disallowed_kernel_modules

    # Should have global + rpi4-specific variables
    forced_vars = policy_rpi4.forced_variables
    assert forced_vars["global_var"] is True
    assert forced_vars["rpi_specific_var"] == "rpi_value"
    assert "ebbr_specific_var" not in forced_vars

    # Test with ebbr target
    policy_ebbr = loader.load_policy(policy_file, "ebbr")

    # Should have global + ebbr-specific modules
    assert set(policy_ebbr.disallowed_kernel_modules) == {
        "fat",
        "nfs",
        "ufs-renesas",
        "at24",
    }
    # Should NOT have rpi4-specific modules
    assert "bcm2835-dma" not in policy_ebbr.disallowed_kernel_modules

    # Should have global + ebbr-specific variables
    forced_vars = policy_ebbr.forced_variables
    assert forced_vars["global_var"] is True
    assert forced_vars["ebbr_specific_var"] == "ebbr_value"
    assert "rpi_specific_var" not in forced_vars


def test_policy_variable_integration_complete(tmp_path):
    """Test complete policy variable integration with all policy features."""
    policy_content = """
name: integration-test-policy
description: Policy for testing complete variable integration

restrictions:
  variables:
    force:
      test_var_bool: true
      test_var_string: "test_value"
      policy_disable_efi_features: true

  rpms:
    disallow:
      - test-package

  kernel_modules:
    disallow:
      - test-module

  sysctl:
    force:
      "test.setting": "1"

  selinux_booleans:
    force:
      test_boolean: false
"""

    loader, policy_file = create_policy_test_setup(tmp_path, policy_content)
    policy = loader.load_policy(policy_file, "rpi4")

    # Test forced variables
    forced_vars = policy.get_forced_variables()
    expected_vars = {
        "test_var_bool": True,
        "test_var_string": "test_value",
        "policy_disable_efi_features": True,
    }
    assert forced_vars == expected_vars

    # Test sysctl values
    forced_sysctl = policy.get_forced_sysctl()
    assert forced_sysctl == {"test.setting": "1"}

    # Test SELinux booleans
    forced_selinux = policy.get_forced_selinux_booleans()
    assert forced_selinux == {"test_boolean": False}

    # Test denylist features
    assert policy.disallowed_rpms == ["test-package"]
    assert policy.disallowed_kernel_modules == ["test-module"]

    # Test main.py integration logic
    class MockArgs:
        def __init__(self):
            self.policy = policy

    args = MockArgs()
    defines = {"_basedir": "/test", "exports": []}

    # Simulate main.py policy variable addition
    if args.policy:
        policy = args.policy
        forced_vars = policy.get_forced_variables()
        defines.update(forced_vars)

        # Add denylist variables
        defines["policy_denylist_rpms"] = policy.disallowed_rpms
        defines["policy_denylist_modules"] = policy.disallowed_kernel_modules

        # Add sysctl options
        sysctl_options = []
        for key, value in policy.get_forced_sysctl().items():
            sysctl_options.append({"key": key, "value": value})
        defines["policy_systemctl_options"] = sysctl_options

        # Add SELinux booleans
        selinux_booleans = []
        for key, value in policy.get_forced_selinux_booleans().items():
            bool_str = "true" if value else "false"
            selinux_booleans.append(f"{key}={bool_str}")
        defines["policy_selinux_booleans"] = selinux_booleans

    # Verify all features are correctly integrated
    assert defines["test_var_bool"] is True
    assert defines["test_var_string"] == "test_value"
    assert defines["policy_disable_efi_features"] is True
    assert defines["policy_denylist_rpms"] == ["test-package"]
    assert defines["policy_denylist_modules"] == ["test-module"]
    assert defines["policy_systemctl_options"] == [
        {"key": "test.setting", "value": "1"}
    ]
    assert defines["policy_selinux_booleans"] == ["test_boolean=false"]


def test_require_simple_manifest(tmp_path):
    """Test require_simple_manifest restriction."""
    # Policy with restriction enabled
    policy_content = """
name: test-simple-only
description: Policy requiring simple manifests
restrictions:
  require_simple_manifest: true
"""
    loader, policy_file = create_policy_test_setup(tmp_path, policy_content)
    policy = loader.load_policy(policy_file, "qemu")

    assert policy.require_simple_manifest is True
    assert policy.validate_manifest_type(is_simple_manifest=True) == []
    errors = policy.validate_manifest_type(is_simple_manifest=False)
    assert len(errors) == 1
    assert "simple manifest (.aib.yml)" in errors[0]
    assert "low-level manifest (.mpp.yml)" in errors[0]

    # Policy without restriction (default behavior)
    policy_content_default = """
name: test-no-restriction
description: Policy without manifest type restriction
restrictions:
  modes:
    allow:
      - image
"""
    policy_file_default = tmp_path / "policy_default.aibp.yml"
    policy_file_default.write_text(policy_content_default)
    policy_default = loader.load_policy(policy_file_default, "qemu")

    assert policy_default.require_simple_manifest is False
    assert policy_default.validate_manifest_type(is_simple_manifest=False) == []
