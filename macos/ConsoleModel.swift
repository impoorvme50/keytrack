import Foundation
import AppKit
import SwiftUI
import UniformTypeIdentifiers
import Darwin

struct Phrase: Codable, Equatable, Identifiable {
    var code: String
    var category: String
    var text: String
    var id: String { code }
}
struct PhraseImportRow: Decodable, Identifiable {
    var id: String
    var code: String
    var text: String
    var category: String
    var status: String
    var message: String
}
struct PhraseImportReport: Decodable {
    var rows: [PhraseImportRow]
    var counts: [String: Int]
}
struct PhraseExport: Decodable { var content: String }
enum PhraseImportSelection {
    static func additions(_ report: PhraseImportReport, selected: Set<String>, existing: [Phrase]) throws -> [Phrase] {
        let rows = report.rows.filter { selected.contains($0.id) }
        guard !rows.isEmpty, rows.count == selected.count, rows.allSatisfy({ $0.status == "new" }) else {
            throw LocalError(message: "请选择可新增的常用语。")
        }
        guard existing.count + rows.count <= 300 else { throw LocalError(message: "常用语最多 300 条，请减少勾选数量。") }
        let codes = rows.map(\.code)
        let texts = rows.map(\.text)
        let existingCodes = Set(existing.map(\.code))
        let existingTexts = Set(existing.map(\.text))
        guard Set(codes).count == codes.count, Set(texts).count == texts.count,
              existingCodes.isDisjoint(with: codes), existingTexts.isDisjoint(with: texts) else {
            throw LocalError(message: "草稿已改变，编码或内容出现冲突，请重新导入预览。")
        }
        return rows.map { Phrase(code: $0.code, category: $0.category, text: $0.text) }
    }
}
enum SelectedTextFile {
    static func read(_ url: URL) throws -> String {
        let descriptor = Darwin.open(url.path, O_RDONLY | O_NONBLOCK | O_NOFOLLOW)
        guard descriptor >= 0 else { throw LocalError(message: "无法打开所选文件，请选择普通 JSON 或 TSV 文件。") }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? handle.close() }
        var metadata = stat()
        guard fstat(descriptor, &metadata) == 0, metadata.st_mode & S_IFMT == S_IFREG,
              metadata.st_size <= 2_000_000 else { throw LocalError(message: "导入文件须为 2 MB 以内的普通文件。") }
        let bytes = try handle.read(upToCount: 2_000_001) ?? Data()
        guard bytes.count <= 2_000_000, let text = String(data: bytes, encoding: .utf8) else {
            throw LocalError(message: "导入文件须为 2 MB 以内的 UTF-8 文本。")
        }
        return text
    }
}
struct GlossaryEntry: Codable, Equatable, Identifiable {
    var word: String
    var en: String
    var ja: String
    var reading: String = ""
    var id: String { word }
}
struct PhraseDiscoveryCandidate: Decodable, Identifiable {
    var id: String
    var text: String
    var count: Int
    var batch_count: Int
    var suggested_code: String
    var duplicate: Bool
    var code_conflict: Bool
    var existing_code: String?
}
struct PhraseDiscoveryReport: Decodable {
    var days: Int
    var start_day: String
    var end_day: String
    var scanned_segments: Int
    var truncated: Bool
    var message: String
    var batch_basis: String
    var rejected_count: Int
    var revision: String
    var candidates: [PhraseDiscoveryCandidate]
}
struct PhraseDiscoveryRejection: Decodable {
    var message: String
    var rejected_count: Int
    var rejected_ids: [String]
    var revision: String
}
enum PhraseDiscoverySelection {
    static func mnemonicCode(for text: String, transform: (String) -> String? = {
        $0.applyingTransform(.mandarinToLatin, reverse: false)?.applyingTransform(.stripDiacritics, reverse: false)
    }) -> String? {
        guard text.range(of: "\\p{Han}", options: .regularExpression) != nil,
              let converted = transform(text), converted.range(of: "\\p{Han}", options: .regularExpression) == nil else { return nil }
        let words = converted.lowercased().components(separatedBy: CharacterSet.letters.inverted)
            .filter { !$0.isEmpty && $0.range(of: "^[a-z]+$", options: .regularExpression) != nil }
        guard words.count >= 4 else { return nil }
        return "q" + words.prefix(6).compactMap { $0.first }.map(String.init).joined()
    }
    static func initialCodes(candidates: [PhraseDiscoveryCandidate], phrases: [Phrase], edits: [String: String],
                             transform: (String) -> String? = {
        $0.applyingTransform(.mandarinToLatin, reverse: false)?.applyingTransform(.stripDiacritics, reverse: false)
    }) -> [String: String] {
        var result = edits
        var reserved = Set(phrases.map(\.code))
        reserved.formUnion(result.values.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) })
        // Reserve all portable fallbacks before choosing mnemonics, including
        // later rows. Existing edits remain the user's responsibility to review.
        let fallbacks = Set(candidates.map(\.suggested_code))
        for candidate in candidates where result[candidate.id] == nil {
            let fallback = candidate.suggested_code
            let chosen: String
            if let existing = duplicate(candidate, in: phrases) {
                chosen = existing.code
            } else if candidate.duplicate {
                chosen = candidate.existing_code ?? fallback
            } else if let mnemonic = mnemonicCode(for: candidate.text, transform: transform),
                      !reserved.contains(mnemonic), !fallbacks.contains(mnemonic) || mnemonic == fallback {
                chosen = mnemonic
            } else {
                chosen = fallback
            }
            result[candidate.id] = chosen
            reserved.insert(chosen)
        }
        return result
    }
    static func normalizedText(_ text: String) -> String {
        text.trimmingCharacters(in: .whitespacesAndNewlines)
    }
    static func code(for candidate: PhraseDiscoveryCandidate, edits: [String: String]) -> String {
        (edits[candidate.id] ?? candidate.suggested_code).trimmingCharacters(in: .whitespacesAndNewlines)
    }
    static func duplicate(_ candidate: PhraseDiscoveryCandidate, in phrases: [Phrase]) -> Phrase? {
        phrases.first { normalizedText($0.text) == normalizedText(candidate.text) }
    }
    static func issue(for candidate: PhraseDiscoveryCandidate, candidates: [PhraseDiscoveryCandidate],
                      selected: Set<String>, edits: [String: String], phrases: [Phrase]) -> String? {
        if let existing = duplicate(candidate, in: phrases) { return "内容已在常用语列表中：\(existing.code)" }
        if candidate.duplicate { return "已保存的常用语已有相同内容：\(candidate.existing_code ?? "请刷新后核对")" }
        let code = code(for: candidate, edits: edits)
        if code.range(of: "^[a-z]{2,20}$", options: .regularExpression) == nil || code.hasPrefix("u") || code.hasPrefix("v") {
            return "短编码须为 2–20 位小写字母，避开 u、v 开头。"
        }
        if phrases.contains(where: { $0.code == code }) { return "短编码已被占用，请修改。" }
        if candidate.code_conflict && code == candidate.suggested_code.trimmingCharacters(in: .whitespacesAndNewlines) {
            return "原建议短编码已被占用，请修改。"
        }
        if candidates.contains(where: { $0.id != candidate.id && selected.contains($0.id) && Self.code(for: $0, edits: edits) == code }) {
            return "所选建议的短编码重复，请修改。"
        }
        return nil
    }
    static func additions(candidates: [PhraseDiscoveryCandidate], selected: Set<String>,
                          edits: [String: String], phrases: [Phrase]) throws -> [Phrase] {
        let chosen = candidates.filter { selected.contains($0.id) }
        guard !chosen.isEmpty else { throw LocalError(message: "请先勾选要加入的表达。") }
        guard chosen.count + phrases.count <= 300 else { throw LocalError(message: "常用语最多 300 条，请减少选择或移出已有条目。") }
        guard Set(chosen.map { normalizedText($0.text) }).count == chosen.count else {
            throw LocalError(message: "所选建议包含相同内容，请保留一条。")
        }
        for candidate in chosen {
            if let issue = issue(for: candidate, candidates: candidates, selected: selected, edits: edits, phrases: phrases) {
                throw LocalError(message: issue)
            }
        }
        return chosen.map { Phrase(code: code(for: $0, edits: edits), category: "发现", text: $0.text) }
    }
}
struct AppRule: Codable, Equatable, Identifiable {
    var bundle: String
    var english: Bool
    var id: String { bundle }
}
struct Preferences: Codable, Equatable {
    var theme = "existing"
    var font_size = 16
    var comment_size = 14
    var font_mode = "existing"
    var font_face = ""
    var preedit_mode = "existing"
    var gloss_language = "off"
    var gloss_overrides: [GlossaryEntry] = []
    var english_completion = "existing"
    var mixed_completion = "existing"
    var emoji_default = "existing"
    var layout = "horizontal"
    var density = "comfortable"
    var hotkey = "Control+Shift+k"
    var apps: [AppRule] = []
    var _original_schemes: [String: String]? = nil
    enum CodingKeys: String, CodingKey {
        case theme, font_size, comment_size, font_mode, font_face, preedit_mode, gloss_language, gloss_overrides
        case english_completion, mixed_completion, emoji_default
        case layout, density, hotkey, apps, _original_schemes
    }
    init() {}
    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        theme = try values.decodeIfPresent(String.self, forKey: .theme) ?? theme
        font_size = try values.decodeIfPresent(Int.self, forKey: .font_size) ?? font_size
        comment_size = try values.decodeIfPresent(Int.self, forKey: .comment_size) ?? comment_size
        font_mode = try values.decodeIfPresent(String.self, forKey: .font_mode) ?? font_mode
        font_face = try values.decodeIfPresent(String.self, forKey: .font_face) ?? font_face
        preedit_mode = try values.decodeIfPresent(String.self, forKey: .preedit_mode) ?? preedit_mode
        gloss_language = try values.decodeIfPresent(String.self, forKey: .gloss_language) ?? gloss_language
        gloss_overrides = try values.decodeIfPresent([GlossaryEntry].self, forKey: .gloss_overrides) ?? []
        english_completion = try values.decodeIfPresent(String.self, forKey: .english_completion) ?? "existing"
        mixed_completion = try values.decodeIfPresent(String.self, forKey: .mixed_completion) ?? "existing"
        emoji_default = try values.decodeIfPresent(String.self, forKey: .emoji_default) ?? "existing"
        layout = try values.decodeIfPresent(String.self, forKey: .layout) ?? layout
        density = try values.decodeIfPresent(String.self, forKey: .density) ?? density
        hotkey = try values.decodeIfPresent(String.self, forKey: .hotkey) ?? hotkey
        apps = try values.decodeIfPresent([AppRule].self, forKey: .apps) ?? apps
        _original_schemes = try values.decodeIfPresent([String: String].self, forKey: ._original_schemes)
    }
}
struct FontAppearance: Decodable { var font_face: String; var inline_preedit: Bool }
struct AppearanceBaseline: Decodable { var style: FontAppearance; var light: FontAppearance; var dark: FontAppearance }
struct InstalledFont: Identifiable {
    var name: String
    var displayName: String
    var familyName: String
    var id: String { name }
    var sample: NSFont { NSFont(name: name, size: 15) ?? .systemFont(ofSize: 15) }
    func matches(_ query: String) -> Bool {
        query.isEmpty || [name, displayName, familyName].contains { $0.localizedStandardContains(query) }
    }
}
enum CandidateFonts {
    // Font discovery stays in AppKit; no subprocess, network, or backend queue.
    static let installed: [InstalledFont] = NSFontManager.shared.availableFonts.compactMap { name in
        guard !name.hasPrefix("."), let font = NSFont(name: name, size: 15) else { return nil }
        return InstalledFont(name: font.fontName, displayName: font.displayName ?? name, familyName: font.familyName ?? name)
    }.sorted { $0.displayName.localizedStandardCompare($1.displayName) == .orderedAscending }
    static func resolve(_ name: String, size: CGFloat) -> NSFont? {
        if let font = NSFont(name: name, size: size) { return font }
        guard let match = installed.first(where: { item in
            [item.name, item.displayName, item.familyName].contains { $0.caseInsensitiveCompare(name) == .orderedSame }
        }) else { return nil }
        return NSFont(name: match.name, size: size)
    }
    static func faces(_ value: String) -> [String] {
        value.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
    }
    static func preview(_ value: String, size: CGFloat) -> NSFont {
        faces(value).compactMap { resolve($0, size: size) }.first ?? .systemFont(ofSize: size)
    }
}
struct Recorder: Decodable { var running: Bool }
struct ServiceState: Decodable { var kev_enabled: Bool; var recorder: Recorder; var demo: Bool }
struct Deployment: Decodable { var pending: Bool; var message: String }
struct Installation: Decodable { var packaged: Bool; var configured: Bool; var can_install: Bool }
struct PredictionState: Decodable {
    var enabled: Bool
    var installed: Bool
    var max_candidates: Int
    var max_iterations: Int
    var schema_id: String
    var schema_name: String?
}
struct GlossaryExample: Decodable, Identifiable {
    var text: String
    var original_comment: String
    var en_comment: String
    var ja_comment: String
    var id: String { text }
    func comment(for language: String) -> String {
        switch language {
        case "en": return en_comment
        case "ja": return ja_comment
        default: return original_comment
        }
    }
}
struct Glossary: Decodable {
    var count: Int
    var version: String
    var examples: [GlossaryExample]
    var base_count: Int?
    var term_count: Int?
    var override_count: Int?
    var entries: [GlossaryEntry]?
    var bundled_entries: [GlossaryEntry]?
}
struct InputTool: Decodable { var available: Bool; var active: Bool }
struct AppearanceTheme: Decodable, Identifiable {
    var id: String
    var name: String
    var description: String
    var light: [String: String]
    var dark: [String: String]

    // Older bundled helpers do not supply the shared catalog. Keep their original
    // three themes usable without duplicating the newer palettes in the UI.
    static let legacy: [AppearanceTheme] = [
        ("green", "青绿", "清爽的青绿色", "#0f766e", "#14b8a6"),
        ("blue", "海蓝", "明亮的蓝色", "#2563eb", "#60a5fa"),
        ("slate", "石墨", "克制的灰色", "#475569", "#94a3b8"),
    ].map { id, name, description, lightAccent, darkAccent in
        func palette(dark: Bool, accent: String) -> [String: String] {
            ["back_color": dark ? "#19232b" : "#f9fbfa",
             "text_color": dark ? "#dce6e5" : "#334155",
             "candidate_text_color": dark ? "#f1f5f9" : "#172d2b",
             "comment_text_color": dark ? "#a5b5b8" : "#667b7b",
             "label_color": dark ? "#9badb3" : "#728785",
             "hilited_candidate_back_color": accent,
             "hilited_candidate_text_color": dark ? "#102a2a" : "#ffffff",
             "hilited_comment_text_color": dark ? "#102a2a" : "#ffffff",
             "hilited_label_color": dark ? "#102a2a" : "#ffffff",
             "border_color": dark ? "#334348" : "#dce8e5"]
        }
        return AppearanceTheme(id: id, name: name, description: description,
                               light: palette(dark: false, accent: lightAccent),
                               dark: palette(dark: true, accent: darkAccent))
    }
    static let existing = AppearanceTheme(id: "existing", name: "保留当前",
        description: "恢复首次保存前的配色", light: [:], dark: [:])
}
struct ConsoleState: Decodable {
    var settings: Preferences
    var phrases: [Phrase]
    var revision: String
    var status: ServiceState
    var today: String
    var deployment: Deployment
    var installation: Installation?
    var prediction: PredictionState
    var appearance_themes: [AppearanceTheme]?
    var appearance_baseline: AppearanceBaseline?
    var glossary: Glossary?
    var input_tools: [String: InputTool]?
}
struct DayTotal: Decodable, Identifiable { var day: String; var chars: Int; var id: String { day } }
struct AppTotal: Decodable, Identifiable { var name: String; var chars: Int; var id: String { name } }
struct FingerTotal: Decodable, Identifiable { var name: String; var count: Int; var id: String { name } }
struct Segment: Decodable { var app: String; var time: String; var text: String }
struct KeySpec: Decodable {
    var key: String; var label: String; var width: Double; var finger: String
    init(from decoder: Decoder) throws {
        var row = try decoder.unkeyedContainer()
        key = try row.decode(String.self); label = try row.decode(String.self)
        width = try row.decode(Double.self); finger = try row.decode(String.self)
    }
}
struct KeyQuality: Decodable {
    var status: String; var reliable: Bool; var message: String; var scope: String
    var first_verified_minute: String?; var mapped_keys: Int; var unmapped_keys: Int
}
struct Report: Decodable {
    var day: String; var total_chars: Int; var segment_count: Int
    var active_minutes: Int?; var cpm: Double?; var total_keys: Int; var correction_rate: Double?
    var key_quality: KeyQuality
    var apps: [AppTotal]; var hours: [Int]; var trend: [DayTotal]; var calendar: [DayTotal]
    var key_frequency: [String: Int]; var fingers: [FingerTotal]; var keyboard: [[KeySpec]]
    var segments: [Segment]?; var segment_limit: Int
    var keyStatisticsNotice: String? {
        switch key_quality.status {
        case "legacy", "mixed": return "当天的按键记录可能不完整，部分统计暂不可用。"
        default: return nil
        }
    }
    var hourlyEmptyMessage: String {
        switch key_quality.status {
        case "legacy", "mixed": return "当天的按键记录不完整，暂不显示小时分布。"
        default: return "当天还没有按键记录。"
        }
    }
}
struct Backup: Decodable, Identifiable { var id: String; var created: String; var reason: String }
struct BackupList: Decodable { var backups: [Backup] }
struct Check: Decodable { var name: String? = nil; var level: String; var message: String }
struct CheckSummary: Identifiable {
    var id: String
    var title: String
    var level: String
    var message: String
}
enum HealthPresentation {
    private static func group(for name: String?) -> String {
        switch name {
        case "recorder", "key_capture": return "record"
        case "kev_switch", "kev_http", "kev_agent": return "ai"
        case "deployed_schema", "glossary_overrides": return "input"
        default: return name?.hasSuffix(".lua") == true ? "input" : "other"
        }
    }
    private static func severity(_ level: String) -> Int {
        switch level {
        case "ok": return 0
        case "error": return 2
        default: return 1
        }
    }
    static func summaries(_ checks: [Check], kevEnabled: Bool) -> [CheckSummary] {
        let grouped = Dictionary(grouping: checks) { group(for: $0.name) }
        let groups = [("record", "输入记录"), ("input", "输入法配置"), ("ai", "AI 建议"), ("other", "其他检查")]
        return groups.compactMap { id, title in
            guard let items = grouped[id], !items.isEmpty else { return nil }
            let rank = items.map { severity($0.level) }.max() ?? 0
            let level = rank == 2 ? "error" : rank == 1 ? "warning" : "ok"
            let message: String
            if level == "error" {
                message = "需要处理"
            } else if level == "warning" {
                message = "需要检查"
            } else if id == "ai" && !kevEnabled {
                message = "已关闭"
            } else if id == "ai" && items.contains(where: { $0.name == "kev_http" && $0.level == "ok" }) {
                message = "服务可用"
            } else {
                message = "检查通过"
            }
            return CheckSummary(id: id, title: title, level: level, message: message)
        }
    }
}
struct Health: Decodable { var checks: [Check] }
struct Outcome: Decodable { var message: String }
struct Envelope<T: Decodable>: Decodable { var ok: Bool; var data: T?; var error: String? }
struct LocalError: LocalizedError { var message: String; var errorDescription: String? { message } }

enum Screen: String, CaseIterable, Identifiable {
    case dashboard, phrases, appearance, settings, backups
    var id: Self { self }
    var title: String {
        switch self {
        case .dashboard: return "输入看板"
        case .phrases: return "常用语"
        case .appearance: return "候选外观"
        case .settings: return "输入设置"
        case .backups: return "备份与状态"
        }
    }
    var icon: String {
        switch self {
        case .dashboard: return "chart.bar.xaxis"
        case .phrases: return "text.alignleft"
        case .appearance: return "paintpalette"
        case .settings: return "keyboard"
        case .backups: return "clock.arrow.circlepath"
        }
    }
}

/// A single serial worker exchanges JSON through private pipes. No HTTP server is started.
// Requests mutate state on queue; start/stop additionally protect lifecycle with lock.
final class NativeBridge: @unchecked Sendable {
    static let shared = NativeBridge()
    private let queue = DispatchQueue(label: "local.keytrack.console.bridge", qos: .userInitiated)
    private let lock = NSLock()
    private var process: Process?
    private var input: FileHandle?
    private var output: FileHandle?
    private var buffer = Data()

    private func start() throws {
        lock.lock(); defer { lock.unlock() }
        if process?.isRunning == true { return }
        let helper = Bundle.main.bundleURL.appendingPathComponent("Contents/Resources/keytrack-runtime/keytrack-helper")
        guard FileManager.default.isExecutableFile(atPath: helper.path) else { throw LocalError(message: "应用运行组件缺失，请重新安装 Keytrack。") }
        let child = Process(), incoming = Pipe(), outgoing = Pipe()
        child.executableURL = helper
        child.arguments = ["console-native"]
        if CommandLine.arguments.contains("--demo") { child.arguments?.append("--demo") }
        child.currentDirectoryURL = helper.deletingLastPathComponent()
        var environment = ProcessInfo.processInfo.environment
        environment.removeValue(forKey: "PYTHONHOME"); environment.removeValue(forKey: "PYTHONPATH")
        environment["PYTHONUNBUFFERED"] = "1"
        child.environment = environment
        child.standardInput = incoming; child.standardOutput = outgoing; child.standardError = FileHandle.nullDevice
        try child.run()
        process = child; input = incoming.fileHandleForWriting; output = outgoing.fileHandleForReading
        buffer.removeAll()
    }
    func request<T: Decodable>(_ action: String, _ fields: [String: Any] = [:], as type: T.Type = T.self) async throws -> T {
        try await withCheckedThrowingContinuation { continuation in
            queue.async {
                do {
                    try self.start()
                    var body = fields; body["action"] = action
                    var bytes = try JSONSerialization.data(withJSONObject: body)
                    guard bytes.count < 4_500_000 else { throw LocalError(message: "内容超过保存上限。") }
                    bytes.append(10)
                    try self.input?.write(contentsOf: bytes)
                    while !self.buffer.contains(10) {
                        guard let received = self.output?.availableData, !received.isEmpty else {
                            throw LocalError(message: "本地服务连接中断，请刷新重试。")
                        }
                        self.buffer.append(received)
                        guard self.buffer.count < 12_000_000 else { throw LocalError(message: "返回内容过大，请缩小查询范围。") }
                    }
                    let newline = self.buffer.firstIndex(of: 10)!
                    let line = Data(self.buffer.prefix(upTo: newline))
                    self.buffer.removeSubrange(...newline)
                    let reply = try JSONDecoder().decode(Envelope<T>.self, from: line)
                    guard reply.ok, let value = reply.data else { throw LocalError(message: reply.error ?? "操作未完成。") }
                    continuation.resume(returning: value)
                } catch { continuation.resume(throwing: error) }
            }
        }
    }
    func stop() {
        lock.lock(); defer { lock.unlock() }
        try? input?.close()
        if process?.isRunning == true { process?.terminate() }
    }
}

@MainActor final class ConsoleModel: ObservableObject {
    @Published var screen: Screen = .dashboard
    @Published var state: ConsoleState?
    @Published var report: Report?
    @Published var preferences = Preferences()
    @Published var phrases: [Phrase] = []
    @Published var backups: [Backup] = []
    @Published var checks: [Check] = []
    @Published var selectedDate = Date()
    @Published var busy = false
    @Published var notice = ""
    @Published var error: String?
    @Published var showText = false
    @Published var discoveryDays = 30
    @Published var phraseDiscovery: PhraseDiscoveryReport?
    @Published var discoverySelected: Set<String> = []
    @Published var discoveryCodes: [String: String] = [:]
    @Published var phraseImport: PhraseImportReport?
    @Published var importSelected: Set<String> = []
    @Published var showPhraseImport = false
    let bridge = NativeBridge.shared
    var dirty: Bool { guard let state else { return false }; return preferences != state.settings || phrases != state.phrases }
    static let dayFormat: DateFormatter = {
        let format = DateFormatter(); format.dateFormat = "yyyy-MM-dd"
        format.locale = Locale(identifier: "en_US_POSIX"); format.timeZone = TimeZone(identifier: "Asia/Shanghai")
        return format
    }()
    var day: String { Self.dayFormat.string(from: selectedDate) }
    func select(_ next: Screen) {
        if dirty && !([Screen.appearance, .settings].contains(screen) && [Screen.appearance, .settings].contains(next)) && next != screen {
            error = "当前修改尚未保存。请先保存，或点击“放弃修改”。"; return
        }
        screen = next
    }
    func operation(_ work: @escaping () async throws -> Void) {
        guard !busy else { return }
        busy = true; notice = ""
        Task {
            defer { busy = false }
            do { try await work() } catch { self.error = error.localizedDescription }
        }
    }
    func load() {
        if dirty { error = "请先保存或放弃修改，再刷新。"; return }
        operation { try await self.reload() }
    }
    private func reload() async throws {
        let latest: ConsoleState = try await bridge.request("state")
        if state == nil { selectedDate = Self.dayFormat.date(from: latest.today) ?? Date() }
        let summary: Report = try await bridge.request("report", ["day": day, "text": false])
        let versions: BackupList = try await bridge.request("backups")
        let health: Health = try await bridge.request("doctor")
        state = latest; preferences = latest.settings; phrases = latest.phrases
        report = summary; backups = versions.backups; checks = health.checks; showText = false
    }
    func changeDate(_ date: Date) {
        selectedDate = date; showText = false
        operation { self.report = try await self.bridge.request("report", ["day": self.day, "text": false]) }
    }
    func toggleText() {
        if showText { showText = false; report?.segments = nil; return }
        operation {
            self.report = try await self.bridge.request("report", ["day": self.day, "text": true])
            self.showText = true
        }
    }
    func discard() {
        guard let state else { return }
        preferences = state.settings; phrases = state.phrases
        discoverySelected.removeAll(); clearPhraseImport(); notice = "已放弃未保存的修改"
    }
    func analyzePhraseHistory() {
        let days = discoveryDays
        operation {
            let report: PhraseDiscoveryReport = try await self.bridge.request("phrase_discovery", ["days": days])
            let phrases = self.phrases, codes = self.discoveryCodes
            let initial = await Task.detached(priority: .userInitiated) {
                PhraseDiscoverySelection.initialCodes(candidates: report.candidates, phrases: phrases, edits: codes)
            }.value
            self.discoveryCodes = initial
            self.phraseDiscovery = report
            self.discoverySelected.removeAll()
        }
    }
    func clearPhraseDiscovery() {
        phraseDiscovery = nil; discoverySelected.removeAll(); discoveryCodes.removeAll()
    }
    func discoveryIssue(_ candidate: PhraseDiscoveryCandidate) -> String? {
        PhraseDiscoverySelection.issue(for: candidate, candidates: phraseDiscovery?.candidates ?? [],
                                       selected: discoverySelected, edits: discoveryCodes, phrases: phrases)
    }
    var discoveryCanAdd: Bool {
        guard let report = phraseDiscovery else { return false }
        return (try? PhraseDiscoverySelection.additions(candidates: report.candidates, selected: discoverySelected,
                                                       edits: discoveryCodes, phrases: phrases)) != nil
    }
    func addDiscoveredPhrases() {
        guard let report = phraseDiscovery else { return }
        do {
            let additions = try PhraseDiscoverySelection.additions(candidates: report.candidates, selected: discoverySelected,
                                                                   edits: discoveryCodes, phrases: phrases)
            phrases.append(contentsOf: additions); discoverySelected.removeAll()
            notice = "已加入 \(additions.count) 条待保存常用语，点击“保存并应用”后生效。"
        } catch { self.error = error.localizedDescription }
    }
    func rejectDiscoveredPhrases(_ ids: [String]) {
        guard !ids.isEmpty else { return }
        operation {
            let result: PhraseDiscoveryRejection = try await self.bridge.request("phrase_discovery_reject", ["ids": ids])
            self.applyDiscoveryRejection(result)
        }
    }
    func applyDiscoveryRejection(_ result: PhraseDiscoveryRejection) {
        let rejected = Set(result.rejected_ids)
        phraseDiscovery?.candidates.removeAll { rejected.contains($0.id) }
        phraseDiscovery?.rejected_count = result.rejected_count
        discoverySelected.subtract(rejected)
        discoveryCodes = discoveryCodes.filter { !rejected.contains($0.key) }
        notice = result.message
    }
    var importCanAdd: Bool {
        guard let report = phraseImport else { return false }
        return (try? PhraseImportSelection.additions(report, selected: importSelected, existing: phrases)) != nil
    }
    func clearPhraseImport() {
        phraseImport = nil; importSelected.removeAll(); showPhraseImport = false
    }
    func importPhrases() {
        guard !busy else { return }
        let panel = NSOpenPanel()
        panel.title = "导入常用语，先预览再加入"
        panel.allowedContentTypes = [.json, UTType(filenameExtension: "tsv") ?? .plainText]
        panel.allowsMultipleSelection = false; panel.canChooseDirectories = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        let format = url.pathExtension.lowercased() == "json" ? "json" : "tsv"
        operation {
            let content = try await Task.detached(priority: .userInitiated) { try SelectedTextFile.read(url) }.value
            let items = try JSONSerialization.jsonObject(with: JSONEncoder().encode(self.phrases))
            self.phraseImport = try await self.bridge.request("phrase_import_preview", ["content": content, "format": format, "existing": items])
            self.importSelected.removeAll(); self.showPhraseImport = true
        }
    }
    func addImportedPhrases() {
        guard let report = phraseImport else { return }
        do {
            let additions = try PhraseImportSelection.additions(report, selected: importSelected, existing: phrases)
            phrases.append(contentsOf: additions); clearPhraseImport()
            notice = "已加入 \(additions.count) 条待保存常用语，点击“保存并应用”后生效。"
        } catch { self.error = error.localizedDescription }
    }
    func exportPhrases(format: String) {
        guard !busy else { return }
        let panel = NSSavePanel(); panel.title = "导出当前常用语列表"
        panel.nameFieldStringValue = "Keytrack-常用语.\(format)"
        panel.allowedContentTypes = [format == "json" ? .json : UTType(filenameExtension: "tsv") ?? .plainText]
        guard panel.runModal() == .OK, let url = panel.url else { return }
        operation {
            let items = try JSONSerialization.jsonObject(with: JSONEncoder().encode(self.phrases))
            let result: PhraseExport = try await self.bridge.request("phrase_export", ["phrases": items, "format": format])
            try result.content.write(to: url, atomically: true, encoding: .utf8)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
            self.notice = "已导出当前列表\(self.dirty ? "（包含未保存草稿）" : "")：\(url.lastPathComponent)"
        }
    }
    func chooseApplication() {
        let panel = NSOpenPanel(); panel.title = "选择应用"
        panel.allowedContentTypes = [.applicationBundle]; panel.canChooseDirectories = false
        panel.directoryURL = URL(fileURLWithPath: "/Applications")
        guard panel.runModal() == .OK, let url = panel.url, let bundle = Bundle(url: url), let id = bundle.bundleIdentifier else { return }
        guard preferences.apps.count < 30 else { error = "应用规则最多 30 项。"; return }
        guard !preferences.apps.contains(where: { $0.bundle == id }) else { error = "这个应用已有默认语言规则。"; return }
        preferences.apps.append(AppRule(bundle: id, english: true))
        notice = "已加入应用规则草稿，请选择默认语言并保存。"
    }
    func save() {
        guard let state else { return }
        operation {
            let action = self.screen == .phrases ? "phrases" : "settings"
            let encoded = try JSONEncoder().encode(action == "phrases" ? NativePayload.phrases(self.phrases) : NativePayload.settings(self.preferences))
            let value = try JSONSerialization.jsonObject(with: encoded)
            let field = action == "phrases" ? "phrases" : "settings"
            let result: Outcome = try await self.bridge.request(action, [field: value, "revision": state.revision])
            try await self.reload(); self.discoverySelected.removeAll(); self.notice = result.message
        }
    }
    func action(_ name: String, fields: [String: Any] = [:]) {
        if dirty { error = "请先保存或放弃修改。"; return }
        operation {
            var payload = fields
            if name == "restore" { payload["revision"] = self.state?.revision ?? "" }
            let result: Outcome = try await self.bridge.request(name, payload)
            try await self.reload(); self.notice = result.message
        }
    }
    func updatePrediction(enabled: Bool? = nil, candidates: Int? = nil) {
        guard let prediction = state?.prediction else { return }
        action("prediction", fields: ["enabled": enabled ?? prediction.enabled,
                                     "max_candidates": candidates ?? prediction.max_candidates,
                                     "max_iterations": 1])
    }
}
private enum NativePayload: Encodable {
    case phrases([Phrase]), settings(Preferences)
    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .phrases(let items): try container.encode(items)
        case .settings(let settings): try container.encode(settings)
        }
    }
}
