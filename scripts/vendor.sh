#!/usr/bin/env bash
# Re-fetch the third-party browser assets into public/ (they are committed, so this is only
# needed to upgrade them). Needs node + npm.
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
( cd "$tmp" && npm init -y >/dev/null && npm i zxing-wasm tesseract.js tesseract.js-core @tesseract.js-data/eng three esbuild \
    @fontsource-variable/ibm-plex-sans @fontsource/ibm-plex-mono >/dev/null )
n="$tmp/node_modules"
mkdir -p public/vendor/tess public/fonts
cp "$n/zxing-wasm/dist/iife/reader/index.js"  public/vendor/zxing-reader.js
cp "$n/zxing-wasm/dist/reader/zxing_reader.wasm" public/vendor/zxing_reader.wasm
# text reader for labels with no square code (loaded only when used; the .wasm.js core embeds its wasm so it works inside a worker)
cp "$n/tesseract.js/dist/tesseract.min.js" "$n/tesseract.js/dist/worker.min.js" public/vendor/tess/
cp "$n/tesseract.js-core/tesseract-core-simd-lstm.wasm.js" public/vendor/tess/
cp "$n/@tesseract.js-data/eng/4.0.0_best_int/eng.traineddata.gz" public/vendor/tess/
# the 3D chip on the home page: three.js, tree-shaken to what scripts/hero3d.src.js uses (this three.js ships no minified build)
cp scripts/hero3d.src.js "$tmp/hero3d.src.js"
( cd "$tmp" && npx esbuild hero3d.src.js --bundle --minify --format=esm --target=es2020 --outfile=hero3d.js >/dev/null )
cp "$tmp/hero3d.js" public/vendor/hero3d.js
cp "$n/@fontsource-variable/ibm-plex-sans/files/ibm-plex-sans-latin-wght-normal.woff2" public/fonts/plexsans.woff2
for w in 400 500 600; do cp "$n/@fontsource/ibm-plex-mono/files/ibm-plex-mono-latin-$w-normal.woff2" public/fonts/plexmono-$w.woff2; done
echo "vendored: three $(node -p "JSON.parse(require('fs').readFileSync('$n/three/package.json')).version"), tesseract.js $(node -p "require('$n/tesseract.js/package.json').version"), zxing-wasm $(node -p "require('$n/zxing-wasm/package.json').version")"
