import AppKit
import SwiftUI
import Charts

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) { NativeBridge.shared.stop() }
}

@main struct KeytrackApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = ConsoleModel()
    var body: some Scene {
        WindowGroup(CommandLine.arguments.contains("--demo") ? "Keytrack · 演示" : "Keytrack · 输入控制台") {
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
                    if let state = model.state {
                        Text(state.status.demo ? "演示数据" : "输入记录\(state.status.recorder.running ? "开启" : "未运行") · AI \(state.status.kev_enabled ? "开启" : "关闭")")
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
                    Label("演示模式 · 保存操作仅影响示例数据", systemImage: "info.circle")
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
                    }.id(model.screen).background(pageBackground)
                }
                if !model.notice.isEmpty {
                    HStack { Image(systemName: "checkmark.circle"); Text(model.notice); Spacer(); Button { model.notice = "" } label: { Image(systemName: "xmark") }.buttonStyle(.plain) }
                        .font(.caption).padding(12).background(accent.opacity(0.1))
                }
            }.navigationTitle(model.screen.title)
                .toolbar {
                    ToolbarItemGroup {
                        if model.busy { ProgressView().controlSize(.small) }
                        if model.state?.deployment.pending == true { Label("设置待生效", systemImage: "clock").font(.caption).foregroundStyle(.orange) }
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
    @State private var width: CGFloat = 900
    private var pairedLayout: AnyLayout {
        width < 820 ? AnyLayout(VStackLayout(alignment: .leading, spacing: 18)) : AnyLayout(HStackLayout(alignment: .top, spacing: 18))
    }
    var body: some View {
        if let report = model.report {
            VStack(alignment: .leading, spacing: 22) {
            HStack {
                PageHeading(title: "输入看板", detail: "查看当天的输入量与按键分布。")
                Spacer()
                Button("今天") { model.changeDate(Date()) }
                DatePicker("日期", selection: Binding(get: { model.selectedDate }, set: { model.changeDate($0) }), displayedComponents: .date).labelsHidden().frame(width: 125)
            }
            if let notice = report.keyStatisticsNotice {
                Label(notice, systemImage: "exclamationmark.triangle").font(.callout).foregroundStyle(.orange)
            }
            LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: width < 740 ? 2 : 4), spacing: 14) {
                Metric(label: "输入字数", value: report.total_chars.formatted(), unit: "字", note: "\(report.segment_count) 条输入记录", icon: "pencil")
                Metric(label: "平均输入量", value: report.cpm.map { String(format: "%.1f", $0) } ?? "—", unit: "字 / 分", note: "仅计算有按键的分钟", icon: "arrow.up.right")
                Metric(label: "输入活跃时间", value: report.active_minutes.map { $0.formatted() } ?? "—", unit: "分钟", note: "有按键记录的分钟数", icon: "clock")
                Metric(label: "退格占比", value: report.correction_rate.map { String(format: "%.1f", $0) } ?? "—", unit: "%", note: "\(report.total_keys.formatted()) 次按键", icon: "delete.left")
            }
            DisclosureGroup("统计说明") {
                VStack(alignment: .leading, spacing: 8) {
                    Text("只统计通过鼠须管输入的文字和按键，不含粘贴、其他输入法及安全输入。组合键按一次计数。")
                    Text("平均输入量按有按键记录的分钟计算，不是打字测速；输入活跃时间不代表工作时长。")
                    Text("手指使用按标准指法估算，不代表实际手指动作；比例仅计算键盘布局内的按键。")
                    Text("键盘布局内 \(report.key_quality.mapped_keys.formatted()) 次 · 布局外 \(report.key_quality.unmapped_keys.formatted()) 次")
                    if let since = report.key_quality.first_verified_minute {
                        Text("最早经校验的按键记录：\(since.replacingOccurrences(of: "T", with: " "))。更早的漏记无法补回。")
                    }
                }.font(.caption).foregroundStyle(.secondary).padding(.top, 8)
            }.font(.caption).foregroundStyle(.secondary)
            pairedLayout {
                Panel(title: "最近两周", caption: "点击查看当天") {
                    HStack(alignment: .bottom, spacing: 7) {
                        ForEach(report.trend) { item in
                            VStack(spacing: 8) {
                                Button { if let date = ConsoleModel.dayFormat.date(from: item.day) { model.changeDate(date) } } label: {
                                    RoundedRectangle(cornerRadius: 4).fill(accent.opacity(item.day == report.day ? 1 : 0.35))
                                        .frame(height: item.chars == 0 ? 0 : max(1, Double(item.chars) / Double(max(1, report.trend.map(\.chars).max() ?? 1)) * 108))
                                        .frame(height: 108, alignment: .bottom).contentShape(Rectangle())
                                }.buttonStyle(.plain).help("\(item.day) · \(item.chars) 字").accessibilityLabel("\(item.day) \(item.chars) 字")
                                Text(String(item.day.suffix(5))).font(.system(size: 10)).foregroundStyle(.secondary)
                            }
                        }
                    }.frame(height: 130)
                    Text("每日输入字数 · 悬停查看数量").font(.caption).foregroundStyle(.secondary)
                }.frame(maxWidth: .infinity)
                Panel(title: "在哪里输入", caption: report.day) {
                    if report.apps.isEmpty { Text("这一天还没有输入记录").foregroundStyle(.secondary) }
                    VStack(spacing: 12) {
                    ForEach(Array(report.apps.prefix(6))) { app in
                        VStack(spacing: 5) {
                            HStack { Text(app.name); Spacer(); Text("\(app.chars.formatted()) 字").foregroundStyle(.secondary) }.font(.caption)
                            ProgressView(value: Double(app.chars), total: Double(max(1, report.apps.first?.chars ?? 1))).tint(accent)
                        }
                    }
                    }
                }.frame(width: width < 820 ? nil : 280)
            }
            pairedLayout {
                Panel(title: "输入日历", caption: "最近 91 天") {
                    InputCalendarView(report: report)
                    HStack(spacing: 5) {
                        Text("少")
                        ForEach([0.06, 0.25, 0.55, 0.86], id: \.self) { opacity in
                            RoundedRectangle(cornerRadius: 2).fill(accent.opacity(opacity)).frame(width: 13, height: 13)
                        }
                        Text("多"); Spacer(); Text("点击查看当天")
                    }.font(.caption).foregroundStyle(.secondary)
                }
                Panel(title: "每小时按键", caption: "所选日期 · 次 / 小时") {
                    HourlyActivityChart(report: report).id(report.day)
                }
            }
            Panel(title: "键盘热力图", caption: "悬停查看次数") {
                KeyboardHeatmap(report: report)
                if !report.key_quality.reliable && report.total_keys > 0 {
                    Text("仅显示已记录的按键；浅色不代表没有按过。").font(.caption).foregroundStyle(.secondary)
                }
            }
            Panel(title: "手指使用估算", caption: "按标准指法分配按键") {
                if report.fingers.isEmpty || report.key_quality.mapped_keys == 0 {
                    Text(report.key_quality.reliable ? "没有可映射到键盘布局的按键" : report.key_quality.message).font(.caption).foregroundStyle(.secondary)
                }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 78))], spacing: 8) {
                    ForEach(report.fingers) { finger in
                        VStack(spacing: 7) {
                            Text(finger.name).font(.system(size: 10)).foregroundStyle(.secondary)
                            Text(String(format: "%.1f%%", Double(finger.count) / Double(max(1, report.fingers.map(\.count).reduce(0, +))) * 100)).font(.system(size: 17, weight: .medium, design: .rounded))
                        }.frame(maxWidth: .infinity).padding(.vertical, 12).background(accent.opacity(0.06), in: RoundedRectangle(cornerRadius: 8))
                    }
                }
            }
            Panel(title: "输入记录") {
                HStack { Text("点击展开后，才读取当天输入的文字。").font(.caption).foregroundStyle(.secondary); Spacer(); Button(model.showText ? "收起原文" : "查看原文") { model.toggleText() } }
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
            }.onGeometryChange(for: CGFloat.self) { $0.size.width } action: { width = $0 }
        }
    }
}
struct InputCalendarView: View {
    @EnvironmentObject var model: ConsoleModel
    var report: Report
    private var offset: Int {
        guard let first = report.calendar.first, let date = ConsoleModel.dayFormat.date(from: first.day) else { return 0 }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Asia/Shanghai")!
        return (calendar.component(.weekday, from: date) + 5) % 7
    }
    var body: some View {
        GeometryReader { geometry in
            let columns = max(1, (offset + report.calendar.count + 6) / 7)
            let cellWidth = max(4, (geometry.size.width - 18 - CGFloat(columns - 1) * 5) / CGFloat(columns))
            HStack(alignment: .top, spacing: 6) {
                VStack(spacing: 6) {
                    ForEach(["一", "二", "三", "四", "五", "六", "日"], id: \.self) { day in
                        Text(day).font(.system(size: 9)).foregroundStyle(.secondary).frame(width: 12, height: 17)
                    }
                }
                LazyHGrid(rows: Array(repeating: GridItem(.fixed(17), spacing: 6), count: 7), spacing: 5) {
                    ForEach(0..<(offset + report.calendar.count), id: \.self) { index in
                        if index < offset {
                            Color.clear.frame(width: cellWidth, height: 17)
                        } else {
                            let item = report.calendar[index - offset]
                            Button { if let date = ConsoleModel.dayFormat.date(from: item.day) { model.changeDate(date) } } label: {
                                RoundedRectangle(cornerRadius: 3)
                                    .fill(accent.opacity(item.chars == 0 ? 0.06 : 0.16 + 0.7 * sqrt(Double(item.chars) / Double(max(1, report.calendar.map(\.chars).max() ?? 1)))))
                                    .frame(width: cellWidth, height: 17)
                                    .overlay(RoundedRectangle(cornerRadius: 3).stroke(item.day == report.day ? accent : .clear, lineWidth: 1.5))
                            }.buttonStyle(.plain).help("\(item.day) · \(item.chars.formatted()) 字")
                                .accessibilityLabel("\(item.day) \(item.chars) 字")
                        }
                    }
                }
            }
        }.frame(height: 155)
    }
}
struct HourlyActivityChart: View {
    var report: Report
    @State private var selected: Double?
    private var selectedHour: Int? {
        guard let selected, selected >= 0, selected < Double(report.hours.count) else { return nil }
        return Int(selected)
    }
    var body: some View {
        if report.hours.isEmpty || report.hours.allSatisfy({ $0 == 0 }) {
            Text(report.hourlyEmptyMessage).font(.callout).foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, minHeight: 130, alignment: .center)
        } else {
            VStack(alignment: .leading, spacing: 10) {
                Chart(report.hours.indices, id: \.self) { hour in
                    BarMark(x: .value("小时", Double(hour) + 0.5), y: .value("按键次数", report.hours[hour]), width: .fixed(10))
                        .foregroundStyle(accent.opacity(selectedHour == hour ? 1 : 0.5))
                        .accessibilityLabel("\(hour)时至\(hour + 1)时")
                        .accessibilityValue("\(report.hours[hour]) 次按键")
                }
                .chartXScale(domain: 0.0...24.0)
                .chartYScale(domain: 0...max(1, report.hours.max() ?? 1))
                .chartXAxis {
                    AxisMarks(values: [0.0, 6.0, 12.0, 18.0, 24.0]) { value in
                        AxisTick()
                        AxisValueLabel(anchor: value.as(Double.self) == 24 ? .topTrailing : .topLeading) {
                            if let hour = value.as(Double.self) { Text("\(Int(hour))时") }
                        }
                    }
                }
                .chartYAxis { AxisMarks(position: .leading) }
                .chartXSelection(value: $selected)
                .chartOverlay { proxy in
                    GeometryReader { geometry in
                        Color.clear.contentShape(Rectangle()).onContinuousHover { phase in
                            switch phase {
                            case .active(let location):
                                if let frame = proxy.plotFrame {
                                    selected = proxy.value(atX: location.x - geometry[frame].origin.x, as: Double.self)
                                }
                            case .ended: selected = nil
                            }
                        }
                    }
                }
                .frame(height: 150)
                if let hour = selectedHour {
                    Text("\(hour):00–\(hour + 1):00 · \(report.hours[hour].formatted()) 次按键")
                        .font(.caption).foregroundStyle(accent)
                } else {
                    Text("共 \(report.hours.reduce(0, +).formatted()) 次按键 · 悬停查看每小时次数")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }.onChange(of: report.day) { _, _ in selected = nil }
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
    @State private var expandedPhrases: Set<String> = []
    var categories: [String] { Array(Set(model.phrases.map(\.category))).sorted() }
    var filtered: [Phrase] { model.phrases.filter { (category.isEmpty || $0.category == category) && (query.isEmpty || ($0.code + $0.category + $0.text).localizedCaseInsensitiveContains(query)) } }
    var body: some View {
        HStack {
            PageHeading(title: "常用语", detail: "用短编码输入常用回复、签名和地址。")
            Spacer()
            Button("导入") { model.importPhrases() }.disabled(model.busy)
            Menu("导出") {
                Button("JSON 文件") { model.exportPhrases(format: "json") }
                Button("TSV 表格") { model.exportPhrases(format: "tsv") }
            }.disabled(model.busy || model.phrases.isEmpty)
            Button { originalCode = nil; editor = Phrase(code: "", category: "常用语", text: "") } label: { Label("添加", systemImage: "plus") }
        }
        Text("输入完整短编码后，用空格上屏。支持多行内容。").font(.caption).foregroundStyle(.secondary)
        HStack {
            TextField("搜索内容、分类或编码", text: $query).textFieldStyle(.roundedBorder)
            Picker("分类", selection: $category) { Text("所有分类").tag(""); ForEach(categories, id: \.self) { Text($0).tag($0) } }.frame(width: 180)
        }
        PhraseDiscoveryView()
        if filtered.isEmpty { Panel(title: model.phrases.isEmpty ? "添加第一条常用语" : "没有匹配的常用语") { Text("保存并应用后，短编码会接入雾凇拼音。").foregroundStyle(.secondary) } }
        ForEach(filtered) { item in
            Panel(title: item.category, caption: item.code) {
                Text(item.text).lineLimit(expandedPhrases.contains(item.code) || (item.text.count <= 80 && !item.text.contains("\n")) ? nil : 3).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                HStack {
                    if item.text.count > 80 || item.text.contains("\n") {
                        Button(expandedPhrases.contains(item.code) ? "收起全文" : "展开全文") {
                            if expandedPhrases.contains(item.code) { expandedPhrases.remove(item.code) } else { expandedPhrases.insert(item.code) }
                        }.font(.caption)
                    }
                    Spacer()
                    Button("复制") { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(item.text, forType: .string); model.notice = "已复制常用语" }
                    Button("编辑") { originalCode = item.code; editor = item }
                    Button("移出列表", role: .destructive) { model.phrases.removeAll { $0.code == item.code } }
                }
            }
        }
        .sheet(item: $editor) { item in PhraseEditor(initial: item, originalCode: originalCode).environmentObject(model) }
        .sheet(isPresented: $model.showPhraseImport, onDismiss: { model.clearPhraseImport() }) {
            PhraseImportPreview().environmentObject(model)
        }
    }
}
struct PhraseImportPreview: View {
    @EnvironmentObject var model: ConsoleModel
    @State private var expanded: Set<String> = []
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("确认要导入的常用语").font(.title2.bold())
            if let report = model.phraseImport {
                Text("新增 \(report.counts["new"] ?? 0) · 重复 \(report.counts["duplicate"] ?? 0) · 冲突 \(report.counts["conflict"] ?? 0) · 无效 \(report.counts["invalid"] ?? 0)")
                    .font(.callout).foregroundStyle(.secondary)
                HStack {
                    Button("勾选可新增项") {
                        model.importSelected = Set(report.rows.filter { $0.status == "new" }.prefix(max(0, 300 - model.phrases.count)).map(\.id))
                    }
                    Button("清除勾选") { model.importSelected = [] }
                    Spacer()
                    Text("已选 \(model.importSelected.count) 条").font(.caption)
                }
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        ForEach(report.rows) { row in
                            HStack(alignment: .top, spacing: 12) {
                                Toggle("导入 \(row.code)", isOn: Binding(get: { model.importSelected.contains(row.id) }, set: { selected in
                                    if selected { model.importSelected.insert(row.id) } else { model.importSelected.remove(row.id) }
                                })).labelsHidden().toggleStyle(.checkbox).disabled(row.status != "new")
                                VStack(alignment: .leading, spacing: 6) {
                                    Text("\(row.code) · \(row.category)").font(.callout.weight(.medium))
                                    Text(row.text).lineLimit(expanded.contains(row.id) ? nil : 4).textSelection(.enabled)
                                    Button(expanded.contains(row.id) ? "收起全文" : "展开全文") {
                                        if expanded.contains(row.id) { expanded.remove(row.id) } else { expanded.insert(row.id) }
                                    }.font(.caption)
                                    Text(row.message).font(.caption).foregroundStyle(row.status == "conflict" || row.status == "invalid" ? Color.orange : .secondary)
                                }.frame(maxWidth: .infinity, alignment: .leading)
                            }.padding(12).background(Color.secondary.opacity(0.05), in: RoundedRectangle(cornerRadius: 8))
                        }
                    }
                }.frame(minHeight: 250, maxHeight: 410)
            }
            Text("重复和冲突不会覆盖现有条目。加入列表后，点击“保存并应用”才会生效。")
                .font(.caption).foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button("取消") { model.clearPhraseImport() }.keyboardShortcut(.cancelAction)
                Button("加入所选条目") { model.addImportedPhrases() }.buttonStyle(.borderedProminent)
                    .disabled(!model.importCanAdd).keyboardShortcut(.defaultAction)
            }
        }.padding(24).frame(width: 600)
    }
}
struct PhraseDiscoveryView: View {
    @EnvironmentObject var model: ConsoleModel
    @State private var expanded = false
    var body: some View {
        Panel(title: "发现重复表达", caption: "仅在本机分析") {
            DisclosureGroup("查看分析选项", isExpanded: $expanded) {
                VStack(alignment: .leading, spacing: 14) {
                    Text("点击分析后才读取所选范围的历史；结果由你选择，不会自动加入常用语。")
                        .font(.caption).foregroundStyle(.secondary)
                    DisclosureGroup("如何筛选建议") {
                        Text("建议需至少出现 3 次、来自 2 个独立记录批次。批次按应用、窗口标题及至少 30 分钟的间隔估算，不代表实际输入会话。")
                            .font(.caption).foregroundStyle(.secondary).padding(.top, 6)
                    }.font(.caption)
                    HStack {
                        Picker("分析范围", selection: $model.discoveryDays) {
                            Text("最近 7 天").tag(7); Text("最近 30 天").tag(30); Text("最近 90 天").tag(90)
                        }.frame(width: 230)
                        Button("分析已有历史") { model.analyzePhraseHistory() }.buttonStyle(.borderedProminent)
                        Spacer()
                    }
                    if let report = model.phraseDiscovery {
                        Text("\(report.start_day) 至 \(report.end_day) · 检查 \(report.scanned_segments.formatted()) 条记录 · 显示 \(report.candidates.count) 条建议")
                            .font(.caption).foregroundStyle(.secondary)
                        if report.days != model.discoveryDays {
                            Label("范围已调整，请重新分析。当前仍显示最近 \(report.days) 天的结果。", systemImage: "info.circle")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        if report.truncated {
                            Label("本次达到扫描或建议显示上限，显示的次数可能仅代表已扫描记录。", systemImage: "exclamationmark.triangle")
                                .font(.caption).foregroundStyle(.orange)
                            Text(report.message).font(.caption).foregroundStyle(.secondary)
                        }
                        if report.candidates.isEmpty {
                            Text("没有可显示的重复表达。").foregroundStyle(.secondary)
                        }
                        ForEach(Array(report.candidates.enumerated()), id: \.element.id) { index, candidate in
                            PhraseDiscoveryRow(candidate: candidate, number: index + 1)
                        }
                        HStack {
                            Button("加入所选常用语") { model.addDiscoveredPhrases() }
                                .buttonStyle(.borderedProminent).disabled(!model.discoveryCanAdd)
                            Text("\(model.discoverySelected.count) 条已勾选").font(.caption).foregroundStyle(.secondary)
                            Spacer()
                            Button("清除分析结果") { model.clearPhraseDiscovery() }
                        }
                        Text("加入列表后仍需点击“保存并应用”；修改前会自动备份。点击“不再推荐”会记住拒绝，不会删除历史。")
                            .font(.caption).foregroundStyle(.secondary)
                        Text("建议编码优先使用拼音首字母，冲突或无法转换时保留备用编码；可按自己的习惯修改。")
                            .font(.caption).foregroundStyle(.secondary)
                        if report.rejected_count > 0 {
                            Text("已记住 \(report.rejected_count) 条拒绝，后续分析会跳过这些表达。")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }.padding(.top, 12)
            }
        }
        .onChange(of: expanded) { _, visible in if !visible { model.clearPhraseDiscovery() } }
        .onDisappear { model.clearPhraseDiscovery() }
    }
}
struct PhraseDiscoveryRow: View {
    @EnvironmentObject var model: ConsoleModel
    var candidate: PhraseDiscoveryCandidate
    var number: Int
    private var duplicate: Phrase? { PhraseDiscoverySelection.duplicate(candidate, in: model.phrases) }
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 10) {
                Toggle("选择建议 \(number)", isOn: Binding(get: { model.discoverySelected.contains(candidate.id) }, set: { selected in
                    if selected { model.discoverySelected.insert(candidate.id) } else { model.discoverySelected.remove(candidate.id) }
                })).labelsHidden().toggleStyle(.checkbox).disabled(duplicate != nil || candidate.duplicate)
                    .accessibilityLabel("选择建议 \(number)")
                Text(candidate.text).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            HStack {
                Text("\(candidate.count) 次 · \(candidate.batch_count) 个独立记录批次").font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button("不再推荐") { model.rejectDiscoveredPhrases([candidate.id]) }
                    .accessibilityLabel("不再推荐建议 \(number)")
            }
            HStack {
                Text("建议短编码").font(.caption).foregroundStyle(.secondary)
                TextField("短编码", text: Binding(get: { model.discoveryCodes[candidate.id] ?? candidate.suggested_code }, set: { model.discoveryCodes[candidate.id] = $0 }))
                    .textFieldStyle(.roundedBorder).frame(width: 180).disabled(duplicate != nil || candidate.duplicate)
                    .accessibilityLabel("建议短编码 \(number)")
                Spacer()
            }
            if let issue = model.discoveryIssue(candidate) {
                Label(issue, systemImage: duplicate != nil || candidate.duplicate ? "checkmark.circle" : "exclamationmark.triangle")
                    .font(.caption).foregroundStyle(duplicate != nil || candidate.duplicate ? Color.secondary : .orange)
            }
        }.padding(14).background(Color.secondary.opacity(0.05), in: RoundedRectangle(cornerRadius: 8))
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
        PageHeading(title: "候选外观", detail: "预览字体、布局与配色，保存并应用后生效。")
        Panel(title: "候选窗预览", caption: selectedTheme == nil ? "原有配色仅作示意" : "设置预览") {
            Toggle("深色预览", isOn: $dark).toggleStyle(.switch).frame(maxWidth: .infinity, alignment: .trailing)
            if inlinePreedit {
                HStack(spacing: 7) {
                    Text("正在输入").foregroundStyle(.secondary)
                    Text("ni hao").font(previewFont(model.preferences.font_size)).underline()
                    Spacer()
                    Text("行内拼音示意").font(.caption).foregroundStyle(.secondary)
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
            Text("预览供参考，实际显示以鼠须管候选窗为准。行内拼音可能使用当前应用的字体。").font(.caption).foregroundStyle(.secondary)
        }
        Panel(title: "配色方案") {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 172, maximum: 260), spacing: 12)], alignment: .leading, spacing: 12) {
                ForEach([AppearanceTheme.existing] + themes) { theme in
                    AppearanceThemeCard(theme: theme, selected: model.preferences.theme == theme.id) { model.preferences.theme = theme.id }
                }
            }
            Text("配色随系统切换浅色与深色。“保留当前”恢复首次保存前的配色。").font(.caption).foregroundStyle(.secondary)
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
            if model.preferences.font_mode == "custom" {
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
            Text("共 \(CandidateFonts.installed.count) 款字体，匹配 \(fontMatches.count) 款。").font(.caption).foregroundStyle(.secondary)
            }
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
                Text(index == 0 ? "问候" : (index == 1 ? "同音" : ""))
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
    @State private var showGlossary = false
    var body: some View {
        PageHeading(title: "输入设置", detail: "设置补全、联想、AI 建议与应用默认语言。")
        if model.dirty {
            Label("请先保存或放弃修改，再切换立即生效的开关。", systemImage: "info.circle").font(.caption).foregroundStyle(.secondary)
        }
        Panel(title: "补全与 Emoji", caption: "保存后生效") {
            Picker("英文补全", selection: $model.preferences.english_completion) {
                Text("保留原设置").tag("existing"); Text("开启").tag("on"); Text("关闭").tag("off")
            }.disabled(model.state?.input_tools?["english_completion"]?.available != true)
            Picker("中英词补全", selection: $model.preferences.mixed_completion) {
                Text("保留原设置").tag("existing"); Text("开启").tag("on"); Text("关闭").tag("off")
            }.disabled(model.state?.input_tools?["mixed_completion"]?.available != true)
            Picker("Emoji 初始状态", selection: $model.preferences.emoji_default) {
                Text("保留原设置").tag("existing"); Text("开启").tag("on"); Text("关闭").tag("off")
            }.disabled(model.state?.input_tools?["emoji_default"]?.available != true)
            Text("Emoji 决定输入方案启动时的状态，输入时仍可在方案菜单切换。")
                .font(.caption).foregroundStyle(.secondary)
            DisclosureGroup("快捷输入示例") {
                Text("rq 日期 · sj 时间 · xq 星期 · nl 农历 · uuid 标识；cC 后接算式可计算。")
                    .font(.caption).foregroundStyle(.secondary).textSelection(.enabled).padding(.top, 6)
            }.font(.caption)
        }
        Panel(title: "本地接词联想", caption: "实验版 · 立即生效") {
            if model.state?.prediction.installed == false {
                HStack {
                    Text("先安装独立测试方案，原“雾凇拼音”方案继续保留。").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button("安装联想实验方案") { model.action("prediction_install") }.buttonStyle(.borderedProminent).disabled(model.dirty)
                }
            }
            Toggle("开启本地接词联想", isOn: Binding(get: { model.state?.prediction.enabled ?? false }, set: { model.updatePrediction(enabled: $0) })).toggleStyle(.switch)
                .disabled(model.state?.prediction.installed != true || model.dirty)
            Text("先切换到“\(model.state?.prediction.schema_name ?? "雾凇拼音 · 接词实验")”方案。上屏后显示带“联想”标记的接词，不等待模型推理。").font(.caption).foregroundStyle(.secondary)
            Stepper("联想候选：\(model.state?.prediction.max_candidates ?? 3) 个", value: Binding(get: { model.state?.prediction.max_candidates ?? 3 }, set: { model.updatePrediction(candidates: $0) }), in: 1...5).disabled(model.state?.prediction.installed != true || model.dirty)
            LabeledContent("连续联想", value: "最多 1 轮")
            Text("空格退出联想并输入空格；随时关闭开关或切回原方案。").font(.caption).foregroundStyle(.secondary)
            DisclosureGroup("联想操作说明") {
                Text("字母开始新拼音；Escape 或第一次退格退出联想，第二次退格正常删除。数字键、Tab 或点击选择；连续空格不选接词，标点照常输入。开关与候选数量从下一次输入生效，修改前会备份。")
                    .font(.caption).foregroundStyle(.secondary).padding(.top, 6)
            }.font(.caption)
        }
        Panel(title: "AI 候选建议", caption: "开关立即生效") {
            Toggle("开启 Kev 候选建议", isOn: Binding(get: { model.state?.status.kev_enabled ?? false }, set: { model.action("kev", fields: ["enabled": $0]) })).toggleStyle(.switch).disabled(model.dirty)
            Text("AI 在本机运行，仅按快捷键时请求建议；再次按可撤销。").font(.caption).foregroundStyle(.secondary)
            Divider()
            Picker("调用快捷键", selection: $model.preferences.hotkey) { Text("⌃ ⇧ K").tag("Control+Shift+k"); Text("⌃ ⌥ K").tag("Control+Alt+k"); Text("⌃ ⌥ J").tag("Control+Alt+j") }.frame(maxWidth: 400)
            Text("快捷键修改后，点击“保存并应用”生效。").font(.caption).foregroundStyle(.secondary)
        }
        Panel(title: "候选释义", caption: "保存后生效") {
            Picker("释义语言", selection: $model.preferences.gloss_language) {
                Text("关闭").tag("off"); Text("英文").tag("en"); Text("日文").tag("ja")
            }.frame(maxWidth: 400)
                .disabled(model.state?.glossary == nil)
                .accessibilityLabel("候选释义语言")
            Text("使用本地词表，支持工作术语和个人修订。未收录的词不显示释义。选择后点击“保存并应用”生效。")
                .font(.caption).foregroundStyle(.secondary)
            if let glossary = model.state?.glossary {
                HStack {
                    Text("内置 \((glossary.base_count ?? 120) + (glossary.term_count ?? 0)) 条 · 个人修订 \(model.preferences.gloss_overrides.count) 条").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button("管理释义词表") { showGlossary = true }.disabled(glossary.entries == nil)
                }
                if model.preferences.gloss_language != "off" {
                    ForEach(Array(glossary.examples.prefix(3))) { example in
                        let comment = example.comment(for: model.preferences.gloss_language)
                        let marker = example.original_comment + " · "
                        HStack(alignment: .top, spacing: 16) {
                            Text(example.text).font(.callout.weight(.medium)).frame(width: 70, alignment: .leading)
                            Text(!example.original_comment.isEmpty && comment.hasPrefix(marker) ? String(comment.dropFirst(marker.count)) : comment)
                                .textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }.padding(.vertical, 4)
                    }
                    Text("样例仅用于设置预览，实际注释以鼠须管候选窗为准。")
                        .font(.caption).foregroundStyle(.secondary)
                }
            } else {
                Text("当前运行组件未提供词表示例，请更新组件后启用。")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        Panel(title: "应用默认语言", caption: "保存后生效") {
            Text("为不同应用选择默认中文或英文；原有的其他应用设置会保留。").font(.caption).foregroundStyle(.secondary)
            ForEach(model.preferences.apps.indices, id: \.self) { index in
                AppLanguageRuleRow(rule: $model.preferences.apps[index]) { model.preferences.apps.remove(at: index) }
            }
            HStack {
                Button("选择应用") { model.chooseApplication() }.disabled(model.preferences.apps.count >= 30)
                Button("手动添加") { model.preferences.apps.append(AppRule(bundle: "", english: true)) }.disabled(model.preferences.apps.count >= 30)
            }
        }
        .sheet(isPresented: $showGlossary) { GlossaryManager().environmentObject(model) }
    }
}
struct AppLanguageRuleRow: View {
    @Binding var rule: AppRule
    var remove: () -> Void
    @State private var editingIdentifier: Bool
    init(rule: Binding<AppRule>, remove: @escaping () -> Void) {
        _rule = rule
        self.remove = remove
        _editingIdentifier = State(initialValue: rule.wrappedValue.bundle.isEmpty)
    }
    private var applicationName: String {
        NSWorkspace.shared.urlForApplication(withBundleIdentifier: rule.bundle)?.deletingPathExtension().lastPathComponent ?? "手动添加的应用"
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(applicationName).lineLimit(1)
                Spacer()
                Picker("默认语言", selection: $rule.english) { Text("默认中文").tag(false); Text("默认英文").tag(true) }.labelsHidden().frame(width: 135)
                Button(action: remove) { Image(systemName: "minus.circle") }.accessibilityLabel("移除应用规则")
            }
            DisclosureGroup("编辑应用标识", isExpanded: $editingIdentifier) {
                TextField("应用标识，例如 com.apple.Safari", text: $rule.bundle).textFieldStyle(.roundedBorder).padding(.top, 6)
            }.font(.caption).foregroundStyle(.secondary)
        }
    }
}
struct GlossaryManager: View {
    @EnvironmentObject var model: ConsoleModel
    @Environment(\.dismiss) var dismiss
    @State private var search = ""
    @State private var editing: GlossaryEntry?
    private var entries: [GlossaryEntry] {
        var items = Dictionary(uniqueKeysWithValues: (model.state?.glossary?.entries ?? []).map { ($0.word, $0) })
        for item in model.state?.settings.gloss_overrides ?? [] { items.removeValue(forKey: item.word) }
        // Restoring an override also restores the bundled entry supplied separately.
        for item in model.state?.glossary?.bundled_entries ?? [] { items[item.word] = item }
        for item in model.preferences.gloss_overrides { items[item.word] = item }
        return items.values.filter { search.isEmpty || ($0.word + $0.en + $0.ja + $0.reading).localizedCaseInsensitiveContains(search) }.sorted { $0.word < $1.word }
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("本地释义词表").font(.title2.bold())
                Spacer()
                Button("新增词条") { editing = GlossaryEntry(word: "", en: "", ja: "") }
            }
            TextField("搜索中文、英文或日文", text: $search).textFieldStyle(.roundedBorder)
            Text("个人修订 \(model.preferences.gloss_overrides.count) / 300。修改进入草稿，保存并应用后生效。")
                .font(.caption).foregroundStyle(.secondary)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    ForEach(entries) { item in
                        HStack(alignment: .top) {
                            VStack(alignment: .leading, spacing: 5) {
                                Text(item.word).font(.headline)
                                Text("EN: \(item.en)")
                                Text("日: \(item.ja)\(item.reading.isEmpty ? "" : "（" + item.reading + "）")")
                            }.textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                            VStack {
                                Button("修订") { editing = item }
                                if model.preferences.gloss_overrides.contains(where: { $0.word == item.word }) {
                                    Button("撤销个人修订") { model.preferences.gloss_overrides.removeAll { $0.word == item.word } }
                                }
                            }
                        }.padding(12).background(Color.secondary.opacity(0.05), in: RoundedRectangle(cornerRadius: 8))
                    }
                }
            }.frame(height: 400)
            HStack { Spacer(); Button("完成") { dismiss() }.keyboardShortcut(.defaultAction) }
        }.padding(24).frame(width: 650)
            .sheet(item: $editing) { item in GlossaryEditor(initial: item).environmentObject(model) }
    }
}
struct GlossaryEditor: View {
    @EnvironmentObject var model: ConsoleModel
    @Environment(\.dismiss) var dismiss
    @State var item: GlossaryEntry
    var originalWord: String
    @State private var error = ""
    init(initial: GlossaryEntry) { _item = State(initialValue: initial); originalWord = initial.word }
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text(originalWord.isEmpty ? "新增释义" : "修订释义").font(.title2.bold())
            Form {
                TextField("中文词", text: $item.word).disabled(!originalWord.isEmpty)
                TextField("英文", text: $item.en)
                TextField("日文", text: $item.ja)
                TextField("日文读音（可选）", text: $item.reading)
            }
            Text("中文词为 1–8 个汉字；英文、日文和读音各最多 80 字符，使用简短单行释义。")
                .font(.caption).foregroundStyle(.secondary)
            if !error.isEmpty { Text(error).font(.caption).foregroundStyle(.red) }
            HStack {
                Spacer(); Button("取消") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("加入草稿") { submit() }.buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
            }
        }.padding(24).frame(width: 500)
    }
    func submit() {
        guard (1...8).contains(item.word.unicodeScalars.count), item.word.unicodeScalars.allSatisfy({ (0x3400...0x9FFF).contains($0.value) }) else { error = "中文词须为 1–8 个汉字。"; return }
        let values = [item.en, item.ja, item.reading]
        guard !item.en.isEmpty, !item.ja.isEmpty, values.allSatisfy({ value in
            value.unicodeScalars.count <= 80 && value == value.trimmingCharacters(in: .whitespacesAndNewlines) &&
            !value.unicodeScalars.contains { $0.value < 32 || (127...159).contains($0.value) || $0.value == 0x2028 || $0.value == 0x2029 }
        }) else { error = "英文和日文必填，最多 80 字符；请去除换行与首尾空白。"; return }
        if let index = model.preferences.gloss_overrides.firstIndex(where: { $0.word == item.word }) {
            model.preferences.gloss_overrides[index] = item
        } else {
            guard model.preferences.gloss_overrides.count < 300 else { error = "个人修订最多 300 条。"; return }
            model.preferences.gloss_overrides.append(item)
        }
        model.preferences.gloss_overrides.sort { $0.word < $1.word }
        dismiss()
    }
}
struct BackupsView: View {
    @EnvironmentObject var model: ConsoleModel
    @State private var restore: Backup?
    @State private var showDiagnostics = false
    @State private var showAllBackups = false
    var body: some View {
        HStack {
            PageHeading(title: "备份与状态", detail: "保存前自动备份，也可以手动保留当前设置。")
            Spacer(); Button("立即备份") { model.action("backup") }
        }
        Panel(title: "当前状态") {
            if model.checks.isEmpty { ProgressView("正在检查…") }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 170))], alignment: .leading, spacing: 14) {
                ForEach(HealthPresentation.summaries(model.checks, kevEnabled: model.state?.status.kev_enabled == true)) { summary in
                    VStack(alignment: .leading, spacing: 8) {
                        CheckIndicator(level: summary.level, text: summary.title)
                        Text(summary.message).font(.caption).foregroundStyle(.secondary)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            DisclosureGroup("检查详情", isExpanded: $showDiagnostics) {
                VStack(alignment: .leading, spacing: 12) {
                    ForEach(model.checks.indices, id: \.self) { index in
                        let check = model.checks[index]
                        CheckIndicator(level: check.level, text: check.message).font(.caption)
                    }
                    Text("这些检查确认安装与服务状态；实际建议效果可在输入时查看。")
                        .font(.caption).foregroundStyle(.secondary)
                    Button("重新应用设置") { model.action("redeploy") }
                }.padding(.top, 10)
            }
            .font(.caption)
            .onChange(of: model.checks.map(\.level), initial: true) { _, levels in
                if levels.contains(where: { $0 != "ok" }) { showDiagnostics = true }
            }
        }
        Panel(title: "设置备份", caption: "不含输入历史") {
            if model.backups.isEmpty { Text("第一次保存设置时会自动创建备份。").foregroundStyle(.secondary) }
            ForEach(Array(showAllBackups ? model.backups : Array(model.backups.prefix(5)))) { backup in
                HStack {
                    VStack(alignment: .leading, spacing: 6) { Text(backup.reason); Text(backup.created.replacingOccurrences(of: "T", with: " ").prefix(19)).font(.caption).foregroundStyle(.secondary) }
                    Spacer(); Button("恢复这个版本") { restore = backup }
                }
                Divider()
            }
            if model.backups.count > 5 {
                Button(showAllBackups ? "收起较早备份" : "查看全部 \(model.backups.count) 份备份") { showAllBackups.toggle() }
                    .font(.caption)
            }
        }
        .alert("恢复这份备份？", isPresented: Binding(get: { restore != nil }, set: { if !$0 { restore = nil } })) {
            Button("取消", role: .cancel) { restore = nil }
            Button("备份当前并恢复") { if let backup = restore { model.action("restore", fields: ["id": backup.id]) }; restore = nil }
        } message: { Text("恢复控制台管理的外观、候选释义、快捷键、常用语和本地联想设置。当前版本会先备份，其他配置保留。") }
    }
}
struct CheckIndicator: View {
    var level: String
    var text: String
    var body: some View {
        Label(text, systemImage: level == "ok" ? "checkmark.circle.fill" : (level == "error" ? "xmark.circle.fill" : "exclamationmark.triangle.fill"))
            .foregroundStyle(level == "ok" ? accent : (level == "error" ? Color.red : Color.orange))
    }
}
