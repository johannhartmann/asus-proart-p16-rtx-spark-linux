# SPDX-License-Identifier: MIT
ROOT := $(abspath ..)
OUT ?= $(ROOT)/build/packages
MAKEPKG ?= makepkg
PACKAGES := p16-platform-policy p16-acpi-firmware p16-speaker-firmware

.PHONY: all $(PACKAGES) p16-displaylink p16-aquamarine
all: $(PACKAGES)

$(PACKAGES):
	@mkdir -p "$(OUT)/$@"
	@set -eu; while IFS= read -r file; do \
		[ -n "$$file" ] || continue; \
		cp "$(ROOT)/$$file" "$(OUT)/$@/$${file##*/}"; \
	done < "$@/sources"
	cp "$@/PKGBUILD" "$(OUT)/$@/PKGBUILD"
	cd "$(OUT)/$@" && $(MAKEPKG) --force --noconfirm

p16-displaylink:
	@mkdir -p "$(OUT)/$@"
	cp "$@/PKGBUILD" "$@/displaylink-driver.service" "$@/80-p16-displaylink.rules" "$(OUT)/$@/"
	cd "$(OUT)/$@" && $(MAKEPKG) --force --noconfirm

p16-aquamarine:
	@mkdir -p "$(OUT)/$@"
	cp "$@/PKGBUILD" "$(ROOT)/ports/aquamarine-0.16.0/evdi-reject-explicit-nonlinear-import.patch" "$(OUT)/$@/"
	cd "$(OUT)/$@" && $(MAKEPKG) --force --noconfirm
