VERSION=$(shell python3 aib/version.py)

PREFIX=/usr
BINDIR=$(PREFIX)/bin
DATADIR=$(PREFIX)/lib/automotive-image-builder
DESTDIR=

OSBUILD_MPP_TAG=v124

.PHONY: all
all:
	@echo Run "make install DESTDIR=..." to install, otherwise run directly from checkout

install:
	mkdir -p $(DESTDIR)$(BINDIR)
	install bin/aib.installed $(DESTDIR)$(BINDIR)/aib
	install bin/aib-dev.installed $(DESTDIR)$(BINDIR)/aib-dev
	install -t $(DESTDIR)$(BINDIR) bin/air
	ln -sf aib $(DESTDIR)$(BINDIR)/automotive-image-builder
	ln -sf aib-dev $(DESTDIR)$(BINDIR)/automotive-image-builder-dev
	ln -sf air $(DESTDIR)$(BINDIR)/automotive-image-runner
	for subdir in distro distro/include include targets targets/include ; do \
		mkdir -p $(DESTDIR)$(DATADIR)/$$subdir ; \
		install -m 0644 -t $(DESTDIR)$(DATADIR)/$$subdir $$subdir/*.yml ; \
	done
	mkdir -p $(DESTDIR)$(DATADIR)/files
	find files -maxdepth 1 -type f -exec install -m 0644 {} $(DESTDIR)$(DATADIR)/files/ \;
	mkdir -p $(DESTDIR)$(DATADIR)/files/policies
	install -m 0644 files/policies/* $(DESTDIR)$(DATADIR)/files/policies/
	mkdir -p $(DESTDIR)/etc/automotive-image-builder/policies
	install -m 0644 files/policies/README.md $(DESTDIR)/etc/automotive-image-builder/policies/
	mkdir -p $(DESTDIR)$(DATADIR)/aib
	install  -t $(DESTDIR)$(DATADIR)/aib aib/*.py
	mkdir -p $(DESTDIR)$(DATADIR)/mpp/aibosbuild/util
	install  -t $(DESTDIR)$(DATADIR)/mpp mpp/aib-osbuild-mpp
	install  -t $(DESTDIR)$(DATADIR)/mpp/aibosbuild/util mpp/aibosbuild/util/*.py

.PHONY: test-unit
test-unit:
	pytest aib/tests

# To run single test, for example "make test-integration-selinux-config"
test-integration-%:
	cd tests && \
	tmt -c arch=$$(arch) --feeling-safe run -vvvv -ePROJECT_DIR=$$PWD/.. plan --name local test --name $*

.PHONY: test-integration
test-integration:
	cd tests && \
	tmt -c arch=$$(arch) --feeling-safe run -v -ePROJECT_DIR=$$PWD/.. plan --name local

.PHONY: test-integration
test-integration-parallel:
	cd tests && \
	TMT_RUN_OPTIONS="-ePROJECT_DIR=$$PWD/.. plan --name local" ../ci-scripts/parallel-test-runner.sh 5 local

.PHONY: test
test: test-unit test-integration yamllint

rpm:
	./build/build-rpm.sh -bb --release

srpm:
	./build/build-rpm.sh -bs --release

rpm_dev:
	./build/build-rpm.sh -bb

srpm_dev:
	./build/build-rpm.sh -bs

import-mpp:
	./import-osbuild-mpp.sh $(OSBUILD_MPP_TAG)

yamllint:
	yamllint -c .yamllint distro/ include/ targets/ examples files/

shellcheck:
	./ci-scripts/run-shellcheck.sh

.venv:
	python3 -m venv .venv
	. .venv/bin/activate; pip install json-schema-for-humans

generate-manifest-doc: .venv
	mkdir -p docs
	. .venv/bin/activate; generate-schema-doc files/manifest_schema.yml docs/manifest.html
	. .venv/bin/activate; generate-schema-doc --config template_name=md files/manifest_schema.yml docs/manifest.md
