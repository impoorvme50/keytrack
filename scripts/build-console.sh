#!/bin/zsh
set -euo pipefail
cd "${0:A:h}/.."
project_dir="$PWD"
build_dir="$project_dir/dist/.build-console"
app_path="$build_dir/Keytrack.app"
if [[ "$(uname -m)" != arm64 ]]; then
  print -u2 '此构建脚本生成 Apple 芯片版本，请在 Apple 芯片 Mac 上运行。'
  exit 1
fi
if ! .venv/bin/python -m PyInstaller --version >/dev/null 2>&1; then
  print -u2 '构建工具缺失：请在项目虚拟环境中安装 pyinstaller==6.22.3。'
  exit 1
fi
mkdir -p "$build_dir" /private/tmp/keytrack-swift-cache
export PYINSTALLER_CONFIG_DIR="$build_dir/pyinstaller-cache"
print '正在打包应用内运行组件…'
if ! .venv/bin/python -m PyInstaller --noconfirm --clean --onedir \
    --name keytrack-helper --paths "$project_dir" --target-architecture arm64 \
    --exclude-module pynput --exclude-module _lzma --add-data "$project_dir/rime:rime" \
    --add-data "$project_dir/data/prediction:data/prediction" \
    --add-data "$project_dir/data/annotations:data/annotations" \
    --distpath "$build_dir/runtime" --workpath "$build_dir/work" --specpath "$build_dir" \
    scripts/frozen-entry.py > "$build_dir/runtime-build.log" 2>&1; then
  tail -60 "$build_dir/runtime-build.log"
  exit 1
fi
# Stage a fresh bundle; publish it only after successful signing and verification.
[[ ! -d "$app_path" ]] || mv "$app_path" "$build_dir/Keytrack.previous.$(date +%s).app"
mkdir -p "$app_path/Contents/MacOS" "$app_path/Contents/Resources" "$app_path/Contents/Resources"
cp -R "$build_dir/runtime/keytrack-helper" "$app_path/Contents/Resources/keytrack-runtime"
print '正在构建 SwiftUI 原生界面…'
xcrun swiftc -swift-version 5 -target arm64-apple-macosx26.0 \
    -module-cache-path /private/tmp/keytrack-swift-cache -O \
    macos/Keytrack.swift macos/ConsoleModel.swift -o "$app_path/Contents/MacOS/Keytrack" \
    -framework AppKit -framework SwiftUI
xcrun swiftc -module-cache-path /private/tmp/keytrack-swift-cache scripts/make-icon.swift -o "$build_dir/make-icon"
"$build_dir/make-icon" "$build_dir/Keytrack.iconset"
iconutil -c icns "$build_dir/Keytrack.iconset" -o "$app_path/Contents/Resources/Keytrack.icns"
.venv/bin/python scripts/bundle-notices.py "$app_path/Contents/Resources/ThirdPartyLicenses"
cp LICENSE "$app_path/Contents/Resources/LICENSE.txt"
cat > "$app_path/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict><key>CFBundleExecutable</key><string>Keytrack</string><key>CFBundleIdentifier</key><string>local.keytrack.console</string><key>CFBundleName</key><string>Keytrack</string><key>CFBundleDisplayName</key><string>Keytrack</string><key>CFBundleShortVersionString</key><string>0.4.4</string><key>CFBundleVersion</key><string>8</string><key>CFBundleIconFile</key><string>Keytrack</string><key>CFBundlePackageType</key><string>APPL</string><key>NSHighResolutionCapable</key><true/><key>LSMinimumSystemVersion</key><string>26.0</string><key>LSArchitecturePriority</key><array><string>arm64</string></array></dict></plist>
PLIST
codesign --force --sign - "$app_path"
codesign --verify --deep --strict "$app_path"
if [[ -d dist/Keytrack.app ]]; then
  mv dist/Keytrack.app "$build_dir/Keytrack.release.$(date +%s).app"
fi
mv "$app_path" dist/Keytrack.app
print "已构建：$project_dir/dist/Keytrack.app"
