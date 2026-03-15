import pytest
import unittest
import tempfile
import os
import shutil
import yaml
import jsonschema
from unittest.mock import Mock, patch, mock_open

from aib import exceptions
from aib.simple import (
    without,
    parse_size,
    json_bool,
    ExtraInclude,
    Contents,
    QMContents,
    ManifestLoader,
    extend_with_default,
)
from aib.policy import Policy


@pytest.mark.parametrize(
    "orig,key,res",
    [
        ({"a": 17, "b": 42}, "b", {"a": 17}),
        ({"a": 17, "b": 42}, "a", {"b": 42}),
    ],
)
def test_without(orig, key, res):
    assert without(orig, key) == res


@pytest.mark.parametrize(
    "s,res",
    [
        ("2kB", 1000 * 2),
        ("2KiB", 1024 * 2),
        ("2MB", 1000 * 1000 * 2),
        ("2MiB", 1024 * 1024 * 2),
        ("2GB", 1000 * 1000 * 1000 * 2),
        ("2GiB", 1024 * 1024 * 1024 * 2),
        ("2TB", 1000 * 1000 * 1000 * 1000 * 2),
        ("2TiB", 1024 * 1024 * 1024 * 1024 * 2),
        ("42", 42),  # Test plain number
    ],
)
def test_parse_string(s, res):
    assert parse_size(s) == res


def test_parse_unsupported_string():
    """
    Cover negative case for parse_string
    """
    with pytest.raises(TypeError):
        parse_size("2Kg")


@pytest.mark.parametrize(
    "value,expected",
    [
        (True, "true"),
        (False, "false"),
        (1, "true"),
        (0, "false"),
        ("hello", "true"),
        ("", "false"),
        ([], "false"),
        ([1], "true"),
        (None, "false"),
    ],
)
def test_json_bool(value, expected):
    """Test json_bool function with various inputs"""
    assert json_bool(value) == expected


@pytest.mark.parametrize(
    "path,should_be_valid",
    [
        # Valid paths for add_files (only /etc and /usr)
        ("/etc/custom-files/file.txt", True),
        ("/etc/config.conf", True),
        ("/usr/bin/script.sh", True),
        ("/usr/lib/app.so", True),
        ("/usr/share/data.txt", True),
        # Invalid paths for add_files
        ("/var/log/app.log", False),  # /var not allowed for add_files
        ("/opt/aib/aib.txt", False),
        ("/usr/local/bin/script.sh", False),
        ("/custom-dir/file.txt", False),
        ("/test.txt", False),
        ("/boot/grub/grub.cfg", False),
        ("/home/user/.bashrc", False),
        ("/root/.ssh/authorized_keys", False),
    ],
)
def test_validate_add_files_paths(path, should_be_valid):
    """Test path validation for add_files (only /etc and /usr allowed)"""
    mock_loader = Mock()
    extra_include = ExtraInclude("/tmp/test-basedir")

    if should_be_valid:
        # Should not raise exception
        data = {"add_files": [{"path": path, "text": "content"}]}
        Contents(mock_loader, data, extra_include)
    else:
        # Should raise InvalidTopLevelPath
        data = {"add_files": [{"path": path, "text": "content"}]}
        with pytest.raises(exceptions.InvalidTopLevelPath) as exc_info:
            Contents(mock_loader, data, extra_include)
        assert path in str(exc_info.value)
        assert "add_files" in str(exc_info.value)


@pytest.mark.parametrize(
    "path,should_be_valid",
    [
        # Valid paths for make_dirs (/etc, /usr, and /var)
        ("/etc/custom-dir", True),
        ("/usr/local-app", True),  # doesn't start with /usr/local/
        ("/usr/lib/myapp", True),
        ("/var/log", True),  # /var IS allowed for make_dirs
        ("/var/lib/app", True),
        ("/var/cache", True),
        # Invalid paths for make_dirs
        ("/usr/local/bin", False),  # /usr/local explicitly disallowed
        ("/opt/aib", False),
        ("/custom-dir", False),
        ("/test", False),
        ("/boot/grub", False),
        ("/home/user", False),
        ("/root/.ssh", False),
    ],
)
def test_validate_make_dirs_paths(path, should_be_valid):
    """Test path validation for make_dirs (/etc, /usr, and /var allowed)"""
    mock_loader = Mock()
    extra_include = ExtraInclude("/tmp/test-basedir")

    if should_be_valid:
        # Should not raise exception
        data = {"make_dirs": [{"path": path}]}
        Contents(mock_loader, data, extra_include)
    else:
        # Should raise InvalidTopLevelPath
        data = {"make_dirs": [{"path": path}]}
        with pytest.raises(exceptions.InvalidTopLevelPath) as exc_info:
            Contents(mock_loader, data, extra_include)
        assert path in str(exc_info.value)
        assert "make_dirs" in str(exc_info.value)


class TestExtraInclude(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.extra_include = ExtraInclude(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_init(self):
        """Test ExtraInclude initialization"""
        self.assertEqual(self.extra_include.basedir, os.path.abspath(self.tmpdir))
        self.assertEqual(self.extra_include.content_id, 1)
        self.assertEqual(self.extra_include.file_content_inputs, {})
        self.assertEqual(self.extra_include.file_content_paths, [])

    def test_gen_id(self):
        """Test ID generation"""
        id1 = self.extra_include.gen_id()
        id2 = self.extra_include.gen_id()
        self.assertEqual(id1, 1)
        self.assertEqual(id2, 2)
        self.assertEqual(self.extra_include.content_id, 3)

    def test_gen_file_input_text(self):
        """Test gen_file_input with text data"""
        data = {"text": "Hello World"}
        result = self.extra_include.gen_file_input(1, data)
        expected = {
            "type": "org.osbuild.files",
            "origin": "org.osbuild.source",
            "mpp-embed": {"id": "image_content_id_1", "text": "Hello World"},
        }
        self.assertEqual(result, expected)

    def test_gen_file_input_url(self):
        """Test gen_file_input with URL data"""
        data = {"url": "https://example.com/file.txt"}
        result = self.extra_include.gen_file_input(2, data)
        expected = {
            "type": "org.osbuild.files",
            "origin": "org.osbuild.source",
            "mpp-embed": {
                "id": "image_content_id_2",
                "url": "https://example.com/file.txt",
            },
        }
        self.assertEqual(result, expected)

    def test_gen_file_input_source_path_relative(self):
        """Test gen_file_input with relative source path"""
        data = {"source_path": "subdir/file.txt"}
        result = self.extra_include.gen_file_input(3, data)
        expected_path = os.path.normpath(os.path.join(self.tmpdir, "subdir/file.txt"))
        expected = {
            "type": "org.osbuild.files",
            "origin": "org.osbuild.source",
            "mpp-embed": {"id": "image_content_id_3", "path": expected_path},
        }
        self.assertEqual(result, expected)

    def test_gen_file_input_source_path_absolute(self):
        """Test gen_file_input with absolute source path"""
        abs_path = "/tmp/absolute/file.txt"
        data = {"source_path": abs_path}
        result = self.extra_include.gen_file_input(4, data)
        expected = {
            "type": "org.osbuild.files",
            "origin": "org.osbuild.source",
            "mpp-embed": {"id": "image_content_id_4", "path": abs_path},
        }
        self.assertEqual(result, expected)

    def test_gen_file_copy(self):
        """Test gen_file_copy"""
        result = self.extra_include.gen_file_copy(5)
        expected = {
            "from": {
                "mpp-format-string": "input://inlinefile5/{embedded['image_content_id_5']}"
            },
            "to": "tree:///image_content_5",
        }
        self.assertEqual(result, expected)

    def test_gen_file_copy_out(self):
        """Test gen_file_copy_out"""
        data = {"path": "/etc/config.txt"}
        result = self.extra_include.gen_file_copy_out(6, data)
        expected = {
            "from": "input://extra/image_content_6",
            "to": "tree:///etc/config.txt",
        }
        self.assertEqual(result, expected)

    def test_add_file_copy(self):
        """Test add_file_copy"""
        mock_contents = Mock()
        mock_contents.file_content_copy = []

        data = {"text": "content", "path": "/etc/test.txt"}
        self.extra_include.add_file_copy(mock_contents, data)

        # Check that file_content_inputs was populated
        self.assertIn("inlinefile1", self.extra_include.file_content_inputs)
        # Check that file_content_paths was populated
        self.assertEqual(len(self.extra_include.file_content_paths), 1)
        # Check that contents.file_content_copy was populated
        self.assertEqual(len(mock_contents.file_content_copy), 1)

    def test_generate_empty(self):
        """Test generate with no file content"""
        result = self.extra_include.generate()
        expected = {"version": "2", "pipelines": []}
        self.assertEqual(result, expected)

    def test_generate_with_content(self):
        """Test generate with file content"""
        mock_contents = Mock()
        mock_contents.file_content_copy = []

        data = {"text": "content", "path": "/etc/test.txt"}
        self.extra_include.add_file_copy(mock_contents, data)

        result = self.extra_include.generate()

        self.assertEqual(result["version"], "2")
        self.assertEqual(len(result["pipelines"]), 1)
        pipeline = result["pipelines"][0]
        self.assertEqual(pipeline["name"], "extra-image-content")
        self.assertEqual(len(pipeline["stages"]), 1)
        stage = pipeline["stages"][0]
        self.assertEqual(stage["type"], "org.osbuild.copy")
        self.assertIn("inputs", stage)
        self.assertIn("options", stage)


class TestContents(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mock_loader = Mock()
        self.mock_loader.defines = {"arch": "x86_64"}
        self.mock_loader.set = Mock()
        self.extra_include = ExtraInclude(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_init(self):
        """Test Contents initialization"""
        data = {
            "enable_repos": ["debug"],
            "repos": [{"baseurl": "http://example.com"}],
            "rpms": ["vim", "git"],
            "container_images": ["registry.com/app:latest"],
            "add_files": [],
            "chown_files": [],
            "chmod_files": [],
            "remove_files": [],
            "make_dirs": [],
            "systemd": {
                "enabled_services": ["sshd"],
                "masked_services": ["getty@tty1.service"],
            },
        }

        contents = Contents(self.mock_loader, data, self.extra_include)

        self.assertEqual(contents.enable_repos, ["debug"])
        self.assertEqual(contents.repos, [{"baseurl": "http://example.com"}])
        self.assertEqual(contents.rpms, ["vim", "git"])
        self.assertEqual(contents.containers, ["registry.com/app:latest"])
        self.assertEqual(
            contents.systemd,
            {"enabled_services": ["sshd"], "masked_services": ["getty@tty1.service"]},
        )

    def test_get_key(self):
        """Test get_key method"""
        contents = Contents(self.mock_loader, {}, self.extra_include)
        self.assertEqual(contents.get_key("test_key"), "test_key")

    def test_set_define(self):
        """Test set_define method"""
        contents = Contents(self.mock_loader, {}, self.extra_include)
        contents.set_define("test_key", "test_value")
        self.mock_loader.set.assert_called_once_with("test_key", "test_value")

    def test_set_defines_with_containers(self):
        """Test set_defines with containers"""
        data = {"container_images": ["registry.com/app:latest"], "rpms": ["vim"]}
        contents = Contents(self.mock_loader, data, self.extra_include)
        contents.set_defines()

        # Check that podman was added to rpms
        expected_rpms = ["vim", "podman"]
        self.mock_loader.set.assert_any_call("simple_rpms", expected_rpms)
        self.mock_loader.set.assert_any_call("use_containers_extra_store", True)

    def test_set_defines_with_debug_repos(self):
        """Test set_defines with debug repos"""
        data = {"enable_repos": ["debug"]}
        contents = Contents(self.mock_loader, data, self.extra_include)
        contents.set_defines()

        self.mock_loader.set.assert_any_call("simple_add_debug_repos", True)

    def test_set_defines_with_devel_repos(self):
        """Test set_defines with devel repos"""
        data = {"enable_repos": ["devel"]}
        contents = Contents(self.mock_loader, data, self.extra_include)
        contents.set_defines()

        self.mock_loader.set.assert_any_call("simple_add_devel_repos", True)

    def test_set_defines_with_arch_substitution(self):
        """Test set_defines with arch substitution in repo URLs"""
        data = {"repos": [{"baseurl": "http://example.com/$arch/repo"}]}
        contents = Contents(self.mock_loader, data, self.extra_include)
        contents.set_defines()

        expected_repos = [{"baseurl": "http://example.com/x86_64/repo"}]
        self.mock_loader.set.assert_any_call("simple_repos", expected_repos)

    def test_set_defines_with_metalink_repo(self):
        """Test set_defines with metalink repo"""
        data = {
            "repos": [{"id": "test", "metalink": "http://example.com/$arch/metalink"}]
        }
        contents = Contents(self.mock_loader, data, self.extra_include)
        contents.set_defines()

        expected_repos = [
            {"id": "test", "metalink": "http://example.com/x86_64/metalink"}
        ]
        self.mock_loader.set.assert_any_call("simple_repos", expected_repos)

    def test_set_defines_with_mirrorlist_repo(self):
        """Test set_defines with mirrorlist repo"""
        data = {
            "repos": [
                {"id": "test", "mirrorlist": "http://example.com/$arch/mirrorlist"}
            ]
        }
        contents = Contents(self.mock_loader, data, self.extra_include)
        contents.set_defines()

        expected_repos = [
            {"id": "test", "mirrorlist": "http://example.com/x86_64/mirrorlist"}
        ]
        self.mock_loader.set.assert_any_call("simple_repos", expected_repos)

    def test_set_defines_with_files(self):
        """Test set_defines with file operations"""
        data = {
            "make_dirs": [{"path": "/etc/test"}],
            "chmod_files": [{"path": "/etc/test", "mode": "755"}],
            "chown_files": [{"path": "/etc/test", "owner": "root", "group": "root"}],
            "remove_files": [{"path": "/etc/old"}],
        }
        contents = Contents(self.mock_loader, data, self.extra_include)
        contents.set_defines()

        self.mock_loader.set.assert_any_call("simple_mkdir", [{"path": "/etc/test"}])
        self.mock_loader.set.assert_any_call(
            "simple_chmod", {"/etc/test": {"mode": "755"}}
        )
        self.mock_loader.set.assert_any_call(
            "simple_chown", {"/etc/test": {"owner": "root", "group": "root"}}
        )
        self.mock_loader.set.assert_any_call("simple_remove", ["/etc/old"])


class TestQMContents(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mock_loader = Mock()
        self.mock_loader.defines = {"arch": "x86_64"}
        self.mock_loader.set = Mock()
        self.extra_include = ExtraInclude(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_get_key_with_use_prefix(self):
        """Test QMContents get_key with use_ prefix"""
        qm_contents = QMContents(self.mock_loader, {}, self.extra_include)
        self.assertEqual(qm_contents.get_key("use_something"), "use_qm_something")

    def test_get_key_without_use_prefix(self):
        """Test QMContents get_key without use_ prefix"""
        qm_contents = QMContents(self.mock_loader, {}, self.extra_include)
        self.assertEqual(qm_contents.get_key("simple_rpms"), "qm_simple_rpms")


class TestManifestPolicyValidation(unittest.TestCase):
    """Test policy-based manifest validation in ManifestLoader."""

    def test_manifest_validation_no_policy(self):
        """Test that manifest validation works when no policy is provided."""
        manifest = {
            "name": "test",
            "version": "1.0",
            "experimental": {
                "internal_defines": {"test_var": "test_value"}
            },  # This would be forbidden by compliance policy, but should pass without policy
        }

        defines = {
            "_basedir": "/usr/lib/automotive-image-builder",
            "_workdir": "/tmp",
        }

        with patch("builtins.open", mock_open_manifest_schema()):
            loader = ManifestLoader(defines, policy=None)
            with patch.object(loader, "validator") as mock_validator:
                mock_validator.iter_errors.return_value = []
                with patch("yaml.dump"):
                    # Should not raise any exception
                    loader._load(manifest, "test.yml", "/tmp")

    def test_manifest_validation_with_policy_pass(self):
        """Test that manifest validation passes when policy allows the content."""
        manifest = {
            "name": "test",
            "version": "1.0",
            "content": {"rpms": ["bash", "systemd"]},  # Allowed packages
        }

        policy_data = {
            "name": "test-policy",
            "description": "Test policy",
            "restrictions": {
                "rpms": {
                    "disallow": ["telnet", "ftp"]
                }  # These packages not in manifest
            },
        }
        policy = Policy(policy_data, "rpi4")

        defines = {
            "_basedir": "/usr/lib/automotive-image-builder",
            "_workdir": "/tmp",
        }

        with patch("builtins.open", mock_open_manifest_schema()):
            loader = ManifestLoader(defines, policy=policy)
            with patch.object(loader, "validator") as mock_validator:
                mock_validator.iter_errors.return_value = []
                with patch("yaml.dump"):
                    # Should not raise any exception
                    loader._load(manifest, "test.yml", "/tmp")

    def test_manifest_validation_with_policy_fail_property(self):
        """Test that manifest validation fails when policy disallows a property."""
        manifest = {
            "name": "test",
            "version": "1.0",
            "experimental": {
                "internal_defines": {"test_var": "test_value"}
            },  # This property is disallowed by policy
        }

        policy_data = {
            "name": "test-policy",
            "description": "Test policy",
            "restrictions": {
                "manifest_restrictions": {"disallow": {"properties": ["experimental"]}}
            },
        }
        policy = Policy(policy_data, "rpi4")

        defines = {
            "_basedir": "/usr/lib/automotive-image-builder",
            "_workdir": "/tmp",
        }

        with patch("builtins.open", mock_open_manifest_schema()):
            loader = ManifestLoader(defines, policy=policy)
            with patch.object(loader, "validator") as mock_validator:
                mock_validator.iter_errors.return_value = []
                with patch("yaml.dump"):
                    # Should raise AIBException due to policy violation
                    with self.assertRaises(exceptions.AIBException) as ctx:
                        loader._load(manifest, "test.yml", "/tmp")
                    self.assertIn(
                        "forbidden property 'experimental' found", str(ctx.exception)
                    )

    def test_manifest_validation_with_policy_fail_value(self):
        """Test that manifest validation fails when policy disallows a value (compliance policy example)."""
        manifest = {
            "name": "test",
            "version": "1.0",
            "content": {
                "container_images": [
                    {
                        "source": "quay.io/test/image",
                        "containers-transport": "containers-storage",  # This value is disallowed by compliance policy
                    }
                ]
            },
        }

        # Use compliance policy restriction with array syntax
        policy_data = {
            "name": "test-compliance",
            "description": "Test compliance policy",
            "restrictions": {
                "manifest_restrictions": {
                    "disallow": {
                        "values": {
                            "content.container_images[].containers-transport": [
                                "containers-storage"
                            ]
                        },
                        "properties": ["experimental"],
                    }
                }
            },
        }
        policy = Policy(policy_data, "rpi4")

        defines = {
            "_basedir": "/usr/lib/automotive-image-builder",
            "_workdir": "/tmp",
        }

        with patch("builtins.open", mock_open_manifest_schema()):
            loader = ManifestLoader(defines, policy=policy)
            with patch.object(loader, "validator") as mock_validator:
                mock_validator.iter_errors.return_value = []
                with patch("yaml.dump"):
                    # Should raise AIBException due to policy violation
                    with self.assertRaises(exceptions.AIBException) as ctx:
                        loader._load(manifest, "test.yml", "/tmp")
                    self.assertIn(
                        "has forbidden value 'containers-storage'", str(ctx.exception)
                    )


class TestExtendWithDefault(unittest.TestCase):
    def test_extend_with_default(self):
        """Test extend_with_default function"""
        base_validator = jsonschema.Draft7Validator
        extended_validator = extend_with_default(base_validator)

        # Test that the extended validator has properties validator
        self.assertIn("properties", extended_validator.VALIDATORS)

        # Test with a schema that has defaults
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "default": "default_name"},
                "age": {"type": "number"},
            },
        }

        instance = {"age": 30}
        validator = extended_validator(schema)

        # Validate and check if default was set
        errors = list(validator.iter_errors(instance))
        self.assertEqual(len(errors), 0)
        self.assertEqual(instance["name"], "default_name")


class TestManifestLoader(unittest.TestCase):
    def load_manifest(self, manifest, policy=None):
        defines = {
            "_basedir": "/usr/lib/automotive-image-builder",
            "_workdir": "/tmp",
            "arch": "x86_64",
        }

        with patch("builtins.open", mock_open_manifest_schema()):
            loader = ManifestLoader(defines, policy)
            with patch.object(loader, "validator") as mock_validator:
                mock_validator.iter_errors.return_value = []
                with patch("yaml.dump"):
                    loader._load(manifest, "test.yml", "/tmp")
        return loader

    def test_basic(self):
        manifest = {"name": "test", "version": "1.0"}
        loader = self.load_manifest(manifest)
        self.assertEqual(loader.defines["name"], "test")
        self.assertEqual(loader.defines["version"], "1.0")

    def test_compliance(self):
        manifest = {
            "name": "test",
            "version": "1.0",
            "content": {
                "rpms": ["vim", "git", "podman"],
                "container_images": ["registry.redhat.io/ubi8/ubi:latest"],
                "systemd": {
                    "enabled_services": ["sshd"],
                    "masked_services": ["getty@tty1.service"],
                },
            },
        }
        loader = self.load_manifest(
            manifest, policy=None
        )  # Compliance validation now handled by policy system
        self.assertEqual(loader.defines["name"], "test")
        self.assertEqual(loader.defines["version"], "1.0")

    def test_with_qm_section(self):
        manifest = {
            "name": "test",
            "version": "1.0",
            "qm": {
                "memory_limit": {"max": "1G", "high": "800M"},
                "cpu_weight": 100,
                "container_checksum": "sha256:abcd1234",
                "content": {"rpms": ["qm-package"]},
            },
        }
        loader = self.load_manifest(manifest)
        self.assertEqual(loader.defines["use_qm"], True)
        self.assertEqual(loader.defines["qm_memory_max"], "1G")
        self.assertEqual(loader.defines["qm_memory_high"], "800M")
        self.assertEqual(loader.defines["qm_cpu_weight"], 100)
        self.assertEqual(loader.defines["boot_check_qm_digest"], "sha256:abcd1234")

    def test_with_network_section(self):
        manifest = {
            "name": "test",
            "version": "1.0",
            "network": {
                "static": {
                    "ip": "192.168.1.100",
                    "ip_prefixlen": 24,
                    "gateway": "192.168.1.1",
                    "dns": ["8.8.8.8"],
                    "iface": "eth0",
                    "load_module": "e1000",
                }
            },
        }
        loader = self.load_manifest(manifest)
        self.assertEqual(loader.defines["use_static_ip"], True)
        self.assertEqual(loader.defines["static_ip"], "192.168.1.100")
        self.assertEqual(loader.defines["static_ip_prefixlen"], "24")
        self.assertEqual(loader.defines["static_gw"], "192.168.1.1")
        self.assertEqual(loader.defines["static_dns"], ["8.8.8.8"])
        self.assertEqual(loader.defines["static_ip_iface"], "eth0")
        self.assertEqual(loader.defines["static_ip_modules"], ["e1000"])

    def test_with_auth_section(self):
        manifest = {
            "name": "test",
            "version": "1.0",
            "auth": {
                "root_password": "secret",
                "root_ssh_keys": ["ssh-rsa AAAAB3..."],
                "sshd_config": {"PermitRootLogin": "yes"},
                "groups": [{"name": "wheel"}],
                "users": [{"name": "testuser", "groups": ["wheel"]}],
            },
        }
        loader = self.load_manifest(manifest)
        self.assertEqual(loader.defines["root_password"], "secret")
        self.assertEqual(loader.defines["root_ssh_keys"], ["ssh-rsa AAAAB3..."])
        self.assertEqual(
            loader.defines["simple_sshd_config"], {"PermitRootLogin": "yes"}
        )
        self.assertEqual(loader.defines["simple_groups"], [{"name": "wheel"}])
        self.assertEqual(
            loader.defines["simple_users"], [{"name": "testuser", "groups": ["wheel"]}]
        )

    def test_with_kernel_section(self):
        manifest = {
            "name": "test",
            "version": "1.0",
            "kernel": {
                "kernel_package": "kernel-rt",
                "kernel_version": "5.14.0",
                "loglevel": 3,
                "debug_logging": True,
                "cmdline": ["quiet", "splash"],
                "remove_modules": ["pcspkr", "snd_pcsp"],
            },
        }
        loader = self.load_manifest(manifest)
        self.assertEqual(loader.defines["kernel_package"], "kernel-rt")
        self.assertEqual(loader.defines["kernel_version"], "5.14.0")
        self.assertEqual(loader.defines["kernel_loglevel"], 3)
        self.assertEqual(loader.defines["use_debug"], True)
        self.assertEqual(loader.defines["simple_kernel_opts"], ["quiet", "splash"])
        self.assertEqual(loader.defines["denylist_modules"], ["pcspkr", "snd_pcsp"])

    def test_with_image_section(self):
        manifest = {
            "name": "test",
            "version": "1.0",
            "image": {
                "image_size": "10GB",
                "hostname": "testhost",
                "ostree_ref": "rhel/9/x86_64/edge",
                "selinux_mode": "enforcing",
                "selinux_policy": "targeted",
                "selinux_booleans": {"httpd_can_network_connect": True},
                "partitions": {
                    "var": {
                        "size": "1GB",
                        "uuid": "12345678-1234-1234-1234-123456789012",
                    },
                    "home": {"size": "2GB"},
                },
            },
        }
        loader = self.load_manifest(manifest)
        self.assertEqual(loader.defines["image_size"], str(10 * 1000 * 1000 * 1000))
        self.assertEqual(loader.defines["hostname"], "testhost")
        self.assertEqual(loader.defines["ostree_ref"], "rhel/9/x86_64/edge")
        self.assertEqual(loader.defines["selinux_mode"], "enforcing")
        self.assertEqual(loader.defines["selinux_policy"], "targeted")
        self.assertEqual(
            loader.defines["selinux_booleans"], ["httpd_can_network_connect=true"]
        )
        self.assertEqual(loader.defines["varpart_size"], int(1000 * 1000 * 1000 / 512))
        self.assertEqual(
            loader.defines["varpart_uuid"], "12345678-1234-1234-1234-123456789012"
        )
        self.assertEqual(loader.defines["homepart_size"], int(2000 * 1000 * 1000 / 512))

    def test_with_experimental_section(self):
        manifest = {
            "name": "test",
            "version": "1.0",
            "experimental": {
                "internal_defines": {"custom_var": "custom_value", "another_var": 42}
            },
        }
        loader = self.load_manifest(manifest)
        self.assertEqual(loader.defines["custom_var"], "custom_value")
        self.assertEqual(loader.defines["another_var"], 42)

    def test_default_expand(self):
        manifest = {
            "name": "test",
            "version": "1.0",
            "content": {
                "rpms": ["vim", "git", "podman"],
                "container_images": ["registry.redhat.io/ubi8/ubi:latest"],
                "systemd": {
                    "enabled_services": ["sshd"],
                    "disabled_services": ["firewalld"],
                },
            },
        }
        loader = self.load_manifest(manifest)

        self.assertEqual(loader.defines["name"], "test")
        self.assertEqual(loader.defines["version"], "1.0")

        # Should add podman to rpms due to container_images
        expected_rpms = ["vim", "git", "podman", "podman"]
        self.assertEqual(loader.defines["simple_rpms"], expected_rpms)

    def test_handle_image_invalid_size(self):
        manifest = {
            "name": "test",
            "version": "1.0",
            "image": {
                "image_size": "1GB",
                "partitions": {
                    "var": {"size": "2GB"}  # var partition larger than image
                },
            },
        }

        with self.assertRaises(exceptions.InvalidMountSize):
            self.load_manifest(manifest)

    def test_handle_image_invalid_rel_size(self):
        manifest = {
            "name": "test",
            "version": "1.0",
            "image": {
                "partitions": {"var": {"relative_size": 1.5}}  # relative size >= 1
            },
        }

        with self.assertRaises(exceptions.InvalidMountRelSize):
            self.load_manifest(manifest)

    def test_handle_image_invalid_rel_size_negative(self):
        manifest = {
            "name": "test",
            "version": "1.0",
            "image": {
                "partitions": {"var": {"relative_size": -0.5}}  # negative relative size
            },
        }

        # This should not raise an exception as negative values are allowed
        loader = self.load_manifest(manifest)
        self.assertEqual(loader.defines["varpart_relative_size"], -0.5)

    def test_set_method(self):
        """Test the set method behavior with empty values"""
        defines = {
            "_basedir": "/test",
            "_workdir": "/tmp",
            "arch": "x86_64",
        }

        with patch("builtins.open", mock_open_manifest_schema()):
            loader = ManifestLoader(defines)

        # Test that empty list is not set
        loader.set("empty_list", [])
        self.assertNotIn("empty_list", loader.defines)

        # Test that empty dict is not set
        loader.set("empty_dict", {})
        self.assertNotIn("empty_dict", loader.defines)

        # Test that non-empty values are set
        loader.set("non_empty_list", ["item"])
        self.assertEqual(loader.defines["non_empty_list"], ["item"])

        loader.set("non_empty_dict", {"key": "value"})
        self.assertEqual(loader.defines["non_empty_dict"], {"key": "value"})

    def test_set_from_method(self):
        """Test the set_from method"""
        defines = {
            "_basedir": "/test",
            "_workdir": "/tmp",
            "arch": "x86_64",
        }

        with patch("builtins.open", mock_open_manifest_schema()):
            loader = ManifestLoader(defines)

        # Test with existing key
        src_dict = {"existing_key": "value"}
        loader.set_from("dest_key", src_dict, "existing_key")
        self.assertEqual(loader.defines["dest_key"], "value")

        # Test with non-existing key and default
        loader.set_from("dest_key2", src_dict, "non_existing_key", "default_value")
        self.assertEqual(loader.defines["dest_key2"], "default_value")

        # Test with non-existing key and no default
        loader.set_from("dest_key3", src_dict, "non_existing_key")
        self.assertNotIn("dest_key3", loader.defines)


def mock_open_manifest_schema():
    """Mock the manifest schema file"""
    schema_content = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "version": {"type": "string"},
            "content": {"type": "object"},
            "qm": {"type": "object"},
            "network": {"type": "object"},
            "auth": {"type": "object"},
            "kernel": {"type": "object"},
            "image": {"type": "object"},
            "experimental": {"type": "object"},
        },
    }
    return mock_open(read_data=yaml.dump(schema_content))


class TestExtraIncludeGlob(unittest.TestCase):
    """Test the new glob functionality in ExtraInclude class."""

    def setUp(self):
        """Create a temporary directory structure for testing."""
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(self._cleanup_test_dir)

        # Create test directory structure
        # test_dir/
        #   ├── files/
        #   │   ├── config1.conf
        #   │   ├── config2.conf
        #   │   └── readme.txt
        #   ├── subdir1/
        #   │   ├── app.log
        #   │   └── data.py
        #   └── subdir2/
        #       ├── system.log
        #       └── utils.py

        self.files_dir = os.path.join(self.test_dir, "files")
        self.subdir1 = os.path.join(self.test_dir, "subdir1")
        self.subdir2 = os.path.join(self.test_dir, "subdir2")

        os.makedirs(self.files_dir)
        os.makedirs(self.subdir1)
        os.makedirs(self.subdir2)

        # Create test files
        test_files = {
            "files/config1.conf": "# Configuration 1\nkey1=value1\n",
            "files/config2.conf": "# Configuration 2\nkey2=value2\n",
            "files/readme.txt": "This is a readme file\n",
            "subdir1/app.log": "Application log entry\n",
            "subdir1/data.py": "# Python data module\ndata = [1, 2, 3]\n",
            "subdir2/system.log": "System log entry\n",
            "subdir2/utils.py": "# Python utilities\ndef helper(): pass\n",
        }

        for rel_path, content in test_files.items():
            full_path = os.path.join(self.test_dir, rel_path)
            with open(full_path, "w") as f:
                f.write(content)

    def _cleanup_test_dir(self):
        """Clean up the temporary test directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_glob_files_flatten(self):
        """Test glob file copying with flattened structure."""
        extra_include = ExtraInclude(self.test_dir)

        # Mock contents object
        class MockContents:
            def __init__(self):
                self.file_content_copy = []
                self.make_dirs = []

        contents = MockContents()

        # Test flattening .conf files
        data = {
            "source_glob": "files/*.conf",
            "path": "/etc/config",
            "preserve_path": False,
        }

        extra_include._add_glob_files(contents, data)

        # Verify that two files were processed
        self.assertEqual(len(contents.file_content_copy), 2)

        # Verify the destination paths are flattened
        dest_paths = [entry["to"] for entry in contents.file_content_copy]
        expected_paths = [
            "tree:///etc/config/config1.conf",
            "tree:///etc/config/config2.conf",
        ]
        self.assertEqual(sorted(dest_paths), sorted(expected_paths))

        # Verify file_content_inputs were created
        self.assertEqual(len(extra_include.file_content_inputs), 2)

    def test_glob_files_preserve_path(self):
        """Test glob file copying with path preservation."""
        extra_include = ExtraInclude(self.test_dir)

        class MockContents:
            def __init__(self):
                self.file_content_copy = []
                self.make_dirs = []

        contents = MockContents()

        # Test preserving paths for .py files with recursive glob pattern
        data = {"source_glob": "**/*.py", "path": "/app/python", "preserve_path": True}

        extra_include._add_glob_files(contents, data)

        # Verify that two Python files were processed
        self.assertEqual(len(contents.file_content_copy), 2)

        # With the fix, **/*.py patterns now correctly preserve directory structure
        dest_paths = [entry["to"] for entry in contents.file_content_copy]
        expected_paths = [
            "tree:///app/python/subdir1/data.py",
            "tree:///app/python/subdir2/utils.py",
        ]
        self.assertEqual(sorted(dest_paths), sorted(expected_paths))

    def test_glob_files_preserve_path_recursive_working(self):
        """Test glob file copying with path preservation using explicit subdirectory patterns."""
        extra_include = ExtraInclude(self.test_dir)

        class MockContents:
            def __init__(self):
                self.file_content_copy = []
                self.make_dirs = []

        contents = MockContents()

        # Test preserving paths using wildcard subdir pattern
        data = {
            "source_glob": "subdir*/*.py",
            "path": "/app/python",
            "preserve_path": True,
        }

        extra_include._add_glob_files(contents, data)

        # Verify that two Python files were processed
        self.assertEqual(len(contents.file_content_copy), 2)

        # With the fix, subdir*/*.py patterns now correctly preserve directory structure
        dest_paths = [entry["to"] for entry in contents.file_content_copy]
        expected_paths = [
            "tree:///app/python/subdir1/data.py",
            "tree:///app/python/subdir2/utils.py",
        ]
        self.assertEqual(sorted(dest_paths), sorted(expected_paths))

    def test_glob_files_preserve_path_real_directory(self):
        """Test glob file copying with path preservation from a real directory path."""
        extra_include = ExtraInclude(self.test_dir)

        class MockContents:
            def __init__(self):
                self.file_content_copy = []
                self.make_dirs = []

        contents = MockContents()

        # Test preserving paths with a real directory (no wildcards in directory part)
        data = {
            "source_glob": "files/*.conf",
            "path": "/etc/config",
            "preserve_path": True,
        }

        extra_include._add_glob_files(contents, data)

        # Verify that two files were processed
        self.assertEqual(len(contents.file_content_copy), 2)

        # With preserve_path=True, the full relative path is preserved including 'files' directory
        dest_paths = [entry["to"] for entry in contents.file_content_copy]
        expected_paths = [
            "tree:///etc/config/files/config1.conf",
            "tree:///etc/config/files/config2.conf",
        ]
        self.assertEqual(sorted(dest_paths), sorted(expected_paths))

    def test_glob_files_preserve_path_with_subdirectory(self):
        """Test glob file copying with path preservation from a subdirectory."""
        extra_include = ExtraInclude(self.test_dir)

        class MockContents:
            def __init__(self):
                self.file_content_copy = []
                self.make_dirs = []

        contents = MockContents()

        # Test preserving paths when globbing from a specific subdirectory
        data = {"source_glob": "subdir1/*", "path": "/app/logs", "preserve_path": True}

        extra_include._add_glob_files(contents, data)

        # Verify that two files from subdir1 were processed
        self.assertEqual(len(contents.file_content_copy), 2)

        # Verify the destination paths preserve relative structure including subdir1
        dest_paths = [entry["to"] for entry in contents.file_content_copy]
        expected_paths = [
            "tree:///app/logs/subdir1/app.log",
            "tree:///app/logs/subdir1/data.py",
        ]
        self.assertEqual(sorted(dest_paths), sorted(expected_paths))

    def test_glob_files_no_matches_error(self):
        """Test that an error is raised when no files match the glob pattern."""
        extra_include = ExtraInclude(self.test_dir)

        class MockContents:
            def __init__(self):
                self.file_content_copy = []

        contents = MockContents()

        # Test with a pattern that matches no files
        data = {
            "source_glob": "nonexistent/*.xyz",
            "path": "/tmp/test",
            "preserve_path": False,
        }

        with self.assertRaises(exceptions.NoMatchingFilesError) as context:
            extra_include._add_glob_files(contents, data)

        self.assertIn("No files matched glob pattern", str(context.exception))
        self.assertEqual(context.exception.glob_pattern, "nonexistent/*.xyz")

    def test_glob_files_max_files_limit(self):
        """Test that glob pattern raises TooManyFilesError when max_files limit is exceeded."""
        extra_include = ExtraInclude(self.test_dir)

        # Create more files than the limit
        for i in range(5):
            with open(os.path.join(self.test_dir, f"test_file_{i}.txt"), "w") as f:
                f.write(f"content {i}")

        class MockContents:
            def __init__(self):
                self.file_content_copy = []

        contents = MockContents()

        data = {"source_glob": "test_file_*.txt", "path": "/tmp/test", "max_files": 3}

        # Should raise TooManyFilesError
        with self.assertRaises(exceptions.TooManyFilesError) as cm:
            extra_include._add_glob_files(contents, data)

        # Check the error message contains expected information
        error_message = str(cm.exception)
        self.assertIn("matched 5 files", error_message)
        self.assertIn("max_files limit is 3", error_message)
        self.assertIn("test_file_*.txt", error_message)

        # Should not process any files due to error
        self.assertEqual(len(contents.file_content_copy), 0)

    def test_glob_files_default_preserve_path(self):
        """Test that preserve_path defaults to False when not specified."""
        extra_include = ExtraInclude(self.test_dir)

        class MockContents:
            def __init__(self):
                self.file_content_copy = []

        contents = MockContents()

        # Test without preserve_path specified (should default to False)
        data = {
            "source_glob": "files/*.conf",
            "path": "/etc/config",
            # preserve_path not specified
        }

        extra_include._add_glob_files(contents, data)

        # Verify files are flattened (preserve_path=False behavior)
        dest_paths = [entry["to"] for entry in contents.file_content_copy]
        expected_paths = [
            "tree:///etc/config/config1.conf",
            "tree:///etc/config/config2.conf",
        ]
        self.assertEqual(sorted(dest_paths), sorted(expected_paths))

    def test_glob_files_absolute_path(self):
        """Test glob functionality with absolute paths."""
        extra_include = ExtraInclude("/some/other/dir")  # Different basedir

        class MockContents:
            def __init__(self):
                self.file_content_copy = []
                self.make_dirs = []

        contents = MockContents()

        # Test with absolute glob pattern
        absolute_glob = os.path.join(self.test_dir, "files", "*.conf")
        data = {
            "source_glob": absolute_glob,
            "path": "/etc/config",
            "preserve_path": False,
        }

        extra_include._add_glob_files(contents, data)

        # Verify that files were still found and processed
        self.assertEqual(len(contents.file_content_copy), 2)
        dest_paths = [entry["to"] for entry in contents.file_content_copy]
        expected_paths = [
            "tree:///etc/config/config1.conf",
            "tree:///etc/config/config2.conf",
        ]
        self.assertEqual(sorted(dest_paths), sorted(expected_paths))

    def test_add_file_copy_integration(self):
        """Test that add_file_copy properly delegates to _add_glob_files."""
        extra_include = ExtraInclude(self.test_dir)

        class MockContents:
            def __init__(self):
                self.file_content_copy = []
                self.make_dirs = []

        contents = MockContents()

        # Test that add_file_copy calls _add_glob_files for glob patterns
        data = {
            "source_glob": "files/*.conf",
            "path": "/etc/config",
            "preserve_path": False,
        }

        extra_include.add_file_copy(contents, data)

        # Verify that glob processing occurred
        self.assertEqual(len(contents.file_content_copy), 2)

        # Test that add_file_copy still handles regular files
        regular_file_data = {
            "source_path": "files/readme.txt",
            "path": "/etc/readme.txt",
        }

        extra_include.add_file_copy(contents, regular_file_data)

        # Should now have 3 files total (2 glob + 1 regular)
        self.assertEqual(len(contents.file_content_copy), 3)

    def test_glob_files_make_dirs_integration(self):
        """Test that directories are added to make_dirs when preserve_path=True creates subdirectories."""
        extra_include = ExtraInclude(self.test_dir)

        class MockContents:
            def __init__(self):
                self.file_content_copy = []
                self.make_dirs = []

        contents = MockContents()

        # Test with preserve_path=True that creates subdirectories
        data = {"source_glob": "**/*.py", "path": "/app/python", "preserve_path": True}
        extra_include._add_glob_files(contents, data)

        # Should have added directories to make_dirs
        self.assertEqual(len(contents.make_dirs), 2)

        # Check that the correct directories were added
        created_dirs = [d["path"] for d in contents.make_dirs]
        expected_dirs = ["/app/python/subdir1", "/app/python/subdir2"]
        self.assertEqual(sorted(created_dirs), sorted(expected_dirs))

        # All make_dirs entries should have parents=True
        for dir_entry in contents.make_dirs:
            self.assertEqual(dir_entry["parents"], True)

        # Generate the manifest - should only have copy stage now
        result = extra_include.generate()
        pipeline = result["pipelines"][0]
        self.assertEqual(len(pipeline["stages"]), 1)
        copy_stage = pipeline["stages"][0]
        self.assertEqual(copy_stage["type"], "org.osbuild.copy")

    def test_glob_files_no_make_dirs_when_flattened(self):
        """Test that no directories are added to make_dirs when preserve_path=False (flattened)."""
        extra_include = ExtraInclude(self.test_dir)

        class MockContents:
            def __init__(self):
                self.file_content_copy = []
                self.make_dirs = []

        contents = MockContents()

        # Test with preserve_path=False (flattened)
        data = {
            "source_glob": "**/*.py",
            "path": "/app/python",
            "preserve_path": False,
        }
        extra_include._add_glob_files(contents, data)

        # Should not have added any directories to make_dirs since files are flattened
        self.assertEqual(len(contents.make_dirs), 0)

        # Generate the manifest to check stages
        result = extra_include.generate()

        # Should have pipelines
        self.assertEqual(len(result["pipelines"]), 1)
        pipeline = result["pipelines"][0]

        # Should have only 1 stage: copy (no mkdir needed for flattened files)
        self.assertEqual(len(pipeline["stages"]), 1)
        copy_stage = pipeline["stages"][0]
        self.assertEqual(copy_stage["type"], "org.osbuild.copy")

    def test_glob_files_no_duplicate_make_dirs(self):
        """Test that duplicate directories are not added to make_dirs."""
        extra_include = ExtraInclude(self.test_dir)

        class MockContents:
            def __init__(self):
                self.file_content_copy = []
                self.make_dirs = []

        contents = MockContents()

        # Add files to same subdirectory twice
        data1 = {"source_glob": "subdir1/*.py", "path": "/app", "preserve_path": True}
        extra_include._add_glob_files(contents, data1)

        data2 = {"source_glob": "subdir1/*.log", "path": "/app", "preserve_path": True}
        extra_include._add_glob_files(contents, data2)

        # Should only have one entry for /app/subdir1 even though we added files from it twice
        self.assertEqual(len(contents.make_dirs), 1)
        self.assertEqual(contents.make_dirs[0]["path"], "/app/subdir1")

    def test_glob_files_with_parent_dir_references(self):
        """Test glob patterns that use ../ and could generate invalid paths."""
        # Create a basedir that simulates the examples directory
        examples_dir = os.path.join(self.test_dir, "examples")
        os.makedirs(examples_dir)

        # Create some test files in sibling directory to examples
        aib_dir = os.path.join(self.test_dir, "aib")
        os.makedirs(aib_dir)
        with open(os.path.join(aib_dir, "test_file.py"), "w") as f:
            f.write("# test file")

        extra_include = ExtraInclude(examples_dir)

        class MockContents:
            def __init__(self):
                self.file_content_copy = []
                self.make_dirs = []

        contents = MockContents()

        # Test glob pattern that goes up a directory level (like in glob-files.aib.yml)
        data = {
            "source_glob": "../aib/*.py",
            "path": "/etc/app/aib",
            "preserve_path": True,
        }

        extra_include._add_glob_files(contents, data)

        # Should have processed the file
        self.assertEqual(len(contents.file_content_copy), 1)

        # The destination path should not contain "../" sequences
        dest_path = contents.file_content_copy[0]["to"]
        self.assertNotIn("..", dest_path)

        # Since the relative path contains "..", it should fall back to basename
        expected_path = "tree:///etc/app/aib/test_file.py"
        self.assertEqual(dest_path, expected_path)

    def test_glob_files_recursive_directory_contents(self):
        """Test glob patterns with /**/* that copy directory contents without the directory itself."""
        extra_include = ExtraInclude(self.test_dir)

        class MockContents:
            def __init__(self):
                self.file_content_copy = []
                self.make_dirs = []

        contents = MockContents()

        # Test pattern that should copy contents of subdir1 without the subdir1 directory itself
        data = {
            "source_glob": "subdir1/**/*",
            "path": "/app/extracted",
            "preserve_path": True,
        }

        extra_include._add_glob_files(contents, data)

        # Should have processed the files from subdir1
        self.assertEqual(len(contents.file_content_copy), 2)

        # Files should be copied without the subdir1 prefix
        dest_paths = [entry["to"] for entry in contents.file_content_copy]
        expected_paths = [
            "tree:///app/extracted/app.log",
            "tree:///app/extracted/data.py",
        ]
        self.assertEqual(sorted(dest_paths), sorted(expected_paths))

        # No directories should be created since files go directly to the destination
        self.assertEqual(len(contents.make_dirs), 0)

    def test_glob_files_recursive_with_subdirs(self):
        """Test glob patterns with /**/* that include subdirectories."""
        extra_include = ExtraInclude(self.test_dir)

        # Create additional nested structure
        nested_dir = os.path.join(self.test_dir, "subdir1", "nested")
        os.makedirs(nested_dir)
        with open(os.path.join(nested_dir, "deep.txt"), "w") as f:
            f.write("deep file")

        class MockContents:
            def __init__(self):
                self.file_content_copy = []
                self.make_dirs = []

        contents = MockContents()

        # Test pattern that should copy all contents recursively
        data = {
            "source_glob": "subdir1/**/*",
            "path": "/app/extracted",
            "preserve_path": True,
        }

        extra_include._add_glob_files(contents, data)

        # Should have processed all files including nested ones
        self.assertEqual(len(contents.file_content_copy), 3)

        # Check that nested structure is preserved but subdir1 prefix is stripped
        dest_paths = [entry["to"] for entry in contents.file_content_copy]
        expected_paths = [
            "tree:///app/extracted/app.log",
            "tree:///app/extracted/data.py",
            "tree:///app/extracted/nested/deep.txt",
        ]
        self.assertEqual(sorted(dest_paths), sorted(expected_paths))

        # Should create the nested directory
        self.assertEqual(len(contents.make_dirs), 1)
        self.assertEqual(contents.make_dirs[0]["path"], "/app/extracted/nested")

    def test_glob_files_allow_empty_true(self):
        """Test that allow_empty=True creates destination directory when no files match"""
        extra_include = ExtraInclude(self.test_dir)

        class MockContents:
            def __init__(self):
                self.file_content_copy = []
                self.make_dirs = []

        contents = MockContents()

        # Test pattern that matches nothing
        data = {
            "source_glob": "nonexistent/*.xyz",
            "path": "/drop/in/dir",
            "allow_empty": True,
        }

        # Should not raise exception and should create directory
        extra_include._add_glob_files(contents, data)

        # Should have no files copied
        self.assertEqual(len(contents.file_content_copy), 0)

        # Should create the destination directory
        self.assertEqual(len(contents.make_dirs), 1)
        self.assertEqual(contents.make_dirs[0]["path"], "/drop/in/dir")
        self.assertTrue(contents.make_dirs[0]["parents"])

    def test_glob_files_allow_empty_false_raises_exception(self):
        """Test that allow_empty=False (default) raises NoMatchingFilesError when no files match"""
        extra_include = ExtraInclude(self.test_dir)

        class MockContents:
            def __init__(self):
                self.file_content_copy = []
                self.make_dirs = []

        contents = MockContents()

        # Test pattern that matches nothing with default allow_empty=False
        data = {
            "source_glob": "nonexistent/*.xyz",
            "path": "/some/dir",
        }

        # Should raise NoMatchingFilesError
        with self.assertRaises(exceptions.NoMatchingFilesError) as cm:
            extra_include._add_glob_files(contents, data)

        self.assertIn("nonexistent/*.xyz", str(cm.exception))

        # Should have no files copied and no directories created
        self.assertEqual(len(contents.file_content_copy), 0)
        self.assertEqual(len(contents.make_dirs), 0)

    def test_glob_files_allow_empty_explicit_false(self):
        """Test that explicitly setting allow_empty=False raises exception when no files match"""
        extra_include = ExtraInclude(self.test_dir)

        class MockContents:
            def __init__(self):
                self.file_content_copy = []
                self.make_dirs = []

        contents = MockContents()

        # Test pattern that matches nothing with explicit allow_empty=False
        data = {
            "source_glob": "missing/*.txt",
            "path": "/some/dir",
            "allow_empty": False,
        }

        # Should raise NoMatchingFilesError
        with self.assertRaises(exceptions.NoMatchingFilesError) as cm:
            extra_include._add_glob_files(contents, data)

        self.assertIn("missing/*.txt", str(cm.exception))
