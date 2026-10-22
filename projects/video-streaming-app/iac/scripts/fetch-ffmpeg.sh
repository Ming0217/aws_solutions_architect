#!/usr/bin/env bash
#
# Fetch the pinned static FFmpeg build, verify its SHA256 against FFMPEG.lock,
# and extract only ffmpeg + ffprobe into assets/ffmpeg/bin so the CDK
# BucketDeployment has a non-empty asset dir. Run BEFORE `cdk synth`.
#
# Fails hard on a checksum mismatch or an empty output dir -- a missing/bad
# prebuild must never silently ship a worker with no FFmpeg.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IAC_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCK_FILE="$IAC_DIR/assets/ffmpeg/FFMPEG.lock"
BIN_DIR="$IAC_DIR/assets/ffmpeg/bin"

[ -f "$LOCK_FILE" ] || { echo "ERROR: lock file not found: $LOCK_FILE" >&2; exit 1; }

# shellcheck disable=SC1090
source "$LOCK_FILE"
: "${TAG:?TAG missing from FFMPEG.lock}"
: "${ASSET:?ASSET missing from FFMPEG.lock}"
: "${SHA256:?SHA256 missing from FFMPEG.lock}"

URL="https://github.com/BtbN/FFmpeg-Builds/releases/download/${TAG}/${ASSET}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "Fetching $URL"
curl -fL --retry 3 -o "$TMP_DIR/$ASSET" "$URL"

echo "Verifying SHA256"
if command -v sha256sum >/dev/null 2>&1; then
  ACTUAL="$(sha256sum "$TMP_DIR/$ASSET" | awk '{print $1}')"
else
  ACTUAL="$(shasum -a 256 "$TMP_DIR/$ASSET" | awk '{print $1}')"
fi
if [ "$ACTUAL" != "$SHA256" ]; then
  echo "ERROR: SHA256 mismatch for $ASSET" >&2
  echo "  expected: $SHA256" >&2
  echo "  actual:   $ACTUAL" >&2
  exit 1
fi

echo "Extracting ffmpeg + ffprobe"
EXTRACT_DIR="$TMP_DIR/extract"
mkdir -p "$EXTRACT_DIR"
# -J works on both GNU tar and macOS bsdtar; extract then copy the two binaries
# (portable, avoids --wildcards/--strip-components divergence between tars).
tar -xJf "$TMP_DIR/$ASSET" -C "$EXTRACT_DIR"

FFMPEG_BIN="$(find "$EXTRACT_DIR" -type f -name ffmpeg | head -1)"
FFPROBE_BIN="$(find "$EXTRACT_DIR" -type f -name ffprobe | head -1)"
[ -n "$FFMPEG_BIN" ] || { echo "ERROR: ffmpeg not found in archive" >&2; exit 1; }
[ -n "$FFPROBE_BIN" ] || { echo "ERROR: ffprobe not found in archive" >&2; exit 1; }

rm -rf "$BIN_DIR"
mkdir -p "$BIN_DIR"
cp "$FFMPEG_BIN" "$BIN_DIR/ffmpeg"
cp "$FFPROBE_BIN" "$BIN_DIR/ffprobe"
chmod +x "$BIN_DIR/ffmpeg" "$BIN_DIR/ffprobe"

if [ -z "$(ls -A "$BIN_DIR")" ]; then
  echo "ERROR: $BIN_DIR is empty after extraction" >&2
  exit 1
fi

echo "Done. Staged into $BIN_DIR:"
ls -l "$BIN_DIR"
