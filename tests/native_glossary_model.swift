// Compile with macos/ConsoleModel.swift. These public-word fixtures never start
// NativeBridge, analyze history, access a network service, or write settings.
import Foundation
import AppKit

@main struct GlossaryModelChecks {
    @MainActor static func main() throws {
        var checks = 0
        func check(_ condition: @autoclosure () -> Bool) {
            precondition(condition(), "Native glossary model assertion failed")
            checks += 1
        }
        let decoder = JSONDecoder(), encoder = JSONEncoder()
        let defaults = Preferences()
        check(defaults.gloss_language == "off")
        let old = try decoder.decode(Preferences.self, from: Data("{\"theme\":\"blue\",\"font_size\":20,\"preedit_mode\":\"candidate\"}".utf8))
        check(old.gloss_language == "off")
        check(old.theme == "blue" && old.font_size == 20 && old.preedit_mode == "candidate")
        let null = try decoder.decode(Preferences.self, from: Data("{\"gloss_language\":null}".utf8))
        check(null.gloss_language == "off")
        let encodedDefaults = try JSONSerialization.jsonObject(with: encoder.encode(defaults)) as! [String: Any]
        check(encodedDefaults["gloss_language"] as? String == "off")
        for language in ["off", "en", "ja"] {
            let loaded = try decoder.decode(Preferences.self, from: Data("{\"gloss_language\":\"\(language)\"}".utf8))
            check(loaded.gloss_language == language)
            let encoded = try JSONSerialization.jsonObject(with: encoder.encode(loaded)) as! [String: Any]
            check(encoded["gloss_language"] as? String == language)
            let roundTrip = try decoder.decode(Preferences.self, from: encoder.encode(loaded))
            check(roundTrip == loaded)
        }
        let oldStateJSON = """
        {"settings":{},"phrases":[],"revision":"synthetic-revision","today":"2026-10-03",
         "status":{"demo":true,"kev_enabled":false,"recorder":{"running":true}},
         "deployment":{"pending":false,"message":"Synthetic fixture"},
         "prediction":{"enabled":false,"installed":true,"max_candidates":3,"max_iterations":1,"schema_id":"fixture"}}
        """
        let legacy = try decoder.decode(ConsoleState.self, from: Data(oldStateJSON.utf8))
        check(legacy.settings.gloss_language == "off" && legacy.glossary == nil)
        var stateObject = try JSONSerialization.jsonObject(with: Data(oldStateJSON.utf8)) as! [String: Any]
        stateObject["glossary"] = [
            "count": 3,
            "version": "synthetic-glossary-v1",
            "examples": [
                ["text": "你好", "original_comment": "", "en_comment": "hello", "ja_comment": "こんにちは"],
                ["text": "谢谢", "original_comment": "同音", "en_comment": "同音 · thanks", "ja_comment": "同音 · ありがとう"],
                ["text": "确认", "original_comment": "联想 · ✦ AI · 数字/Tab",
                 "en_comment": "联想 · ✦ AI · 数字/Tab · confirm",
                 "ja_comment": "联想 · ✦ AI · 数字/Tab · 確認（かくにん）"],
            ],
        ]
        let latest = try decoder.decode(ConsoleState.self, from: JSONSerialization.data(withJSONObject: stateObject))
        let glossary = latest.glossary!
        check(glossary.count == 3 && glossary.version == "synthetic-glossary-v1")
        check(glossary.examples.map(\.text) == ["你好", "谢谢", "确认"])
        check(glossary.examples[0].comment(for: "en") == "hello")
        check(glossary.examples[0].comment(for: "ja") == "こんにちは")
        check(glossary.examples[2].comment(for: "en") == "联想 · ✦ AI · 数字/Tab · confirm")
        check(glossary.examples[2].comment(for: "ja") == "联想 · ✦ AI · 数字/Tab · 確認（かくにん）")
        check(glossary.examples[2].comment(for: "off") == "联想 · ✦ AI · 数字/Tab")
        check(glossary.examples[2].comment(for: "unknown") == glossary.examples[2].original_comment)
        let model = ConsoleModel()
        model.state = latest
        model.preferences = latest.settings
        check(!model.dirty && model.preferences.gloss_language == "off")
        model.screen = .settings
        model.preferences.gloss_language = "en"
        check(model.dirty && model.phrases == latest.phrases)
        let settingsPayload = try JSONSerialization.jsonObject(with: encoder.encode(model.preferences)) as! [String: Any]
        check(settingsPayload["gloss_language"] as? String == "en")
        check(settingsPayload["theme"] as? String == latest.settings.theme)
        check(model.state!.settings.gloss_language == "off")
        model.preferences.gloss_language = "ja"
        check(model.dirty)
        let japanesePayload = try JSONSerialization.jsonObject(with: encoder.encode(model.preferences)) as! [String: Any]
        check(japanesePayload["gloss_language"] as? String == "ja")
        model.discard()
        check(!model.dirty && model.preferences.gloss_language == "off")
        model.state = legacy
        model.preferences = legacy.settings
        check(model.state?.glossary == nil && !model.dirty)
        print("Native glossary model checks passed: \(checks) assertions; fixtures only; no service or settings operations.")
    }
}
