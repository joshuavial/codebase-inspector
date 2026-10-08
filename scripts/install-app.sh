#!/usr/bin/env bash
# Build, package, install the cbi CLI, and staged-replace
# /Applications/Codebase Inspector.app. The previous copy is kept until the
# new one launches, and restored if it does not.
set -euo pipefail

if [[ $# -ne 0 ]]; then
  echo "install-app: takes no arguments" >&2
  exit 1
fi

cd "$(dirname "$0")/.."
repo=$(pwd)
app_dir="$repo/app"
src="$app_dir/release/mac-arm64/Codebase Inspector.app"
dest="/Applications/Codebase Inspector.app"
bin="$dest/Contents/MacOS/Codebase Inspector"

(
  cd "$app_dir"
  if [[ ! -d node_modules ]]; then
    npm ci
  fi
  npm run package
)
uv tool install --force --editable "$repo"

if pgrep -f "$bin" >/dev/null; then
  osascript -e 'quit app "Codebase Inspector"' || true
  for _ in {1..20}; do
    pgrep -f "$bin" >/dev/null || break
    sleep 0.5
  done
  if pgrep -f "$bin" >/dev/null; then
    echo "install-app: Codebase Inspector is still running" >&2
    exit 1
  fi
fi

[[ -d "$src" ]] || { echo "install-app: $src not found" >&2; exit 1; }

rm -rf "$dest.new" "$dest.prev"
ditto "$src" "$dest.new"
if [[ -d "$dest" ]]; then
  mv "$dest" "$dest.prev"
fi
mv "$dest.new" "$dest"

open -g "$dest"
for _ in {1..20}; do
  if pgrep -f "$bin" >/dev/null; then
    rm -rf "$dest.prev"
    version=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$dest/Contents/Info.plist")
    echo "install-app: installed and launched $dest ($version)"
    exit 0
  fi
  sleep 0.5
done

echo "install-app: new app did not launch; restoring previous copy" >&2
rm -rf "$dest"
if [[ -d "$dest.prev" ]]; then
  mv "$dest.prev" "$dest"
fi
exit 1
