#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
check_machine
[[ $EUID != 0 ]] || { echo 'makepkg als normaler Benutzer ausführen.' >&2; exit 1; }
# Isolated keyring: upstream signatures remain enabled.
export GNUPGHOME="$REPO/build/gnupg"
install -d -m700 "$GNUPGHOME"
gpg --batch --import "$REPO"/kernel/keys/pgp/*.asc
cd "$REPO/kernel"
PKGEXT=.pkg.tar.zst makepkg --syncdeps --cleanbuild "$@"
