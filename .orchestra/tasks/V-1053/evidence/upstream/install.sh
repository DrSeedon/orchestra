#!/bin/sh
# Installs the latest tour release.
#
#   curl -fsSL https://raw.githubusercontent.com/init-co-jp/diff-tour/main/install.sh | sh
#
# Environment variables:
#   TOUR_VERSION      version to install, e.g. v0.1.0 (default: latest)
#   TOUR_INSTALL_DIR  where to put the binary (default: ~/.local/bin)
set -eu

repo="init-co-jp/diff-tour"
dir="${TOUR_INSTALL_DIR:-$HOME/.local/bin}"

say() { printf '%s\n' "$*"; }
fail() { printf 'install.sh: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "$1 is required"; }

need curl
need tar
need uname

case "$(uname -s)" in
  Linux) os=linux ;;
  Darwin) os=darwin ;;
  *) fail "unsupported OS: $(uname -s). On Windows, download the zip from https://github.com/$repo/releases" ;;
esac
case "$(uname -m)" in
  x86_64 | amd64) arch=amd64 ;;
  arm64 | aarch64) arch=arm64 ;;
  *) fail "unsupported CPU: $(uname -m)" ;;
esac

version="${TOUR_VERSION:-}"
if [ -z "$version" ]; then
  # The latest release URL redirects to .../releases/tag/vX.Y.Z
  url=$(curl -fsSLI -o /dev/null -w '%{url_effective}' "https://github.com/$repo/releases/latest") ||
    fail "could not find the latest release"
  version="${url##*/}"
fi
case "$version" in
  v*) ;;
  *) fail "could not find the latest release (got '$version')" ;;
esac

archive="diff-tour_${version#v}_${os}_${arch}.tar.gz"
base="https://github.com/$repo/releases/download/$version"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

say "Downloading tour $version ($os/$arch)"
curl -fsSL -o "$tmp/$archive" "$base/$archive" || fail "download failed: $base/$archive"
curl -fsSL -o "$tmp/checksums.txt" "$base/checksums.txt" || fail "download failed: $base/checksums.txt"

want=$(grep " $archive\$" "$tmp/checksums.txt" | cut -d' ' -f1)
[ -n "$want" ] || fail "no checksum for $archive"
if command -v sha256sum >/dev/null 2>&1; then
  got=$(sha256sum "$tmp/$archive" | cut -d' ' -f1)
else
  got=$(shasum -a 256 "$tmp/$archive" | cut -d' ' -f1)
fi
[ "$got" = "$want" ] || fail "checksum mismatch for $archive"

tar -xzf "$tmp/$archive" -C "$tmp" tour
mkdir -p "$dir"
mv "$tmp/tour" "$dir/tour"
chmod 755 "$dir/tour"
say "Installed $dir/tour"

case ":$PATH:" in
  *":$dir:"*) say "Run 'tour' inside a git repository to start." ;;
  *)
    case "${SHELL:-}" in
      */zsh) rc="~/.zshrc" ;;
      */bash) rc="~/.bashrc" ;;
      */fish) rc="" ;;
      *) rc="your shell's startup file" ;;
    esac
    say ""
    say "$dir is not on your PATH yet. To fix that, run:"
    if [ -z "$rc" ]; then
      say "  fish_add_path $dir"
    else
      say "  echo 'export PATH=\"$dir:\$PATH\"' >> $rc"
      say "and open a new terminal."
    fi
    ;;
esac
