import AppKit
import SwiftUI

struct DesktopPetAppearance: Codable, Equatable {
    var coat: CatCoatTheme = .classicBlack
    var keyboard: KeyboardTheme = .classicMilk
    var furRGB: Int?
    var irisRGB: Int?
    var scale = 0.7
    var rotation = 0.0
    var mirrored = false
    var keyLegends = true

    static func load(_ data: Data?, previousCoat: String?) -> Self {
        if let data, var appearance = try? JSONDecoder().decode(Self.self, from: data) {
            appearance.normalize()
            return appearance
        }
        return Self(coat: previousCoat.flatMap(CatCoatTheme.init(rawValue:)) ?? .classicBlack)
    }

    mutating func normalize() {
        scale = scale.isFinite ? min(1.3, max(0.45, scale)) : 0.7
        rotation = rotation.isFinite ? min(30, max(-30, rotation)) : 0
        furRGB = furRGB.flatMap { (0...0xFFFFFF).contains($0) ? $0 : nil }
        irisRGB = irisRGB.flatMap { (0...0xFFFFFF).contains($0) ? $0 : nil }
    }

    var skin: SkinSpec {
        var skin = SkinSpec.builtIn(coat)
        if let furRGB {
            let original = skin.palette.body
            let color = SkinColor.hex(furRGB)
            skin.palette.body = color
            if skin.palette.headBody == original { skin.palette.headBody = color }
            if skin.palette.legs == original { skin.palette.legs = color }
            if skin.palette.paws == original { skin.palette.paws = color }
            if skin.palette.earOuter == original { skin.palette.earOuter = color }
            if skin.palette.tail == original { skin.palette.tail = color }
        }
        if let irisRGB {
            let color = SkinColor.hex(irisRGB)
            skin.palette.iris = color
            skin.palette.irisLeft = color
            skin.palette.irisRight = color
        }
        return skin
    }
}

struct DesktopPetAppearanceView: View {
    @ObservedObject var pet: DesktopPet

    var body: some View {
        Form {
            Toggle("显示桌宠", isOn: Binding(get: { pet.isEnabled }, set: pet.setEnabled))
            Section("外观") {
                Picker("皮肤", selection: setting(\.coat)) {
                    ForEach(CatCoatTheme.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                }
                customColor("毛色", value: \.furRGB, base: SkinSpec.builtIn(pet.appearance.coat).palette.body.ns)
                customColor("瞳色", value: \.irisRGB, base: Color(.sRGB, red: 0.79, green: 0.95, blue: 0.25))
                Picker("键盘配色", selection: setting(\.keyboard)) {
                    ForEach(KeyboardTheme.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                }
                LabeledContent("大小") {
                    Slider(value: setting(\.scale), in: 0.45...1.3, step: 0.01) { Text("大小") }.labelsHidden()
                    Text("\(Int((pet.appearance.scale / 0.7 * 100).rounded()))%")
                        .monospacedDigit().frame(width: 46, alignment: .trailing)
                }
                LabeledContent("旋转") {
                    Slider(value: setting(\.rotation), in: -30...30, step: 1) { Text("旋转") }.labelsHidden()
                    Text("\(Int(pet.appearance.rotation))°")
                        .monospacedDigit().frame(width: 46, alignment: .trailing)
                }
                Toggle("左右镜像", isOn: setting(\.mirrored))
                Button("恢复默认外观") { pet.setAppearance(DesktopPetAppearance()) }
            }
            Section("按键显示") {
                Toggle("显示键帽字样", isOn: setting(\.keyLegends))
                Toggle("在其他 App 也显示实际键位", isOn: Binding(get: { pet.wantsGlobalKeys }, set: pet.setGlobalKeys))
                if !pet.isEnabled {
                    Text("显示桌宠后可查看按键反馈。").foregroundStyle(.secondary)
                } else if pet.wantsGlobalKeys && !pet.globalKeysActive {
                    Text("请在「隐私与安全性 → 输入监控」中允许 Keytrack。授权后如仍未生效，请重新打开 Keytrack。")
                        .foregroundStyle(.secondary)
                    Button("打开输入监控设置", action: pet.openInputMonitoring)
                } else {
                    Text(pet.globalKeysActive ? "已启用跨应用键位显示。" : "Keytrack 窗口内显示实际键位，其他 App 使用通用动画。")
                        .foregroundStyle(.secondary)
                }
            }
        }
        .formStyle(.grouped)
        .frame(width: 480, height: 630)
    }

    private func setting<Value>(_ field: WritableKeyPath<DesktopPetAppearance, Value>) -> Binding<Value> {
        Binding(get: { pet.appearance[keyPath: field] }, set: { value in
            var appearance = pet.appearance
            appearance[keyPath: field] = value
            pet.setAppearance(appearance)
        })
    }

    private func customColor(_ title: String, value: WritableKeyPath<DesktopPetAppearance, Int?>, base: NSColor) -> some View {
        customColor(title, value: value, base: Color(nsColor: base))
    }

    private func customColor(_ title: String, value: WritableKeyPath<DesktopPetAppearance, Int?>, base: Color) -> some View {
        HStack {
            ColorPicker(title, selection: Binding(get: {
                pet.appearance[keyPath: value].map { Color(nsColor: SkinColor.hex($0).ns) } ?? base
            }, set: { color in
                guard let rgb = NSColor(color).usingColorSpace(.sRGB) else { return }
                func byte(_ component: CGFloat) -> Int {
                    Int((min(1, max(0, component)) * 255).rounded())
                }
                let red = byte(rgb.redComponent)
                let green = byte(rgb.greenComponent)
                let blue = byte(rgb.blueComponent)
                setting(value).wrappedValue = red << 16 | green << 8 | blue
            }), supportsOpacity: false)
            Button("还原") { setting(value).wrappedValue = nil }
                .disabled(pet.appearance[keyPath: value] == nil)
        }
    }
}
