#!/bin/sh
# FilmCraft's web build (storytold/filmcraft, MIT OR Apache-2.0), beside the data, for the project's Edit step: a full
# timeline editor in the browser that NEXORA drives by its commands (window.filmcraft). Served at /filmcraft/.
# Run once: sh scripts/setup-filmcraft.sh [data dir]. About 42 MB. Nothing is fetched by the page itself afterwards.
set -e
DATA="${1:-data}"
VERSION="0.8.0"
DEST="$DATA/tools/filmcraft-web/$VERSION"
URL="https://github.com/storytold/filmcraft/releases/download/v$VERSION/filmcraft-web-$VERSION.zip"
TMP="$(mktemp -d)"
curl -fsSL -o "$TMP/f.zip" "$URL"
# The release's own SHA256SUMS.txt and GitHub's digest for the file agree on this; anything else is refused.
printf "6b13956fc741522427663517b1e483d6e0777891063fed02b1bd94bfada8a6c7  $TMP/f.zip\n" | shasum -a 256 -c -
mkdir -p "$DEST"
unzip -q -o "$TMP/f.zip" -d "$TMP/u"
cp -R "$TMP/u/filmcraft-web-$VERSION/." "$DEST/"
rm -rf "$TMP"
# The files the server will hand out, as checked when this version was taken in (the server checks them again at start).
printf "eb7882f9e8c17a5d28be4d287265a8f2029d4f1fe860eb3bcb3cf1664281399e  $DEST/filmcraft_web_bg.wasm\n8892fadd3f0a25f414259781316e95b6bb788b587afb9dbb645c0fb3648f38ce  $DEST/filmcraft_web.js\nbd87b647b9a99a5dc19c843d809f088b161238a122854af2698a24ba03515799  $DEST/index.html\ne3d3272a30eafe34505e5676eb3543d7248870835a5569f314f388c89b807524  $DEST/audio-worklet.js\n" | shasum -a 256 -c -
echo "ready $DEST"
