"""Policy system for automotive-image-builder."""

import os
import yaml
from enum import Enum
from pathlib import Path
from typing import Dict, Any, List, Optional

import jsonschema


class PolicyError(Exception):
    """Base exception for policy-related errors."""


class PolicyValidationError(PolicyError):
    """Exception raised when policy validation fails."""


class RestrictionType(Enum):
    """Types of policy restrictions."""

    MODE = "mode"
    TARGET = "target"
    DISTRIBUTION = "distribution"
    ARCHITECTURE = "architecture"
    REPOSITORY = "repository"


class PolicyLoader:
    """Load and validate policy files from YAML."""

    def __init__(self, base_dir):
        """Initialize policy loader."""
        self.base_dir = base_dir
        self._schema = None

    def _load_schema(self) -> Dict[str, Any]:
        """Load the policy validation schema."""
        if self._schema is None:
            schema_path = os.path.join(self.base_dir, "files", "policy_schema.yml")

            if not os.path.exists(schema_path):
                raise PolicyError(f"Policy schema file not found: {schema_path}")

            with open(schema_path, "r") as f:
                self._schema = yaml.safe_load(f)

        return self._schema

    def load_policy(self, policy_path: Path, target: str) -> "Policy":
        """Load and validate a policy file."""
        if not policy_path.exists():
            raise PolicyError(f"Policy file not found: {policy_path}")

        try:
            with open(policy_path, "r") as f:
                policy_data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise PolicyError(f"Invalid YAML in policy file: {e}")

        # Basic validation
        if not isinstance(policy_data, dict):
            raise PolicyValidationError("Policy file must contain a YAML dictionary")

        # Schema validation
        schema = self._load_schema()
        try:
            jsonschema.validate(policy_data, schema)
        except jsonschema.ValidationError as e:
            raise PolicyValidationError(f"Policy validation failed: {e.message}")
        except jsonschema.SchemaError as e:
            raise PolicyError(f"Policy schema error: {e.message}")

        # Validate allow/disallow consistency for target-specific restrictions
        self._validate_restriction_consistency(policy_data)

        return Policy(policy_data, target)

    def _validate_restriction_consistency(self, policy_data: Dict[str, Any]) -> None:
        """Validate that target-specific restrictions don't conflict with global ones."""
        restrictions = policy_data.get("restrictions", {})

        # Check each restriction section that exists
        for restriction_name, restriction_data in restrictions.items():
            if isinstance(restriction_data, dict):
                self._validate_restriction_section_consistency(
                    restriction_name, restriction_data
                )

    def _validate_restriction_section_consistency(
        self, restriction_name: str, restriction_data: Dict[str, Any]
    ) -> None:
        """Validate consistency within a single restriction section."""
        has_global_allow = "allow" in restriction_data
        has_global_disallow = "disallow" in restriction_data

        # Find target-specific keys
        target_allow_keys = [
            key for key in restriction_data.keys() if key.startswith("allow@")
        ]
        target_disallow_keys = [
            key for key in restriction_data.keys() if key.startswith("disallow@")
        ]

        # Rule 1: Can't have both global allow and global disallow
        if has_global_allow and has_global_disallow:
            raise PolicyValidationError(
                f"Restriction '{restriction_name}' cannot have both 'allow' and 'disallow' keys"
            )

        # Rule 2: If global uses allow, target-specific must use allow@target
        if has_global_allow and target_disallow_keys:
            raise PolicyValidationError(
                f"Restriction '{restriction_name}' uses global 'allow' but has target-specific 'disallow@' keys: {target_disallow_keys}"
            )

        # Rule 3: If global uses disallow, target-specific must use disallow@target
        if has_global_disallow and target_allow_keys:
            raise PolicyValidationError(
                f"Restriction '{restriction_name}' uses global 'disallow' but has target-specific 'allow@' keys: {target_allow_keys}"
            )


class Policy:
    """Represents a loaded policy with all restriction data."""

    def __init__(self, policy_data: Dict[str, Any], target: str):
        """Initialize policy from loaded data."""
        self.data = policy_data
        self.name = policy_data.get("name", "unknown")
        self.description = policy_data.get("description", "")
        self.target = target

        # Process restrictions to merge target-specific entries
        self.restrictions = self._process_restrictions(
            policy_data.get("restrictions", {})
        )

    def _process_restrictions(self, restrictions: Dict[str, Any]) -> Dict[str, Any]:
        """Process restrictions to merge target-specific entries and remove @target keys."""
        for restriction_data in restrictions.values():
            # Skip non-dict restrictions (e.g., boolean flags like require_simple_manifest)
            if not isinstance(restriction_data, dict):
                continue

            keys_to_remove = []

            # Find and merge target-specific keys
            for key, value in restriction_data.items():
                if "@" in key:
                    key_type, key_target = key.split("@", 1)
                    if key_target == self.target:
                        # Merge into base restriction
                        if key_type in restriction_data:
                            if key_type in ["allow", "disallow"]:
                                restriction_data[key_type].extend(value)
                            else:  # force
                                restriction_data[key_type].update(value)
                        else:
                            restriction_data[key_type] = value
                    keys_to_remove.append(key)

            # Remove all @target keys
            for key in keys_to_remove:
                del restriction_data[key]

        return restrictions

    @property
    def mode_restrictions(self) -> Dict[str, List[str]]:
        """Get mode restrictions (allow/disallow lists)."""
        return self.restrictions.get("modes", {})

    @property
    def target_restrictions(self) -> Dict[str, List[str]]:
        """Get target restrictions (allow/disallow lists)."""
        return self.restrictions.get("targets", {})

    @property
    def distribution_restrictions(self) -> Dict[str, List[str]]:
        """Get distribution restrictions (allow/disallow lists)."""
        return self.restrictions.get("distributions", {})

    @property
    def architecture_restrictions(self) -> Dict[str, List[str]]:
        """Get architecture restrictions (allow/disallow lists)."""
        return self.restrictions.get("architectures", {})

    @property
    def repository_restrictions(self) -> Dict[str, List[str]]:
        """Get repository restrictions (allow/disallow lists)."""
        return self.restrictions.get("repositories", {})

    @property
    def manifest_restrictions(self) -> Dict[str, Any]:
        """Get manifest content restrictions."""
        return self.restrictions.get("manifest_restrictions", {})

    @property
    def forced_variables(self) -> Dict[str, Any]:
        """Get variables to force to specific values."""
        return self.restrictions.get("variables", {}).get("force", {})

    @property
    def disallowed_rpms(self) -> List[str]:
        """Get list of disallowed RPM packages."""
        return self.restrictions.get("rpms", {}).get("disallow", [])

    @property
    def disallowed_kernel_modules(self) -> List[str]:
        """Get list of disallowed kernel modules."""
        return self.restrictions.get("kernel_modules", {}).get("disallow", [])

    @property
    def forced_selinux_booleans(self) -> Dict[str, bool]:
        """Get SELinux booleans to force to specific values."""
        return self.restrictions.get("selinux_booleans", {}).get("force", {})

    @property
    def masked_services(self) -> List[str]:
        """Get list of services to mask."""
        return self.restrictions.get("systemd", {}).get("masked_services", [])

    @property
    def enabled_services(self) -> List[str]:
        """Get list of services to enable."""
        return self.restrictions.get("systemd", {}).get("enabled_services", [])

    @property
    def disabled_services(self) -> List[str]:
        """Get list of services to disable."""
        return self.restrictions.get("systemd", {}).get("disabled_services", [])

    @property
    def forced_sysctl(self) -> Dict[str, str]:
        """Get sysctl parameters to force to specific values."""
        return self.restrictions.get("sysctl", {}).get("force", {})

    @property
    def require_simple_manifest(self) -> bool:
        """Check if policy requires simple manifest usage only."""
        return self.restrictions.get("require_simple_manifest", False)

    def validate_build_args(
        self,
        mode: str,
        target: str,
        distribution: str,
        architecture: str,
        repositories: Optional[List[str]] = None,
    ) -> List[str]:
        """Validate build arguments against policy restrictions."""
        errors = []

        # Validate mode
        errors.extend(
            self._validate_restriction(
                RestrictionType.MODE, mode, self.mode_restrictions
            )
        )

        # Validate target
        errors.extend(
            self._validate_restriction(
                RestrictionType.TARGET, target, self.target_restrictions
            )
        )

        # Validate distribution
        errors.extend(
            self._validate_restriction(
                RestrictionType.DISTRIBUTION,
                distribution,
                self.distribution_restrictions,
            )
        )

        # Validate architecture
        errors.extend(
            self._validate_restriction(
                RestrictionType.ARCHITECTURE,
                architecture,
                self.architecture_restrictions,
            )
        )

        # Validate repositories if provided
        if repositories:
            for repo in repositories:
                errors.extend(
                    self._validate_restriction(
                        RestrictionType.REPOSITORY, repo, self.repository_restrictions
                    )
                )

        return errors

    def validate_manifest_type(self, is_simple_manifest: bool) -> List[str]:
        """Validate manifest type against policy restrictions."""
        if self.require_simple_manifest and not is_simple_manifest:
            return [
                f"Policy '{self.name}' requires using a simple manifest (.aib.yml), "
                f"but a low-level manifest (.mpp.yml) was provided"
            ]
        return []

    def validate_manifest(self, manifest: Dict[str, Any]) -> List[str]:
        """Validate manifest content against policy restrictions."""
        errors = []
        manifest_restrictions = self.manifest_restrictions

        if "disallow" in manifest_restrictions:
            errors.extend(
                self._validate_disallow_manifest_restrictions(
                    manifest, manifest_restrictions["disallow"]
                )
            )

        if "allow" in manifest_restrictions:
            errors.extend(
                self._validate_allow_manifest_restrictions(
                    manifest, manifest_restrictions["allow"]
                )
            )

        return errors

    def get_forced_variables(self) -> Dict[str, Any]:
        """Get variables that should be forced to specific values."""
        return self.forced_variables

    def get_forced_selinux_booleans(self) -> Dict[str, bool]:
        """Get SELinux booleans that should be forced to specific values."""
        return self.forced_selinux_booleans

    def get_forced_sysctl(self) -> Dict[str, str]:
        """Get sysctl parameters that should be forced to specific values."""
        return self.forced_sysctl

    def _validate_restriction(
        self,
        restriction_type: RestrictionType,
        value: str,
        restrictions: Dict[str, List[str]],
    ) -> List[str]:
        """Validate a single restriction type."""
        errors = []

        if "allow" in restrictions and value not in restrictions["allow"]:
            errors.append(
                f"Policy '{self.name}': {restriction_type.value} '{value}' is not in allowed list: {restrictions['allow']}"
            )
        elif "disallow" in restrictions and value in restrictions["disallow"]:
            errors.append(
                f"Policy '{self.name}': {restriction_type.value} '{value}' is in disallowed list: {restrictions['disallow']}"
            )

        return errors

    def _validate_disallow_manifest_restrictions(
        self, manifest: Dict[str, Any], disallow_rules: Dict[str, Any]
    ) -> List[str]:
        """Validate manifest against disallow restrictions."""
        errors = []

        # Validate disallowed properties
        if "properties" in disallow_rules:
            for property_path in disallow_rules["properties"]:
                if self._has_nested_property(manifest, property_path):
                    errors.append(
                        f"Policy '{self.name}': forbidden property '{property_path}' found in manifest"
                    )

        # Validate disallowed values
        if "values" in disallow_rules:
            for property_path, forbidden_values in disallow_rules["values"].items():
                errors.extend(
                    self._validate_property_values(
                        manifest, property_path, forbidden_values
                    )
                )

        return errors

    def _validate_allow_manifest_restrictions(
        self, manifest: Dict[str, Any], allow_rules: Dict[str, Any]
    ) -> List[str]:
        """Validate manifest against allow restrictions."""
        errors = []

        # Validate allowed properties
        if "properties" in allow_rules:
            allowed_properties = allow_rules["properties"]
            errors.extend(
                self._validate_property_allowlist(manifest, allowed_properties)
            )

        # Validate allowed values
        if "values" in allow_rules:
            for property_path, allowed_values in allow_rules["values"].items():
                errors.extend(
                    self._validate_value_allowlist(
                        manifest, property_path, allowed_values
                    )
                )

        return errors

    def _validate_property_allowlist(
        self, manifest: Dict[str, Any], allowed_properties: List[str]
    ) -> List[str]:
        """Validate that only allowed properties are present in manifest."""
        errors = []

        def check_properties(obj: Dict[str, Any], path_prefix: str = "") -> None:
            if not isinstance(obj, dict):
                return

            for key, value in obj.items():
                current_path = f"{path_prefix}.{key}" if path_prefix else key

                # Check if this property is allowed
                property_allowed = current_path in allowed_properties
                parent_allowed = any(
                    current_path.startswith(allowed_prop + ".")
                    for allowed_prop in allowed_properties
                )

                if not property_allowed and not parent_allowed:
                    # Only report the error if no child properties will be checked
                    # This prevents duplicate errors for parent and child properties
                    if not isinstance(value, dict):
                        errors.append(
                            f"Policy '{self.name}': property '{current_path}' is not in allowed list"
                        )
                    else:
                        # For dict values, only report if this is a top-level forbidden property
                        is_top_level_forbidden = not any(
                            path_part.startswith(current_path + ".")
                            for path_part in allowed_properties
                        )
                        if is_top_level_forbidden:
                            errors.append(
                                f"Policy '{self.name}': property '{current_path}' is not in allowed list"
                            )
                            continue  # Don't recurse into forbidden properties

                # Recursively check nested objects
                if isinstance(value, dict):
                    check_properties(value, current_path)
                elif isinstance(value, list):
                    for i, item in enumerate(value):
                        if isinstance(item, dict):
                            check_properties(item, f"{current_path}[{i}]")

        check_properties(manifest)
        return errors

    def _validate_value_allowlist(
        self, manifest: Dict[str, Any], property_path: str, allowed_values: List[str]
    ) -> List[str]:
        """Validate that property values are in the allowed list."""
        errors = []

        if "[]" in property_path:
            # Handle array element validation
            errors.extend(
                self._validate_array_element_allowlist(
                    manifest, property_path, allowed_values
                )
            )
        else:
            # Handle regular property validation
            actual_value = self._get_nested_property(manifest, property_path)
            if actual_value is not None and actual_value not in allowed_values:
                errors.append(
                    f"Policy '{self.name}': property '{property_path}' has value '{actual_value}' which is not in allowed list {allowed_values}"
                )

        return errors

    def _validate_array_element_allowlist(
        self, manifest: Dict[str, Any], property_path: str, allowed_values: List[str]
    ) -> List[str]:
        """Validate array element values against allowed list."""
        errors = []

        # Parse array path (e.g., "content.container_images[].containers-transport")
        base_path, element_property = property_path.split("[].")
        array_obj = self._get_nested_property(manifest, base_path)

        if isinstance(array_obj, list):
            for i, element in enumerate(array_obj):
                if isinstance(element, dict) and element_property in element:
                    actual_value = element[element_property]
                    if actual_value not in allowed_values:
                        errors.append(
                            f"Policy '{self.name}': property '{property_path}' (element {i}) has value '{actual_value}' which is not in allowed list {allowed_values}"
                        )

        return errors

    def _validate_property_values(
        self, manifest: Dict[str, Any], property_path: str, forbidden_values: List[str]
    ) -> List[str]:
        """Validate property values against forbidden list, supporting array element paths."""
        errors = []

        if "[]" in property_path:
            # Handle array element validation
            errors.extend(
                self._validate_array_element_values(
                    manifest, property_path, forbidden_values
                )
            )
        else:
            # Handle regular property validation
            actual_value = self._get_nested_property(manifest, property_path)
            if actual_value in forbidden_values:
                errors.append(
                    f"Policy '{self.name}': property '{property_path}' has forbidden value '{actual_value}'"
                )

        return errors

    def _validate_array_element_values(
        self, manifest: Dict[str, Any], property_path: str, forbidden_values: List[str]
    ) -> List[str]:
        """Validate values in array elements against forbidden list.

        Supports paths like 'content.container_images[].containers-transport'
        """
        errors = []

        # Split path at the array marker
        parts = property_path.split("[]")
        if len(parts) != 2:
            # Invalid array path format
            return errors

        array_path = parts[0]  # e.g., "content.container_images"
        element_property = parts[1]  # e.g., ".containers-transport"

        # Remove leading dot from element property
        if element_property.startswith("."):
            element_property = element_property[1:]

        # Get the array
        array_data = self._get_nested_property(manifest, array_path)
        if not isinstance(array_data, list):
            return errors

        # Check each array element
        for i, element in enumerate(array_data):
            actual_value = (
                element
                if not element_property
                else self._get_nested_property(element, element_property)
            )
            if actual_value in forbidden_values:
                errors.append(
                    f"Policy '{self.name}': property '{property_path}' (element {i}) has forbidden value '{actual_value}'"
                )

        return errors

    def _get_nested_property(self, data: Dict[str, Any], property_path: str) -> Any:
        """Get nested property value using dot notation with array element support.

        Supports paths like:
        - simple.path: normal nested property access
        - array[].property: gets property from all elements in array
        - nested.array[].deep.property: complex nested array access
        """
        parts = property_path.split(".")
        current = data

        try:
            for part in parts:
                if part.endswith("[]"):
                    # Handle array element access
                    array_name = part[:-2]  # Remove '[]'
                    current = current[array_name]
                    if not isinstance(current, list):
                        return None
                    # Return list of values for array element property access
                    # This will be handled by the calling function
                    return current
                else:
                    current = current[part]
            return current
        except (KeyError, TypeError):
            return None

    def _has_nested_property(self, data: Dict[str, Any], property_path: str) -> bool:
        """Check if nested property exists using dot notation."""
        return self._get_nested_property(data, property_path) is not None
