import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from collections.abc import Callable


def spdx_formatter(sbom) -> str:

    def rpm_fmt(rpm: SBOMRPMPackage) -> str:
        analyzed = f"{rpm.files_analyzed}".lower()
        return f"""##### Package: {rpm.name}

PackageName: {rpm.name}
SPDXID: {rpm.id}
PackageVersion: {rpm.version}
PackageSupplier: Organization: {rpm.supplier}
PackageDownloadLocation: {rpm.download_url}
FilesAnalyzed: {analyzed}
PackageSourceInfo: acquired package info during image build
PackageLicenseDeclared: {'(' + rpm.licenses + ')' if rpm.licenses else 'NOASSERTION'}
ExternalRef: PACKAGE-MANAGER purl pkg:rpm/{rpm.name}@{rpm.version}?arch={rpm.arch}&upstream={rpm.src_rpm}
"""

    def relation_fmt(relation: SBOMRelation) -> str:
        return f"Relationship: {relation.source} {relation.rtype} {relation.target}"

    creator = '\n'.join('Creator: ' + c for c in sbom.creator)
    packages = '\n'.join(rpm_fmt(r) for r in sbom.rpm_packages)
    relations = '\n'.join(relation_fmt(r) for r in sbom.relations)

    namespace = hashlib.sha256(f"{packages}{relations}".encode("utf-8")).hexdigest().removeprefix("sha256:")
    
    return f"""SPDXVersion: {sbom.version}
DataLicense: {sbom.license}
SPDXID: {sbom.element_id}
DocumentName: {sbom.name}
DocumentNamespace: https://aib.org/spdx/{sbom.name}-{namespace}
Created: {sbom.created.strftime('%Y-%m-%dT%H:%M:%S')}
{creator}

{packages}

##### Relationships

{relations}
"""


@dataclass
class SBOMRelation:
    source: str
    target: str
    rtype: str


@dataclass
class SBOMRPMPackage:

    checksum: str
    name: str
    version: str
    arch: str
    supplier: str
    files_analyzed: bool
    download_url: str
    src_rpm: str
    licenses: str
    requires: list[str]
    provides: list[str]

    @property
    def id(self) -> str:
        pruned_checksum = self.checksum.removeprefix("sha256:")
        return f"SPDXRef-Package-rpm-{self.name}-{pruned_checksum}"


@dataclass
class SBOM:

    version: str
    license: str
    element_id: str
    name: str
    creator: list[str]
    created: datetime
    rpm_packages: list[SBOMRPMPackage]
    relations: list[SBOMRelation]

    @staticmethod
    def from_pkgs(env: str, packages: list[dict]) -> "SBOM":
        rpm_packages: list[SBOMRPMPackage] = []
        relations: list[SBOMRelation] = []

        provides_map: dict[str, str] = {}
        unknown_rpms_map: dict[str, SBOMRPMPackage] = {}

        for pkg in packages:
            # remove epoch from version
            version = pkg.get("evr")
            if ":" in version:
                version = version.split(":")[1]

            sbom_pkg = SBOMRPMPackage(
                checksum=pkg.get("checksum"),
                name=pkg.get("name"),
                version=version,
                arch=pkg.get("arch"),
                supplier=pkg.get("vendor"),
                files_analyzed=False,
                download_url=pkg.get("url"),
                src_rpm=pkg.get("sourcerpm"),
                licenses=pkg.get("license"),
                requires=pkg.get("requires", []),
                provides=pkg.get("provides", []),
            )
            rpm_packages.append(sbom_pkg)

            for provide in sbom_pkg.provides:
                provides_map[provide] = sbom_pkg.id

        for pkg in rpm_packages:
            pkg_dep_map: set[str] = set()
            for require in pkg.requires:
                dep = provides_map.get(require, None)

                # If no dependency has been found, then it is most likely a mismatch
                # in the requires and provides fields, e.g. /usr/bin/bash is required
                # by package A, but the bash package only provides /bin/bash.
                # In order to not drop them silently and still not trying to interpret
                # information into this, these RPM packages are added with only the name
                # and the relation ship created.
                if dep is None:
                    if require not in unknown_rpms_map:
                        unknown_rpm_dep = SBOMRPMPackage(
                            checksum=hashlib.sha256(require.encode()).hexdigest(),
                            name=require.replace("/", "-"),
                            version="NOASSERTION",
                            arch="NOASSERTION",
                            supplier="NOASSERTION",
                            files_analyzed=False,
                            download_url="NOASSERTION",
                            src_rpm="NOASSERTION",
                            licenses="NOASSERTION",
                            requires=[],
                            provides=require,
                        )
                        unknown_rpms_map[require] = unknown_rpm_dep
                        rpm_packages.append(unknown_rpm_dep)
                    dep = unknown_rpms_map[require].id

                pkg_dep_map.add(dep)

            for pkg_dep in pkg_dep_map:
                relations.append(
                    SBOMRelation(
                        source=pkg.id,
                        target=pkg_dep,
                        rtype="DEPENDS_ON",
                    )
                )

        return SBOM(
            version="SPDX-2.3",
            license="CC0-1.0",
            element_id="SPDXRef-DOCUMENT",
            name=env,
            creator=["Organization: Automotive Stream Distribution", "Tool: automotive-image-builder"],
            created=datetime.now(timezone.utc),
            rpm_packages=rpm_packages,
            relations=relations,
        )

    def serialize(self, fmt: Callable[["SBOM"], str] = spdx_formatter) -> str:
        return fmt(self)
