// Compile alongside macos/ConsoleModel.swift. Only synthetic rows and files in
// /private/tmp are used. No bridge request, real settings, history, or UI panel.
import Foundation
import AppKit
import Darwin

@main struct MsimeModelChecks {
    @MainActor static func main() throws {
        var checks = 0
        func check(_ condition: Bool, _ message: String = "Native optimization model assertion failed") {
            precondition(condition, message)
            checks += 1
        }
        func rejects(_ work: () throws -> Void) {
            do {
                try work()
                preconditionFailure("Expected safe rejection")
            } catch let error as LocalError {
                check(!error.message.isEmpty)
            } catch {
                preconditionFailure("Expected a local, user-readable rejection: \(error)")
            }
        }
        func row(_ id: String, _ code: String, _ text: String, status: String = "new", category: String = "测试") -> PhraseImportRow {
            PhraseImportRow(id: id, code: code, text: text, category: category, status: status, message: "Synthetic fixture")
        }
        func report(_ rows: [PhraseImportRow]) -> PhraseImportReport {
            PhraseImportReport(rows: rows, counts: ["total": rows.count, "new": rows.filter { $0.status == "new" }.count])
        }
        let first = row("first", "qsample", "请确认样品", category: "样品")
        let second = row("second", "qdelivery", "请确认交期", category: "交付")
        let mixed = report([first, row("duplicate", "qold", "已有表达", status: "duplicate"),
                            row("conflict", "qconflict", "冲突表达", status: "conflict"),
                            row("invalid", "bad", "非法表达", status: "invalid"), second])
        let accepted = try PhraseImportSelection.additions(mixed, selected: ["second", "first"], existing: [])
        check(accepted == [Phrase(code: "qsample", category: "样品", text: "请确认样品"),
                           Phrase(code: "qdelivery", category: "交付", text: "请确认交期")])
        check(mixed.rows.count == 5 && mixed.rows[0].status == "new")
        for status in ["duplicate", "conflict", "invalid"] {
            rejects { _ = try PhraseImportSelection.additions(mixed, selected: ["first", status], existing: []) }
        }
        rejects { _ = try PhraseImportSelection.additions(mixed, selected: [], existing: []) }
        rejects { _ = try PhraseImportSelection.additions(mixed, selected: ["first", "stale-id"], existing: []) }
        rejects { _ = try PhraseImportSelection.additions(report([first, row("first", "qother", "另一表达")]),
                                                          selected: ["first"], existing: []) }
        rejects { _ = try PhraseImportSelection.additions(report([first, row("same-code", first.code, "不同表达")]),
                                                          selected: ["first", "same-code"], existing: []) }
        rejects { _ = try PhraseImportSelection.additions(report([first, row("same-text", "qother", first.text)]),
                                                          selected: ["first", "same-text"], existing: []) }
        let occupiedCode = [Phrase(code: first.code, category: "后来编辑", text: "新的草稿内容")]
        let occupiedText = [Phrase(code: "qoccupied", category: "后来编辑", text: first.text)]
        rejects { _ = try PhraseImportSelection.additions(report([first]), selected: ["first"], existing: occupiedCode) }
        rejects { _ = try PhraseImportSelection.additions(report([first]), selected: ["first"], existing: occupiedText) }
        check(occupiedCode[0].text == "新的草稿内容" && occupiedText[0].code == "qoccupied")
        let legacyDuplicates = [Phrase(code: "qlegacyone", category: "旧分类一", text: "已有表达"),
                                Phrase(code: "qlegacytwo", category: "旧分类二", text: "已有表达")]
        check(try PhraseImportSelection.additions(report([first]), selected: ["first"], existing: legacyDuplicates) == [accepted[0]])
        let spaced = row("spaced", "qspaced", "原话 ")
        let original = row("original", "qoriginal", "原话")
        let spacePair = try PhraseImportSelection.additions(report([original, spaced]), selected: ["original", "spaced"], existing: [])
        check(spacePair.map(\.text) == ["原话", "原话 "])
        check(try PhraseImportSelection.additions(report([spaced]), selected: ["spaced"],
                                                 existing: [Phrase(code: "qold", category: "旧", text: "原话")])[0].text == "原话 ")
        let full = (0..<300).map { Phrase(code: "qfixture\($0)", category: "测试", text: "已有条目\($0)") }
        check(try PhraseImportSelection.additions(report([first]), selected: ["first"], existing: Array(full.prefix(299))).count == 1)
        rejects { _ = try PhraseImportSelection.additions(report([first]), selected: ["first"], existing: full) }
        rejects { _ = try PhraseImportSelection.additions(report([first, second]), selected: ["first", "second"],
                                                          existing: Array(full.prefix(299))) }

        let directory = URL(fileURLWithPath: "/private/tmp/keytrack-msime-model-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: directory) }
        let textFile = directory.appendingPathComponent("多行 样例.tsv")
        let text = "code\ttext\tcategory\nqsample\t请确认样品\t样品\nqdelivery\t第一行\\n第二行\t交付\n"
        try Data(text.utf8).write(to: textFile)
        check(try SelectedTextFile.read(textFile) == text)
        check(try Data(contentsOf: textFile) == Data(text.utf8))
        let invalidUTF8 = directory.appendingPathComponent("invalid.json")
        try Data([0xc3, 0x28]).write(to: invalidUTF8)
        rejects { _ = try SelectedTextFile.read(invalidUTF8) }
        try Data([0xed, 0xa0, 0x80]).write(to: invalidUTF8)
        rejects { _ = try SelectedTextFile.read(invalidUTF8) }
        let large = directory.appendingPathComponent("large.tsv")
        try Data(repeating: 0x61, count: 2_000_000).write(to: large)
        check(try SelectedTextFile.read(large).utf8.count == 2_000_000)
        try Data(repeating: 0x61, count: 2_000_001).write(to: large)
        rejects { _ = try SelectedTextFile.read(large) }
        check(try Data(contentsOf: large).count == 2_000_001)
        let fifo = directory.appendingPathComponent("pipe.tsv")
        check(fifo.path.withCString { Darwin.mkfifo($0, mode_t(0o600)) } == 0)
        rejects { _ = try SelectedTextFile.read(fifo) }
        let link = directory.appendingPathComponent("link.tsv")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: textFile)
        rejects { _ = try SelectedTextFile.read(link) }
        check(try Data(contentsOf: textFile) == Data(text.utf8))
        rejects { _ = try SelectedTextFile.read(directory) }

        let decoder = JSONDecoder(), encoder = JSONEncoder()
        let legacy = try decoder.decode(Preferences.self, from: Data("{\"theme\":\"blue\",\"font_size\":20,\"apps\":[{\"bundle\":\"test.Editor\",\"english\":false}]}".utf8))
        check(legacy.theme == "blue" && legacy.font_size == 20 && legacy.apps[0].bundle == "test.Editor")
        check(legacy.gloss_language == "off" && legacy.gloss_overrides.isEmpty)
        check(legacy.english_completion == "existing" && legacy.mixed_completion == "existing" && legacy.emoji_default == "existing")
        let nullFields = try decoder.decode(Preferences.self, from: Data("{\"gloss_overrides\":null,\"english_completion\":null,\"mixed_completion\":null,\"emoji_default\":null}".utf8))
        check(nullFields.gloss_overrides.isEmpty && nullFields.english_completion == "existing"
              && nullFields.mixed_completion == "existing" && nullFields.emoji_default == "existing")
        var saved = legacy
        saved.gloss_language = "ja"
        saved.gloss_overrides = [GlossaryEntry(word: "样品", en: "sample", ja: "サンプル", reading: "")]
        saved.english_completion = "on"; saved.mixed_completion = "off"; saved.emoji_default = "on"
        let encoded = try encoder.encode(saved)
        check(try decoder.decode(Preferences.self, from: encoded) == saved)
        let savedObject = try JSONSerialization.jsonObject(with: encoded) as! [String: Any]
        check(savedObject["english_completion"] as? String == "on" && savedObject["mixed_completion"] as? String == "off")
        check((savedObject["gloss_overrides"] as? [[String: Any]])?[0]["reading"] as? String == "")
        let baseState: [String: Any] = ["settings": savedObject, "phrases": [["code": "qexisting", "text": "已有表达", "category": "旧"]],
            "revision": "synthetic-revision", "today": "2026-10-03",
            "status": ["demo": true, "kev_enabled": false, "recorder": ["running": true]],
            "deployment": ["pending": false, "message": "Synthetic fixture"],
            "prediction": ["enabled": false, "installed": true, "max_candidates": 3, "max_iterations": 1, "schema_id": "fixture"],
            "glossary": ["count": 2, "version": "synthetic", "examples": [],
                         "entries": [["word": "样品", "en": "sample", "ja": "サンプル", "reading": ""]],
                         "bundled_entries": [["word": "样品", "en": "sample", "ja": "サンプル", "reading": ""],
                                             ["word": "模具", "en": "mold", "ja": "金型", "reading": ""]]]]
        let state = try decoder.decode(ConsoleState.self, from: JSONSerialization.data(withJSONObject: baseState))
        check(state.glossary?.bundled_entries?.count == 2 && state.glossary?.entries?.count == 1)
        let model = ConsoleModel()
        model.state = state; model.preferences = state.settings; model.phrases = state.phrases
        check(!model.dirty && !model.busy)
        model.preferences.gloss_overrides[0].en = "custom sample"
        check(model.dirty && model.state?.settings.gloss_overrides[0].en == "sample")
        model.preferences.gloss_overrides.append(GlossaryEntry(word: "模具", en: "tooling", ja: "金型", reading: "かながた"))
        check(model.dirty && model.preferences.gloss_overrides.count == 2)
        model.discard()
        check(!model.dirty && model.preferences == saved && model.phrases == state.phrases)
        model.preferences.gloss_overrides.removeAll()
        check(model.dirty && model.state?.settings.gloss_overrides.count == 1)
        model.preferences.english_completion = "off"; model.preferences.emoji_default = "off"
        model.discard()
        check(!model.dirty && model.preferences.english_completion == "on" && model.preferences.emoji_default == "on")
        model.phraseImport = report([first]); model.importSelected = ["first"]; model.showPhraseImport = true
        check(model.importCanAdd)
        model.addImportedPhrases()
        check(model.dirty && model.phrases.last == accepted[0] && model.phrases.count == state.phrases.count + 1)
        check(model.phraseImport == nil && model.importSelected.isEmpty && !model.showPhraseImport)
        model.discard()
        check(!model.dirty && model.phrases == state.phrases && model.preferences == saved)
        model.phraseImport = report([first]); model.importSelected = ["first"]
        model.phrases.append(Phrase(code: first.code, category: "新草稿", text: "后来占用"))
        check(!model.importCanAdd)
        let beforeFailedAdd = model.phrases
        model.addImportedPhrases()
        check(model.phrases == beforeFailedAdd && model.error != nil && model.phraseImport != nil)
        model.discard()
        check(!model.dirty && model.phraseImport == nil && model.importSelected.isEmpty && !model.busy)
        print("Native optimization model checks passed: \(checks) assertions; synthetic files only; no bridge or settings operations.")
    }
}
