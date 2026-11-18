#!/usr/bin/env bash
# Re-fetch the third-party browser assets into public/ (they are committed, so this is only
# needed to upgrade them). Needs node + npm.
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
( cd "$tmp" && npm init -y >/dev/null && npm i zxing-wasm tesseract.js tesseract.js-core @tesseract.js-data/eng @fontsource-variable/bricolage-grotesque @fontsource/ibm-plex-mono >/dev/null )
n="$tmp/node_modules"
mkdir -p public/vendor/tess public/fonts
cp "$n/zxing-wasm/dist/iife/reader/index.js"  public/vendor/zxing-reader.js
cp "$n/zxing-wasm/dist/reader/zxing_reader.wasm" public/vendor/zxing_reader.wasm
# text reader for labels with no square code (loaded only when used; the .wasm.js core embeds its wasm so it works inside a worker)
cp "$n/tesseract.js/dist/tesseract.min.js" "$n/tesseract.js/dist/worker.min.js" public/vendor/tess/
cp "$n/tesseract.js-core/tesseract-core-simd-lstm.wasm.js" public/vendor/tess/
cp "$n/@tesseract.js-data/eng/4.0.0_best_int/eng.traineddata.gz" public/vendor/tess/
cp "$n/@fontsource-variable/bricolage-grotesque/files/bricolage-grotesque-latin-wght-normal.woff2" public/fonts/bricolage.woff2
cp "$n/@fontsource/ibm-plex-mono/files/ibm-plex-mono-latin-400-normal.woff2" public/fonts/plexmono-400.woff2
cp "$n/@fontsource/ibm-plex-mono/files/ibm-plex-mono-latin-500-normal.woff2" public/fonts/plexmono-500.woff2
echo "vendored: tesseract.js $(node -p "require('$n/tesseract.js/package.json').version"), zxing-wasm $(node -p "require('$n/zxing-wasm/package.json').version")"
