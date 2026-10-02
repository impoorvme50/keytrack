import AppKit
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) { NativeBridge.shared.stop() }
}

@main struct KeytrackApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = ConsoleModel()
    var body: some Scene {
        WindowGroup(CommandLine.arguments.contains("--demo") ? "Keytrack · 原生演示" : "Keytrack · 输入控制台") {
            ConsoleView().environmentObject(model).frame(minWidth: 860, minHeight: 620)
        }
        .defaultSize(width: 1190, height: 820)
        .commands {
            CommandGroup(replacing: .newItem) {}
            CommandGroup(after: .toolbar) {
                Button("刷新数据") { model.load() }.keyboardShortcut("r")
            }
        }
    }
}

private let accent = Color(red: 0.06, green: 0.46, blue: 0.43)
private let pageBackground = Color(nsColor: .windowBackgroundColor)

struct ConsoleView: View {
    @EnvironmentObject var model: ConsoleModel
    @State private var confirmInstallation = false
    var body: some View {
        NavigationSplitView {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 10) {
                    Image(systemName: "keyboard.fill").font(.title2).foregroundStyle(accent)
                    VStack(alignment: .leading) { Text("Keytrack").font(.title3.bold()); Text("输入控制台").font(.caption).foregroundStyle(.secondary) }
                }.padding(20)
                List(selection: Binding(get: { model.screen }, set: { model.select($0) })) {
                    Section("我的输入") {
                        ForEach([Screen.dashboard, .phrases]) { screen in Label(screen.title, systemImage: screen.icon).tag(screen) }
                    }
                    Section("偏好设置") {
                        ForEach([Screen.appearance, .settings, .backups]) { screen in Label(screen.title, systemImage: screen.icon).tag(screen) }
                    }
                }.listStyle(.sidebar)
                VStack(alignment: .leading, spacing: 7) {
                    Label("仅在本机", systemImage: "lock.shield").foregroundStyle(accent)
                    Text("SwiftUI 原生界面").foregroundStyle(.secondary)
                    if let state = model.state {
                        Text(state.status.demo ? "演示数据 · 本机配置未改动" : "采集\(state.status.recorder.running ? "运行中" : "未运行") · Kev \(state.status.kev_enabled ? "开启" : "关闭")")
                            .foregroundStyle(.secondary)
                    }
                }.font(.caption).padding(20)
            }.navigationSplitViewColumnWidth(min: 190, ideal: 218, max: 260)
        } detail: {
            VStack(spacing: 0) {
                if let installation = model.state?.installation, installation.packaged && !installation.configured {
                    HStack(spacing: 12) {
                        Image(systemName: "shippingbox")
                        Text(installation.can_install ? "完成一次本机安装，让后台采集使用应用内程序。" : "请先将 Keytrack 拖入「应用程序」，再打开完成安装。")
                        Spacer()
                        if installation.can_install {
                            Button("完成本机安装") { confirmInstallation = true }.buttonStyle(.borderedProminent)
                        }
                    }.font(.callout).padding(12).background(accent.opacity(0.10))
                    .confirmationDialog("完成本机安装", isPresented: $confirmInstallation, titleVisibility: .visible) {
                        Button("备份并安装") { model.action("install") }
                        Button("取消", role: .cancel) {}
                    } message: {
                        Text("先备份输入法配置和原后台服务，再切换到应用内程序。输入历史保留，AI 开关与模型服务保持当前设置。")
                    }
                }
                if model.state?.status.demo == true {
                    Label("演示模式 · 所有保存操作只修改自造测试数据", systemImage: "info.circle")
                        .font(.caption).frame(maxWidth: .infinity, alignment: .leading).padding(12)
                        .background(Color.orange.opacity(0.10))
                }
                if model.state == nil {
                    VStack(spacing: 14) { ProgressView(); Text("正在读取本机数据…").foregroundStyle(.secondary) }.frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 22) {
                            switch model.screen {
                            case .dashboard: DashboardView()
                            case .phrases: PhrasesView()
                            case .appearance: AppearanceView()
                            case .settings: InputSettingsView()
                            case .backups: BackupsView()
                            }
                        }.padding(28).frame(maxWidth: 1250, alignment: .leading).frame(maxWidth: .infinity)
                    }.background(pageBackground)
                }
                if !model.notice.isEmpty {
                    HStack { Image(systemName: "checkmark.circle"); Text(model.notice); Spacer(); Button { model.notice = "" } label: { Image(systemName: "xmark") }.buttonStyle(.plain) }
                        .font(.caption).padding(12).background(accent.opacity(0.1))
                }
            }.navigationTitle(model.screen.title)
                .toolbar {
                    ToolbarItemGroup {
                        if model.busy { ProgressView().controlSize(.small) }
                        if model.state?.deployment.pending == true { Label("等待部署", systemImage: "clock").font(.caption).foregroundStyle(.orange) }
                        if model.dirty {
                            Button("放弃修改") { model.discard() }
                            Button("保存并应用") { model.save() }.buttonStyle(.borderedProminent)
                        }
                        Button { model.load() } label: { Label("刷新", systemImage: "arrow.clockwise") }.help("刷新本机数据")
                    }
                }
        }
        .tint(accent)
        .disabled(model.busy)
        .task { if model.state == nil { model.load() } }
        .alert("操作未完成", isPresented: Binding(get: { model.error != nil }, set: { if !$0 { model.error = nil } })) {
            Button("好") { model.error = nil }
        } message: { Text(model.error ?? "") }
    }
}

struct Panel<Content: View>: View {
    var title: String
    var caption: String = ""
    @ViewBuilder var content: () -> Content
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack { Text(title).font(.headline); Spacer(); if !caption.isEmpty { Text(caption).font(.caption).foregroundStyle(.secondary) } }
            content()
        }.padding(20).frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.primary.opacity(0.05)))
    }
}
struct PageHeading: View {
    var title: String; var detail: String
    var body: some View { VStack(alignment: .leading, spacing: 8) { Text(title).font(.system(size: 26, weight: .semibold)); Text(detail).font(.callout).foregroundStyle(.secondary) } }
}
struct Metric: View {
    var label: String; var value: String; var unit: String; var note: String; var icon: String
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack { Text(label).foregroundStyle(.secondary); Spacer(); Image(systemName: icon).foregroundStyle(accent) }.font(.caption)
            HStack(alignment: .firstTextBaseline, spacing: 4) { Text(value).font(.system(size: 30, weight: .semibold, design: .rounded)); Text(unit).font(.caption).foregroundStyle(.secondary) }
            Text(note).font(.caption2).foregroundStyle(.secondary)
        }.frame(maxWidth: .infinity, alignment: .leading).padding(18)
            .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 12))
    }
}
struct DashboardView: View {
    @EnvironmentObject var model: ConsoleModel
    var body: some View {
        if let report = model.report {
            HStack {
                PageHeading(title: "你的输入，一目了然。", detail: "回看输入节奏，找到更舒服的工作习惯。")
                Spacer()
                Button("今天") { model.changeDate(Date()) }
                DatePicker("日期", selection: Binding(get: { model.selectedDate }, set: { model.changeDate($0) }), displayedComponents: .date).labelsHidden().frame(width: 125)
            }
            Panel(title: report.key_quality.reliable ? "采集范围" : "按键统计待完善", caption: "") {
                Text(report.key_quality.message).font(.callout)
                Text(report.key_quality.scope).font(.caption).foregroundStyle(.secondary)
                if let since = report.key_quality.first_verified_minute {
                    Text("修复后采集始于 \(since.replacingOccurrences(of: "T", with: " "))；更早的漏采无法补回。").font(.caption).foregroundStyle(.secondary)
                }
            }
            LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 4), spacing: 14) {
                Metric(label: "上屏文字", value: report.total_chars.formatted(), unit: "字", note: "\(report.segment_count) 个输入片段", icon: "pencil")
                Metric(label: "输入速度", value: report.cpm.map { String(format: "%.1f", $0) } ?? "—", unit: "字 / 分", note: "按活跃分钟计算", icon: "arrow.up.right")
                Metric(label: "活跃时间", value: report.active_minutes.map { $0.formatted() } ?? "—", unit: "分钟", note: "有按键记录的分钟数", icon: "clock")
                Metric(label: "退格占比", value: report.correction_rate.map { String(format: "%.1f", $0) } ?? "—", unit: "%", note: "\(report.total_keys.formatted()) 次按键", icon: "delete.left")
            }
            HStack(alignment: .top, spacing: 18) {
                Panel(title: "最近两周", caption: "点击查看当天") {
                    HStack(alignment: .bottom, spacing: 7) {
                        ForEach(report.trend) { item in
                            VStack(spacing: 8) {
                                Button { if let date = ConsoleModel.dayFormat.date(from: item.day) { model.changeDate(date) } } label: {
                                    RoundedRectangle(cornerRadius: 4).fill(accent.opacity(item.day == report.day ? 1 : 0.35))
                                        .frame(height: max(3, Double(item.chars) / Double(max(1, report.trend.map(\.chars).max() ?? 1)) * 108))
                                        .frame(maxHeight: 108, alignment: .bottom)
                                }.buttonStyle(.plain).help("\(item.day) · \(item.chars) 字").accessibilityLabel("\(item.day) \(item.chars) 字")
                                Text(String(item.day.suffix(5))).font(.system(size: 9)).foregroundStyle(.secondary)
                            }
                        }
                    }.frame(height: 130)
                    Text("输入法上屏记录，不包含粘贴和其他输入法的文字。").font(.caption2).foregroundStyle(.secondary)
                }.frame(maxWidth: .infinity)
                Panel(title: "在哪里输入", caption: report.day) {
                    if report.apps.isEmpty { Text("这一天还没有输入记录").foregroundStyle(.secondary) }
                    ForEach(Array(report.apps.prefix(6))) { app in
                        VStack(spacing: 5) {
                            HStack { Text(app.name); Spacer(); Text("\(app.chars.formatted()) 字").foregroundStyle(.secondary) }.font(.caption)
                            ProgressView(value: Double(app.chars), total: Double(max(1, report.apps.first?.chars ?? 1))).tint(accent)
                        }
                    }
                }.frame(width: 280)
            }
            HStack(alignment: .top, spacing: 18) {
                Panel(title: "输入日历", caption: "最近 91 天") {
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 6), count: 13), spacing: 6) {
                        ForEach(report.calendar) { item in
                            Button { if let date = ConsoleModel.dayFormat.date(from: item.day) { model.changeDate(date) } } label: {
                                RoundedRectangle(cornerRadius: 3).fill(accent.opacity(item.chars == 0 ? 0.06 : 0.16 + 0.7 * sqrt(Double(item.chars) / Double(max(1, report.calendar.map(\.chars).max() ?? 1))))).frame(height: 17)
                            }.buttonStyle(.plain).help("\(item.day) · \(item.chars) 字").accessibilityLabel("\(item.day) \(item.chars) 字")
                        }
                    }
                }
                Panel(title: "一天的节奏", caption: "每小时的按键次数") {
                    if report.hours.isEmpty { Text(report.key_quality.message).font(.caption).foregroundStyle(.secondary) }
                    HStack(alignment: .bottom, spacing: 4) {
                        ForEach(report.hours.indices, id: \.self) { hour in
                            VStack(spacing: 6) {
                                RoundedRectangle(cornerRadius: 3).fill(accent.opacity(0.4)).frame(height: max(3, Double(report.hours[hour]) / Double(max(1, report.hours.max() ?? 1)) * 83)).frame(maxHeight: 83, alignment: .bottom)
                                Text(hour % 6 == 0 ? "\(hour)时" : " ").font(.system(size: 8)).foregroundStyle(.secondary)
                            }.help("\(hour):00 · \(report.hours[hour]) 次")
                        }
                    }.frame(height: 105)
                }
            }
            Panel(title: "键盘热力图", caption: "已映射 \(report.key_quality.mapped_keys) 次 · 布局外 \(report.key_quality.unmapped_keys) 次") {
                KeyboardHeatmap(report: report)
                Text(report.key_quality.reliable ? "ANSI 布局 · 悬停查看次数" : "仅展示已收到的按键；浅色不代表没有按过。").font(.caption).foregroundStyle(.secondary)
            }
            Panel(title: "按标准指法估算的按键分布", caption: "仅以布局内的按键为分母") {
                if report.fingers.isEmpty || report.key_quality.mapped_keys == 0 {
                    Text(report.key_quality.reliable ? "没有可映射到键盘布局的按键" : report.key_quality.message).font(.caption).foregroundStyle(.secondary)
                }
                LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 9), spacing: 8) {
                    ForEach(report.fingers) { finger in
                        VStack(spacing: 7) {
                            Text(finger.name).font(.system(size: 10)).foregroundStyle(.secondary)
                            Text(String(format: "%.1f%%", Double(finger.count) / Double(max(1, report.fingers.map(\.count).reduce(0, +))) * 100)).font(.system(size: 17, weight: .medium, design: .rounded))
                        }.frame(maxWidth: .infinity).padding(.vertical, 12).background(accent.opacity(0.06), in: RoundedRectangle(cornerRadius: 8))
                    }
                }
            }
            Panel(title: "当天输入回看", caption: "默认折叠") {
                HStack { Text("主动展开后，才读取当天原文。").font(.caption).foregroundStyle(.secondary); Spacer(); Button(model.showText ? "收起原文" : "展开输入原文") { model.toggleText() } }
                if model.showText {
                    if report.segment_count > report.segment_limit { Text("仅显示最近 \(report.segment_limit) 个片段。").font(.caption).foregroundStyle(.secondary) }
                    ForEach(Array((report.segments ?? []).enumerated()), id: \.offset) { _, item in
                        VStack(alignment: .leading, spacing: 8) {
                            Text("\(item.time) · \(item.app)").font(.caption).foregroundStyle(.secondary)
                            Text(item.text).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                            Divider()
                        }
                    }
                    if (report.segments ?? []).isEmpty { Text("这一天没有上屏文字").foregroundStyle(.secondary) }
                }
            }
        }
    }
}
struct KeyboardHeatmap: View {
    var report: Report
    var body: some View {
        GeometryReader { geometry in
            VStack(spacing: 6) {
                ForEach(report.keyboard.indices, id: \.self) { row in
                    let keys = report.keyboard[row]
                    let units = keys.map(\.width).reduce(0, +)
                    HStack(spacing: 5) {
                        ForEach(keys.indices, id: \.self) { index in
                            let key = keys[index], count = report.key_frequency[key.key] ?? 0
                            Text(key.label.isEmpty ? "空格" : key.label).font(.system(size: 11))
                                .frame(width: max(1, (geometry.size.width - Double(keys.count - 1) * 5) * key.width / units), height: 31)
                                .background(accent.opacity(count == 0 ? 0.06 : 0.12 + 0.65 * sqrt(Double(count) / Double(max(1, report.key_frequency.values.max() ?? 1)))), in: RoundedRectangle(cornerRadius: 5))
                                .help("\(key.key) · \(count.formatted()) 次")
                        }
                    }
                }
            }
        }.frame(height: CGFloat(report.keyboard.count * 37))
    }
}

struct PhrasesView: View {
    @EnvironmentObject var model: ConsoleModel
    @State private var query = ""
    @State private var category = ""
    @State private var editor: Phrase?
    @State private var originalCode: String?
    var categories: [String] { Array(Set(model.phrases.map(\.category))).sorted() }
    var filtered: [Phrase] { model.phrases.filter { (category.isEmpty || $0.category == category) && (query.isEmpty || ($0.code + $0.category + $0.text).localizedCaseInsensitiveContains(query)) } }
    var body: some View {
        HStack { PageHeading(title: "把重复输入，变成一个短编码。", detail: "常用回复、签名和地址，按分类整理。"); Spacer(); Button { originalCode = nil; editor = Phrase(code: "", category: "常用语", text: "") } label: { Label("添加", systemImage: "plus") } }
        Text("输入完整短编码后，用空格上屏。支持多行内容。").font(.caption).foregroundStyle(.secondary)
        HStack {
            TextField("搜索内容、分类或编码", text: $query).textFieldStyle(.roundedBorder)
            Picker("分类", selection: $category) { Text("所有分类").tag(""); ForEach(categories, id: \.self) { Text($0).tag($0) } }.frame(width: 180)
        }
        if filtered.isEmpty { Panel(title: model.phrases.isEmpty ? "添加第一条常用语" : "没有匹配的常用语") { Text("保存并应用后，短编码会接入雾凇拼音。").foregroundStyle(.secondary) } }
        ForEach(filtered) { item in
            Panel(title: item.category, caption: item.code) {
                Text(item.text).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                HStack {
                    Spacer()
                    Button("复制") { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(item.text, forType: .string); model.notice = "已复制常用语" }
                    Button("编辑") { originalCode = item.code; editor = item }
                    Button("移出列表", role: .destructive) { model.phrases.removeAll { $0.code == item.code } }
                }
            }
        }
        .sheet(item: $editor) { item in PhraseEditor(initial: item, originalCode: originalCode).environmentObject(model) }
    }
}
struct PhraseEditor: View {
    @EnvironmentObject var model: ConsoleModel
    @Environment(\.dismiss) var dismiss
    @State var phrase: Phrase
    var originalCode: String?
    @State private var error = ""
    init(initial: Phrase, originalCode: String?) { _phrase = State(initialValue: initial); self.originalCode = originalCode }
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text(originalCode == nil ? "添加常用语" : "编辑常用语").font(.title2.bold())
            Form {
                TextField("分类", text: $phrase.category)
                TextField("短编码", text: $phrase.code)
            }
            Text("2–20 位小写字母，避开 v、u 开头。").font(.caption).foregroundStyle(.secondary)
            Text("内容").font(.headline)
            TextEditor(text: $phrase.text).font(.body).frame(height: 170).border(Color.secondary.opacity(0.2)).accessibilityLabel("常用语内容")
            if !error.isEmpty { Text(error).font(.caption).foregroundStyle(.red) }
            HStack { Spacer(); Button("取消") { dismiss() }.keyboardShortcut(.cancelAction); Button("加入列表") { submit() }.keyboardShortcut(.defaultAction).buttonStyle(.borderedProminent) }
        }.padding(28).frame(width: 500)
    }
    func submit() {
        phrase.code = phrase.code.trimmingCharacters(in: .whitespacesAndNewlines)
        phrase.category = phrase.category.trimmingCharacters(in: .whitespacesAndNewlines)
        guard phrase.code.range(of: "^[a-z]{2,20}$", options: .regularExpression) != nil, !["u", "v"].contains(String(phrase.code.prefix(1))) else { error = "请填写 2–20 位小写字母编码，避开 v、u 开头。"; return }
        guard !phrase.category.isEmpty, phrase.category.count <= 18, !phrase.text.isEmpty, phrase.text.count <= 2000 else { error = "分类需 1–18 字，内容需 1–2000 字。"; return }
        guard !model.phrases.contains(where: { $0.code == phrase.code && $0.code != originalCode }) else { error = "短编码已被使用。"; return }
        if let code = originalCode, let index = model.phrases.firstIndex(where: { $0.code == code }) { model.phrases[index] = phrase } else { model.phrases.append(phrase) }
        dismiss()
    }
}

struct AppearanceView: View {
    @EnvironmentObject var model: ConsoleModel
    @State private var dark = false
    @State private var fontSearch = ""
    var themes: [AppearanceTheme] { model.state?.appearance_themes ?? AppearanceTheme.legacy }
    var selectedTheme: AppearanceTheme? { themes.first { $0.id == model.preferences.theme } }
    private var palette: AppearancePalette { AppearancePalette(colors: dark ? (selectedTheme?.dark ?? [:]) : (selectedTheme?.light ?? [:]), dark: dark) }
    var candidateSpacing: CGFloat { model.preferences.density == "compact" ? 4 : 8 }
    var baseline: FontAppearance? {
        guard let original = model.state?.appearance_baseline else { return nil }
        return model.preferences.theme == "existing" ? (dark ? original.dark : original.light) : original.style
    }
    var fontFace: String {
        switch model.preferences.font_mode {
        case "custom": return model.preferences.font_face
        case "system": return ""
        default: return baseline?.font_face ?? ""
        }
    }
    var inlinePreedit: Bool {
        switch model.preferences.preedit_mode {
        case "inline": return true
        case "candidate": return false
        default: return baseline?.inline_preedit ?? true
        }
    }
    var missingFonts: [String] { CandidateFonts.faces(fontFace).filter { CandidateFonts.resolve($0, size: 15) == nil } }
    var fontMatches: [InstalledFont] { CandidateFonts.installed.filter { $0.matches(fontSearch.trimmingCharacters(in: .whitespacesAndNewlines)) } }
    func previewFont(_ size: Int) -> Font { Font(CandidateFonts.preview(fontFace, size: CGFloat(size))) }
    var body: some View {
        PageHeading(title: "让候选窗更顺眼。", detail: "调整字体、布局与配色，保存前先看效果。")
        Panel(title: "候选窗预览", caption: selectedTheme == nil ? "仅布局示意 · 原有配色未读取" : "实际由鼠须管绘制") {
            Toggle("深色预览", isOn: $dark).toggleStyle(.switch).frame(maxWidth: .infinity, alignment: .trailing)
            if inlinePreedit {
                HStack(spacing: 7) {
                    Text("正在输入").foregroundStyle(.secondary)
                    Text("ni hao").font(previewFont(model.preferences.font_size)).underline()
                    Spacer()
                    Text("应用内行内拼音示意").font(.caption).foregroundStyle(.secondary)
                }.padding(10).background(Color.secondary.opacity(0.06), in: RoundedRectangle(cornerRadius: 6))
            }
            VStack(alignment: .leading, spacing: candidateSpacing) {
                if !inlinePreedit { Text("ni hao").font(previewFont(model.preferences.font_size)).foregroundStyle(palette.color("text_color")) }
                if model.preferences.layout == "vertical" {
                    VStack(alignment: .leading, spacing: candidateSpacing) { candidates }
                } else {
                    ScrollView(.horizontal, showsIndicators: false) { HStack(spacing: candidateSpacing) { candidates } }
                }
            }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
                .background(palette.color("back_color"), in: RoundedRectangle(cornerRadius: 10))
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(palette.color("border_color")))
                .accessibilityElement(children: .combine)
                .accessibilityLabel("\(dark ? "深色" : "浅色")候选窗预览，\(selectedTheme?.name ?? "原有配色未读取")，\(model.preferences.layout == "vertical" ? "竖排" : "横排")，字体 \(fontFace.isEmpty ? "系统默认" : fontFace)，\(inlinePreedit ? "行内拼音" : "候选窗拼音")，候选字号 \(model.preferences.font_size)，注释字号 \(model.preferences.comment_size)")
            Text("行内拼音由正在输入的应用绘制，可能使用应用自己的字体；候选字体与实际布局以鼠须管候选窗为准。").font(.caption).foregroundStyle(.secondary)
        }
        Panel(title: "配色方案") {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 172, maximum: 260), spacing: 12)], alignment: .leading, spacing: 12) {
                ForEach([AppearanceTheme.existing] + themes) { theme in
                    AppearanceThemeCard(theme: theme, selected: model.preferences.theme == theme.id) { model.preferences.theme = theme.id }
                }
            }
            Text("选择只更新预览，点击“保存并应用”后生效。新方案随系统切换浅色与深色。“保留当前”恢复首次保存前的原有配色，预览只展示布局。").font(.caption).foregroundStyle(.secondary)
        }
        Panel(title: "候选字体", caption: "编号与注释跟随") {
            Picker("字体设置", selection: $model.preferences.font_mode) {
                Text("保留原字体").tag("existing")
                Text("系统默认").tag("system")
                Text("自选字体").tag("custom")
            }.pickerStyle(.segmented)
                .onChange(of: model.preferences.font_mode) { _, value in
                    if value == "custom" && model.preferences.font_face.isEmpty {
                        model.preferences.font_face = CandidateFonts.installed.first(where: { $0.name == "PingFangSC-Regular" })?.name ?? CandidateFonts.installed.first?.name ?? "Helvetica"
                    }
                }
            HStack {
                Text(fontFace.isEmpty ? "系统默认字体" : fontFace).textSelection(.enabled)
                Spacer()
                Text("你好 · Keytrack 123").font(previewFont(18))
            }
            if !missingFonts.isEmpty {
                Label("预览未找到：\(missingFonts.joined(separator: "、"))。使用其余已安装字体或系统回退。", systemImage: "exclamationmark.triangle")
                    .font(.caption).foregroundStyle(.orange)
            }
            TextField("搜索字体名称", text: $fontSearch).textFieldStyle(.roundedBorder)
                .accessibilityLabel("搜索已安装字体")
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 2) {
                    ForEach(fontMatches) { item in
                        Button {
                            model.preferences.font_face = item.name
                            model.preferences.font_mode = "custom"
                        } label: {
                            HStack {
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(item.displayName).font(Font(item.sample)).lineLimit(1)
                                    Text(item.name).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                                }
                                Spacer()
                                Text("你好 Aa 123").font(Font(item.sample))
                                Image(systemName: model.preferences.font_mode == "custom" && model.preferences.font_face == item.name ? "checkmark.circle.fill" : "circle")
                                    .foregroundStyle(accent)
                            }.padding(.horizontal, 9).padding(.vertical, 7)
                                .contentShape(Rectangle())
                        }.buttonStyle(.plain)
                            .accessibilityLabel("字体 \(item.displayName)，\(item.name)")
                            .accessibilityValue(model.preferences.font_mode == "custom" && model.preferences.font_face == item.name ? "已选中" : "未选中")
                    }
                    if fontMatches.isEmpty { Text("没有匹配的已安装字体").foregroundStyle(.secondary).padding(10) }
                }
            }.frame(height: 190)
            Text("共 \(CandidateFonts.installed.count) 款已安装字体，匹配 \(fontMatches.count) 款。选择只更新预览；保留原字体可恢复保存前的设置。").font(.caption).foregroundStyle(.secondary)
        }
        Panel(title: "字号与布局") {
            Form {
                Stepper("候选字号：\(model.preferences.font_size) pt", value: $model.preferences.font_size, in: 12...28)
                Stepper("注释字号：\(model.preferences.comment_size) pt", value: $model.preferences.comment_size, in: 10...24)
                Picker("排列方向", selection: $model.preferences.layout) { Text("横排").tag("horizontal"); Text("竖排").tag("vertical") }
                Picker("候选间距", selection: $model.preferences.density) { Text("舒适").tag("comfortable"); Text("紧凑").tag("compact") }
                Picker("拼音显示", selection: $model.preferences.preedit_mode) {
                    Text("保留原设置").tag("existing"); Text("行内").tag("inline"); Text("候选窗").tag("candidate")
                }
            }.formStyle(.grouped)
        }
    }
    @ViewBuilder var candidates: some View {
        ForEach(Array(["你好", "拟好", "你号", "你"].enumerated()), id: \.offset) { index, word in
            HStack(spacing: 8) {
                Text("\(index + 1)").font(previewFont(max(11, model.preferences.font_size - 3)))
                    .foregroundStyle(palette.color(index == 0 ? "hilited_label_color" : "label_color"))
                Text(word).font(previewFont(model.preferences.font_size))
                    .foregroundStyle(palette.color(index == 0 ? "hilited_candidate_text_color" : "candidate_text_color"))
                Text(index == 0 ? "✦ AI" : (index == 1 ? "同音" : ""))
                    .font(previewFont(model.preferences.comment_size))
                    .foregroundStyle(palette.color(index == 0 ? "hilited_comment_text_color" : "comment_text_color"))
            }.padding(model.preferences.density == "compact" ? 7 : 11)
                .fixedSize()
                .background(index == 0 ? palette.color("hilited_candidate_back_color") : Color.clear, in: RoundedRectangle(cornerRadius: 6))
        }
    }
}

private struct AppearancePalette {
    var colors: [String: String]
    var dark: Bool
    func color(_ key: String) -> Color {
        if let hex = colors[key], hex.count == 7, hex.first == "#", let rgb = UInt32(hex.dropFirst(), radix: 16) {
            return Color(red: Double((rgb >> 16) & 255) / 255, green: Double((rgb >> 8) & 255) / 255, blue: Double(rgb & 255) / 255)
        }
        // The original user palette may be defined outside the managed config.
        // Its clearly labelled layout-only preview uses neutral colors.
        switch key {
        case "back_color": return dark ? Color(white: 0.13) : Color(white: 0.97)
        case "border_color": return dark ? Color(white: 0.30) : Color(white: 0.86)
        case "hilited_candidate_back_color": return dark ? Color(white: 0.72) : Color(white: 0.30)
        case "hilited_candidate_text_color", "hilited_comment_text_color", "hilited_label_color": return dark ? .black : .white
        case "comment_text_color", "label_color": return dark ? Color(white: 0.72) : Color(white: 0.42)
        default: return dark ? Color(white: 0.94) : Color(white: 0.12)
        }
    }
}

private struct AppearanceThemeCard: View {
    var theme: AppearanceTheme
    var selected: Bool
    var choose: () -> Void
    var body: some View {
        Button(action: choose) {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text(theme.name).font(.callout.weight(.semibold))
                    Spacer(minLength: 4)
                    Image(systemName: selected ? "checkmark.circle.fill" : "circle").foregroundStyle(selected ? accent : Color.secondary.opacity(0.4))
                }
                Text(theme.description).font(.caption).foregroundStyle(.secondary).lineLimit(2).frame(minHeight: 30, alignment: .topLeading)
                HStack(spacing: 8) {
                    sample(theme.light, dark: false)
                    sample(theme.dark, dark: true)
                }
            }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
                .background(selected ? accent.opacity(0.06) : Color.primary.opacity(0.02), in: RoundedRectangle(cornerRadius: 10))
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(selected ? accent : Color.primary.opacity(0.12), lineWidth: selected ? 2 : 1))
                .contentShape(RoundedRectangle(cornerRadius: 10))
        }.buttonStyle(.plain)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("\(theme.name)，\(theme.description)，\(theme.id == "existing" ? "原有配色未读取" : "提供浅色和深色配色")")
            .accessibilityValue(selected ? "已选中" : "未选中")
            .accessibilityAddTraits(selected ? .isSelected : [])
            .accessibilityHint("选择后可在上方预览，保存并应用后生效")
    }
    func sample(_ colors: [String: String], dark: Bool) -> some View {
        let palette = AppearancePalette(colors: colors, dark: dark)
        return VStack(alignment: .leading, spacing: 4) {
            Text(dark ? "深色" : "浅色").font(.system(size: 9)).foregroundStyle(palette.color("comment_text_color"))
            HStack(spacing: 5) {
                HStack(spacing: 3) {
                    Text("1").font(.system(size: 9)).foregroundStyle(palette.color("hilited_label_color"))
                    Text("你").font(.system(size: 12)).foregroundStyle(palette.color("hilited_candidate_text_color"))
                }.padding(.horizontal, 4).padding(.vertical, 3).background(palette.color("hilited_candidate_back_color"), in: RoundedRectangle(cornerRadius: 3))
                Text("好").font(.system(size: 12)).foregroundStyle(palette.color("candidate_text_color"))
            }
        }.padding(7).frame(maxWidth: .infinity, alignment: .leading)
            .background(palette.color("back_color"), in: RoundedRectangle(cornerRadius: 6))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(palette.color("border_color")))
    }
}
struct InputSettingsView: View {
    @EnvironmentObject var model: ConsoleModel
    var body: some View {
        PageHeading(title: "输入习惯，由你决定。", detail: "本地联想与 Kev 候选建议分别控制，日常输入继续交给鼠须管。")
        Panel(title: "本地接词联想", caption: "实验版 · 默认关闭") {
            if model.state?.prediction.installed == false {
                HStack {
                    Text("先安装独立测试方案，原“雾凇拼音”方案继续保留。").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button("安装联想实验方案") { model.action("prediction_install") }.buttonStyle(.borderedProminent)
                }
            }
            Toggle("开启本地接词联想", isOn: Binding(get: { model.state?.prediction.enabled ?? false }, set: { model.updatePrediction(enabled: $0) })).toggleStyle(.switch)
                .disabled(model.state?.prediction.installed != true)
            Text("先切换到“\(model.state?.prediction.schema_name ?? "雾凇拼音 · 接词实验")”方案。上屏后显示带“联想”标记的接词，不等待模型推理。").font(.caption).foregroundStyle(.secondary)
            Stepper("联想候选：\(model.state?.prediction.max_candidates ?? 3) 个", value: Binding(get: { model.state?.prediction.max_candidates ?? 3 }, set: { model.updatePrediction(candidates: $0) }), in: 1...5).disabled(model.state?.prediction.installed != true)
            LabeledContent("连续联想", value: "最多 1 轮")
            Text("字母开始新拼音；Escape 或第一次退格退出联想，第二次退格正常删除。数字键、Tab 或点击选择；空格退出并输入空格，连续空格不选接词。标点照常输入。").font(.caption).foregroundStyle(.secondary)
            Text("随时关闭此开关，或切回原“雾凇拼音”方案。设置从下一次输入生效；修改前会备份。").font(.caption).foregroundStyle(.secondary)
        }
        Panel(title: "Kev 候选建议") {
            Toggle("开启 Kev 候选建议", isOn: Binding(get: { model.state?.status.kev_enabled ?? false }, set: { model.action("kev", fields: ["enabled": $0]) })).toggleStyle(.switch)
            Text("开启后也只在按快捷键时请求模型；再次按可撤销。").font(.caption).foregroundStyle(.secondary)
            Divider()
            Picker("调用快捷键", selection: $model.preferences.hotkey) { Text("⌃ ⇧ K").tag("Control+Shift+k"); Text("⌃ ⌥ K").tag("Control+Alt+k"); Text("⌃ ⌥ J").tag("Control+Alt+j") }.frame(maxWidth: 400)
            Text("修改快捷键后，保存并重新部署生效。").font(.caption).foregroundStyle(.secondary)
            LabeledContent("模型位置", value: "127.0.0.1:8009")
        }
        Panel(title: "应用默认中英文") {
            Text("使用应用标识，例如 com.apple.Terminal。未在这里管理的原有设置会保留。").font(.caption).foregroundStyle(.secondary)
            ForEach(model.preferences.apps.indices, id: \.self) { index in
                HStack {
                    TextField("应用标识", text: $model.preferences.apps[index].bundle).textFieldStyle(.roundedBorder)
                    Picker("默认语言", selection: $model.preferences.apps[index].english) { Text("默认中文").tag(false); Text("默认英文").tag(true) }.labelsHidden().frame(width: 135)
                    Button { model.preferences.apps.remove(at: index) } label: { Image(systemName: "minus.circle") }.accessibilityLabel("移除应用规则")
                }
            }
            Button { model.preferences.apps.append(AppRule(bundle: "", english: true)) } label: { Label("添加应用", systemImage: "plus") }
        }
    }
}
struct BackupsView: View {
    @EnvironmentObject var model: ConsoleModel
    @State private var restore: Backup?
    var body: some View {
        HStack {
            PageHeading(title: "设置有备份，状态看得清。", detail: "保存前自动保留版本，也可以随时手动备份。")
            Spacer(); Button("重新部署") { model.action("redeploy") }; Button("立即备份") { model.action("backup") }
        }
        Panel(title: "当前诊断") {
            ForEach(model.checks.indices, id: \.self) { index in
                let check = model.checks[index]
                Label(check.message, systemImage: check.level == "ok" ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    .font(.callout).foregroundStyle(check.level == "ok" ? accent : .orange)
            }
        }
        Panel(title: "本机配置备份", caption: "最近 50 份 · 不含输入历史") {
            if model.backups.isEmpty { Text("第一次保存设置时会自动创建备份。").foregroundStyle(.secondary) }
            ForEach(model.backups) { backup in
                HStack {
                    VStack(alignment: .leading, spacing: 6) { Text(backup.reason); Text(backup.created.replacingOccurrences(of: "T", with: " ").prefix(19)).font(.caption).foregroundStyle(.secondary) }
                    Spacer(); Button("恢复这个版本") { restore = backup }
                }
                Divider()
            }
        }
        .alert("恢复这份备份？", isPresented: Binding(get: { restore != nil }, set: { if !$0 { restore = nil } })) {
            Button("取消", role: .cancel) { restore = nil }
            Button("备份当前并恢复") { if let backup = restore { model.action("restore", fields: ["id": backup.id]) }; restore = nil }
        } message: { Text("恢复控制台管理的外观、快捷键、常用语和本地联想设置。当前版本会先备份，其他配置保留。") }
    }
}
