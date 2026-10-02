#!/bin/zsh
set -euo pipefail
cd "${0:A:h}/.."
project_dir="$PWD"
app_path="$project_dir/dist/Keytrack.app"
[[ -d "$app_path" ]] || { print -u2 '请先运行 scripts/build-console.sh'; exit 1; }
codesign --verify --deep --strict "$app_path"
version=$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$app_path/Contents/Info.plist")
stage_dir=$(mktemp -d "$project_dir/dist/.dmg-stage.XXXXXX")
cp -R "$app_path" "$stage_dir/Keytrack.app"
cp LICENSE "$stage_dir/LICENSE.txt"
ln -s /Applications "$stage_dir/Applications"
cat > "$stage_dir/安装说明.txt" <<'TXT'
Keytrack 输入控制台
Apple 芯片 Mac · macOS 26 及以上

1. 将 Keytrack.app 拖入 Applications（应用程序）。
2. 从「应用程序」打开 Keytrack。
3. 点击窗口上方「完成本机安装」，再点「备份并安装」。

安装会备份原后台服务和输入法配置，再让后台采集使用应用内程序。
输入历史保留，AI 开关与已有模型服务保持当前设置。
应用自带运行组件，无需安装 Python、Homebrew，也不依赖源码目录。
输入法功能需要已经安装鼠须管；AI 建议继续使用已有的本机 Kev 模型。
退出窗口后采集可继续，登录时自动启动。

这是本机使用版，尚未进行 Apple Developer ID 签名和苹果公证。
配置与历史存放在个人目录，不会写入应用包。
TXT
image_path="$project_dir/dist/Keytrack-$version-apple-silicon.dmg"
if [[ -f "$image_path" ]]; then
  mv "$image_path" "$project_dir/dist/.Keytrack-$version-$(date +%s).dmg"
fi
hdiutil create -volname 'Keytrack' -srcfolder "$stage_dir" -format UDZO -ov "$image_path"
hdiutil verify "$image_path"
(
  cd "$project_dir/dist"
  shasum -a 256 "${image_path:t}"
) > "$image_path.sha256"
print "已生成安装包：$image_path"
