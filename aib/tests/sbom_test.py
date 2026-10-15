import hashlib
import pathlib

import pytest


@pytest.fixture
def sbom_module(monkeypatch):
    repo_root = pathlib.Path(__file__).parents[2]
    monkeypatch.syspath_prepend(str(repo_root / "mpp"))
    import sbom

    return sbom


def make_pkg(
    name="testpkg",
    evr="1.0-1.el9",
    checksum="sha256:abc123",
    arch="x86_64",
    vendor="Test Vendor",
    url="https://example.com",
    sourcerpm="testpkg-1.0-1.el9.src.rpm",
    license="MIT",
    requires=None,
    provides=None,
):
    return {
        "name": name,
        "evr": evr,
        "checksum": checksum,
        "arch": arch,
        "vendor": vendor,
        "url": url,
        "sourcerpm": sourcerpm,
        "license": license,
        "requires": requires or [],
        "provides": provides or [],
    }


def test_rpm_package_id(sbom_module):
    pkg = sbom_module.SBOMRPMPackage(
        checksum="sha256:abcdef123456",
        name="testpkg",
        version="1.0",
        arch="x86_64",
        supplier="Test",
        files_analyzed=False,
        download_url="https://example.com",
        src_rpm="testpkg.src.rpm",
        licenses="MIT",
        requires=[],
        provides=[],
    )
    assert pkg.id == "SPDXRef-Package-rpm-testpkg-abcdef123456"


def test_rpm_package_id_no_sha256_prefix(sbom_module):
    pkg = sbom_module.SBOMRPMPackage(
        checksum="abcdef123456",
        name="testpkg",
        version="1.0",
        arch="x86_64",
        supplier="Test",
        files_analyzed=False,
        download_url="https://example.com",
        src_rpm="testpkg.src.rpm",
        licenses="MIT",
        requires=[],
        provides=[],
    )
    assert pkg.id == "SPDXRef-Package-rpm-testpkg-abcdef123456"


def test_spdx_formatter_package_fields(sbom_module):
    pkgs = [
        make_pkg(
            name="testpkg",
            evr="1.0-1.el9",
            checksum="sha256:abc123",
            arch="x86_64",
            vendor="Test Vendor",
            url="https://example.com",
            sourcerpm="testpkg-1.0-1.el9.src.rpm",
            license="MIT",
        )
    ]
    result = sbom_module.SBOM.from_pkgs("test-env", pkgs)
    output = result.serialize()
    assert "PackageName: testpkg" in output
    assert f"SPDXID: {result.rpm_packages[0].id}" in output
    assert "PackageVersion: 1.0-1.el9" in output
    assert "PackageSupplier: Organization: Test Vendor" in output
    assert "PackageDownloadLocation: https://example.com" in output
    assert "FilesAnalyzed: false" in output
    assert "PackageLicenseDeclared: (MIT)" in output
    assert "PackageSourceInfo: acquired package info during image build" in output
    assert (
        "ExternalRef: PACKAGE-MANAGER purl "
        "pkg:rpm/testpkg@1.0-1.el9?arch=x86_64"
        "&upstream=testpkg-1.0-1.el9.src.rpm"
    ) in output


@pytest.mark.parametrize(
    "license_val,expected",
    [
        pytest.param("MIT", "PackageLicenseDeclared: (MIT)", id="with-license"),
        pytest.param("", "PackageLicenseDeclared: NOASSERTION", id="empty-license"),
    ],
)
def test_spdx_formatter_license(sbom_module, license_val, expected):
    pkgs = [make_pkg(license=license_val)]
    result = sbom_module.SBOM.from_pkgs("test-env", pkgs)
    assert expected in result.serialize()


def test_spdx_formatter_relation(sbom_module):
    pkgs = [
        make_pkg(name="client", requires=["libfoo"], provides=["client"]),
        make_pkg(name="libfoo-pkg", checksum="sha256:def456", provides=["libfoo"]),
    ]
    result = sbom_module.SBOM.from_pkgs("test-env", pkgs)
    output = result.serialize()
    client_id = result.rpm_packages[0].id
    libfoo_id = result.rpm_packages[1].id
    assert f"Relationship: {client_id} DEPENDS_ON {libfoo_id}" in output


def test_serialize_custom_formatter(sbom_module):
    pkgs = [make_pkg()]
    result = sbom_module.SBOM.from_pkgs("test-env", pkgs)
    custom_output = result.serialize(fmt=lambda sbom: f"custom:{sbom.name}")
    assert custom_output == "custom:test-env"


def test_from_pkgs_basic(sbom_module):
    pkgs = [make_pkg()]
    result = sbom_module.SBOM.from_pkgs("test-env", pkgs)
    assert result.version == "SPDX-2.3"
    assert result.license == "CC0-1.0"
    assert result.element_id == "SPDXRef-DOCUMENT"
    assert result.name == "test-env"
    assert result.creator == [
        "Organization: Automotive Stream Distribution",
        "Tool: automotive-image-builder",
    ]
    assert len(result.rpm_packages) == 1
    assert result.rpm_packages[0].name == "testpkg"


@pytest.mark.parametrize(
    "evr,expected_version",
    [
        pytest.param("1:2.0-1.el9", "2.0-1.el9", id="with-epoch"),
        pytest.param("2.0-1.el9", "2.0-1.el9", id="without-epoch"),
    ],
)
def test_from_pkgs_epoch_stripping(sbom_module, evr, expected_version):
    pkgs = [make_pkg(evr=evr)]
    result = sbom_module.SBOM.from_pkgs("test-env", pkgs)
    assert result.rpm_packages[0].version == expected_version


def test_from_pkgs_dependency_resolution(sbom_module):
    pkgs = [
        make_pkg(name="client", requires=["libfoo"], provides=["client"]),
        make_pkg(name="libfoo-pkg", checksum="sha256:def456", provides=["libfoo"]),
    ]
    result = sbom_module.SBOM.from_pkgs("test-env", pkgs)
    assert len(result.rpm_packages) == 2
    client_id = result.rpm_packages[0].id
    libfoo_id = result.rpm_packages[1].id
    dep_relations = [r for r in result.relations if r.source == client_id]
    assert len(dep_relations) == 1
    assert dep_relations[0].target == libfoo_id
    assert dep_relations[0].rtype == "DEPENDS_ON"


def test_from_pkgs_unknown_dependency(sbom_module):
    pkgs = [make_pkg(name="client", requires=["/usr/bin/bash"])]
    result = sbom_module.SBOM.from_pkgs("test-env", pkgs)
    assert len(result.rpm_packages) == 2
    unknown_pkg = result.rpm_packages[1]
    assert unknown_pkg.name == "-usr-bin-bash"
    assert unknown_pkg.version == "NOASSERTION"
    assert unknown_pkg.arch == "NOASSERTION"
    assert unknown_pkg.supplier == "NOASSERTION"
    assert unknown_pkg.checksum == hashlib.sha256(b"/usr/bin/bash").hexdigest()
    assert len(result.relations) == 1
    assert result.relations[0].target == unknown_pkg.id


def test_from_pkgs_unknown_dependency_dedup(sbom_module):
    pkgs = [
        make_pkg(name="pkg-a", requires=["missing-dep"]),
        make_pkg(name="pkg-b", checksum="sha256:other", requires=["missing-dep"]),
    ]
    result = sbom_module.SBOM.from_pkgs("test-env", pkgs)
    unknown_pkgs = [p for p in result.rpm_packages if p.version == "NOASSERTION"]
    assert len(unknown_pkgs) == 1


def test_from_pkgs_self_provides(sbom_module):
    pkgs = [make_pkg(name="bash", requires=["bash"], provides=["bash"])]
    result = sbom_module.SBOM.from_pkgs("test-env", pkgs)
    assert len(result.rpm_packages) == 1
    assert len(result.relations) == 1
    assert result.relations[0].source == result.relations[0].target


def test_from_pkgs_empty(sbom_module):
    result = sbom_module.SBOM.from_pkgs("test-env", [])
    assert len(result.rpm_packages) == 0
    assert len(result.relations) == 0
    assert result.name == "test-env"


def test_serialize_header(sbom_module):
    pkgs = [make_pkg()]
    result = sbom_module.SBOM.from_pkgs("test-env", pkgs)
    output = result.serialize()
    assert "SPDXVersion: SPDX-2.3" in output
    assert "DataLicense: CC0-1.0" in output
    assert "SPDXID: SPDXRef-DOCUMENT" in output
    assert "DocumentName: test-env" in output
    assert "Created:" in output


def test_serialize_includes_packages_and_relations(sbom_module):
    pkgs = [
        make_pkg(name="client", requires=["libfoo"], provides=["client"]),
        make_pkg(name="libfoo-pkg", checksum="sha256:def456", provides=["libfoo"]),
    ]
    result = sbom_module.SBOM.from_pkgs("test-env", pkgs)
    output = result.serialize()
    assert "PackageName: client" in output
    assert "PackageName: libfoo-pkg" in output
    assert "##### Relationships" in output
    assert "DEPENDS_ON" in output


def test_serialize_document_namespace(sbom_module):
    """Test that DocumentNamespace includes a hash of packages and relations"""
    pkgs = [make_pkg()]
    result = sbom_module.SBOM.from_pkgs("test-env", pkgs)
    output = result.serialize()
    assert "DocumentNamespace: https://aib.org/spdx/test-env-" in output
    # Verify the namespace contains a hash (64 hex chars after the name)
    import re

    match = re.search(
        r"DocumentNamespace: https://aib.org/spdx/test-env-([a-f0-9]{64})", output
    )
    assert match is not None, "DocumentNamespace should contain a 64-character hex hash"


def test_serialize_creators(sbom_module):
    """Test that multiple creators are formatted correctly"""
    pkgs = [make_pkg()]
    result = sbom_module.SBOM.from_pkgs("test-env", pkgs)
    output = result.serialize()
    assert "Creator: Organization: Automotive Stream Distribution" in output
    assert "Creator: Tool: automotive-image-builder" in output


def test_spdx_formatter_files_analyzed_boolean(sbom_module):
    """Test that FilesAnalyzed is formatted as lowercase boolean"""
    pkg = sbom_module.SBOMRPMPackage(
        checksum="sha256:abc123",
        name="testpkg",
        version="1.0",
        arch="x86_64",
        supplier="Test",
        files_analyzed=True,
        download_url="https://example.com",
        src_rpm="testpkg.src.rpm",
        licenses="MIT",
        requires=[],
        provides=[],
    )
    sbom = sbom_module.SBOM(
        version="SPDX-2.3",
        license="CC0-1.0",
        element_id="SPDXRef-DOCUMENT",
        name="test",
        creator=["Tool: test"],
        created=sbom_module.datetime.now(sbom_module.timezone.utc),
        rpm_packages=[pkg],
        relations=[],
    )
    output = sbom.serialize()
    assert "FilesAnalyzed: true" in output
    assert "FilesAnalyzed: True" not in output


def test_from_pkgs_unknown_dependency_provides_field(sbom_module):
    """Test that unknown dependencies have the provides field set correctly"""
    pkgs = [make_pkg(name="client", requires=["/usr/bin/bash"])]
    result = sbom_module.SBOM.from_pkgs("test-env", pkgs)
    unknown_pkg = result.rpm_packages[1]
    assert unknown_pkg.provides == "/usr/bin/bash"


def test_spdx_formatter_package_section_header(sbom_module):
    """Test that each package has a section header"""
    pkgs = [make_pkg(name="testpkg")]
    result = sbom_module.SBOM.from_pkgs("test-env", pkgs)
    output = result.serialize()
    assert "##### Package: testpkg" in output


def test_spdx_formatter_relationships_section_header(sbom_module):
    """Test that relationships section has a header"""
    pkgs = [
        make_pkg(name="client", requires=["libfoo"], provides=["client"]),
        make_pkg(name="libfoo-pkg", checksum="sha256:def456", provides=["libfoo"]),
    ]
    result = sbom_module.SBOM.from_pkgs("test-env", pkgs)
    output = result.serialize()
    assert "##### Relationships" in output
