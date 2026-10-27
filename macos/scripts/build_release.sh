#!/bin/bash
# Build CrowSplat.app and a signed, notarized DMG.
#
#   macos/scripts/build_release.sh            build, sign, DMG, notarize if a profile exists
#   NOTARIZE=0 macos/scripts/build_release.sh skip notarization
#
# Needs: Xcode, xcodegen, uv, create-dmg (brew), a "Developer ID Application"
# certificate in the keychain, and for notarization a notarytool profile:
#   xcrun notarytool store-credentials crowsplat --apple-id <id> --team-id MMT322XFLL
set -euo pipefail

MAC="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(cd "$MAC/.." && pwd)"
OUT="$MAC/build/release"
IDENTITY="${IDENTITY:-Developer ID Application: Matti Schulz (MMT322XFLL)}"
PROFILE="${NOTARY_PROFILE:-crowsplat}"
PY_VERSION="3.13.11"
VERSION="$(sed -n 's/.*MARKETING_VERSION: "\(.*\)"/\1/p' "$MAC/project.yml")"

step() { printf '\n── %s ──\n' "$1"; }

step "Assets"
python3 "$MAC/scripts/sync_assets.py" --viewer

step "Build app ($VERSION)"
cd "$MAC"
xcodegen generate >/dev/null
rm -rf "$OUT"
xcodebuild -project CrowSplat.xcodeproj -scheme CrowSplat -configuration Release \
    -derivedDataPath "$OUT/dd" CODE_SIGN_IDENTITY="$IDENTITY" \
    OTHER_CODE_SIGN_FLAGS="--timestamp" build | grep -E "error:|warning: |BUILD" || true
APP="$OUT/dd/Build/Products/Release/CrowSplat.app"
[ -d "$APP" ] || { echo "build failed"; exit 1; }
RES="$APP/Contents/Resources"

step "Embed Python $PY_VERSION"
uv python install "$PY_VERSION" >/dev/null
PY_SRC="$(uv python find --managed-python "$PY_VERSION")"
PY_ROOT="$(cd "$(dirname "$PY_SRC")/.." && pwd)"
rsync -a --delete \
    --exclude 'lib/python3.13/test' --exclude 'lib/python3.13/idlelib' \
    --exclude 'lib/python3.13/tkinter' --exclude 'lib/python3.13/turtledemo' \
    --exclude 'lib/python3.13/ensurepip' --exclude 'lib/libtcl*' --exclude 'lib/libtk*' \
    --exclude 'lib/tcl*' --exclude 'lib/tk*' --exclude 'include' --exclude 'share' \
    --exclude '__pycache__' "$PY_ROOT/" "$RES/python/"
rm -f "$RES/python/lib/python3.13/EXTERNALLY-MANAGED"
PY="$RES/python/bin/python3"

step "Core dependencies (no Qt)"
# requirements.txt minus PySide6: the native app replaces the Qt GUI.
grep -v -i '^pyside6' "$ROOT/requirements.txt" > "$OUT/requirements-core.txt"
"$PY" -m pip install --quiet --no-compile --disable-pip-version-check -r "$OUT/requirements-core.txt"
"$PY" -m pip uninstall --quiet -y pip setuptools 2>/dev/null || true

step "Core"
mkdir -p "$RES/core/assets"
rsync -a --delete --exclude '__pycache__' --exclude 'app/gui' "$ROOT/app/" "$RES/core/app/"
# The bridge uses two Qt-free helpers from app/gui; nothing else from it ships.
mkdir -p "$RES/core/app/gui/panels"
cp "$ROOT/app/gui/__init__.py" "$ROOT/app/gui/chaining_logic.py" "$RES/core/app/gui/"
cp "$ROOT/app/gui/panels/__init__.py" "$ROOT/app/gui/panels/reconstruction_logic.py" "$RES/core/app/gui/panels/"
rsync -a "$ROOT/assets/locales" "$RES/core/assets/"
cp "$ROOT/LICENSE" "$RES/core/LICENSE"
find "$RES" -name '__pycache__' -type d -prune -exec rm -rf {} +

step "Smoke test the embedded core"
env -i HOME="$HOME" PATH="/usr/bin:/bin:/opt/homebrew/bin" PYTHONPATH="$RES/core" \
    CROWSPLAT_DATA_DIR="$OUT/smoke-data" "$PY" -I -c "
import sys; sys.path.insert(0, '$RES/core')
import app.bridge.jobs, app.bridge.probe, numpy, cv2, PIL, plyfile, trimesh
assert 'PySide6' not in sys.modules
print('core imports ok, python', sys.version.split()[0])"
rm -rf "$OUT/smoke-data"

step "Sign"
PY_ENT="$OUT/python.entitlements"
cat > "$PY_ENT" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>com.apple.security.cs.disable-library-validation</key><true/>
  <key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>
</dict></plist>
PLIST
# Inside out: every Mach-O in the runtime, then the interpreter, then the app.
find "$RES/python" -type f \( -name '*.so' -o -name '*.dylib' \) -print0 |
    xargs -0 -n 20 codesign --force --timestamp --options runtime --sign "$IDENTITY"
for exe in "$RES"/python/bin/*; do
    [ -L "$exe" ] && continue
    file "$exe" | grep -q 'Mach-O' || continue
    codesign --force --timestamp --options runtime --entitlements "$PY_ENT" --sign "$IDENTITY" "$exe"
done
codesign --force --timestamp --options runtime \
    --entitlements "$MAC/CrowSplat/CrowSplat.entitlements" --sign "$IDENTITY" "$APP"
codesign --verify --deep --strict --verbose=1 "$APP"

step "DMG"
DMG="$OUT/CrowSplat-$VERSION.dmg"
command -v create-dmg >/dev/null || brew install create-dmg
STAGE="$OUT/dmg"; rm -rf "$STAGE"; mkdir -p "$STAGE"; cp -R "$APP" "$STAGE/"
# Retina background: tiff with both scales.
tiffutil -cathidpicheck "$MAC/scripts/dmg-background.png" "$MAC/scripts/dmg-background@2x.png" \
    -out "$OUT/dmg-background.tiff" >/dev/null
create-dmg --volname "CrowSplat" --volicon "$RES/AppIcon.icns" \
    --background "$OUT/dmg-background.tiff" --window-size 660 400 --icon-size 112 \
    --icon "CrowSplat.app" 165 200 --app-drop-link 495 200 --hide-extension "CrowSplat.app" \
    --no-internet-enable "$DMG" "$STAGE" >/dev/null
codesign --force --timestamp --sign "$IDENTITY" "$DMG"

if [ "${NOTARIZE:-1}" = "1" ] && xcrun notarytool history --keychain-profile "$PROFILE" >/dev/null 2>&1; then
    step "Notarize"
    xcrun notarytool submit "$DMG" --keychain-profile "$PROFILE" --wait
    xcrun stapler staple "$DMG"
    spctl --assess --type open --context context:primary-signature -v "$DMG"
else
    echo "Notarization skipped (no notarytool profile \"$PROFILE\")."
fi

du -h "$DMG"
echo "$DMG"
