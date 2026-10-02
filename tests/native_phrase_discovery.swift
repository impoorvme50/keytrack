// Compile with macos/ConsoleModel.swift. All records below are synthetic; this
// test never starts NativeBridge, queries history, or accesses Rime settings.
import Foundation
import AppKit

@main struct PhraseDiscoveryChecks {
    @MainActor static func main() throws {
        var checks = 0
        func check(_ value: @autoclosure () -> Bool) {
            precondition(value(), "Native phrase discovery assertion failed")
            checks += 1
        }
        func rejected(_ work: () throws -> Void) {
            do { try work(); preconditionFailure("Invalid selection was accepted") }
            catch { checks += 1 }
        }
        let reportJSON = """
        {"days":30,"start_day":"2026-09-04","end_day":"2026-10-03",
         "scanned_segments":12,"truncated":false,"message":"Synthetic fixture",
         "batch_basis":"Synthetic independent recording batches","rejected_count":1,"revision":"r1",
         "candidates":[
          {"id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","text":"第一行测试表达\\n第二行测试表达","count":5,"batch_count":3,"suggested_code":"qsample","duplicate":false,"code_conflict":false,"existing_code":null},
          {"id":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","text":"另一条合成测试表达","count":3,"batch_count":2,"suggested_code":"qreply","duplicate":false,"code_conflict":true,"existing_code":null},
          {"id":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","text":"已经保存的合成表达","count":4,"batch_count":2,"suggested_code":"qexisting","duplicate":true,"code_conflict":false,"existing_code":"qexisting"}
        ]}
        """
        let report = try JSONDecoder().decode(PhraseDiscoveryReport.self, from: Data(reportJSON.utf8))
        let first = report.candidates[0], second = report.candidates[1], third = report.candidates[2]
        check(report.days == 30 && report.scanned_segments == 12 && report.candidates.count == 3)
        check(first.text == "第一行测试表达\n第二行测试表达")
        check(first.batch_count == 3 && second.code_conflict && third.existing_code == "qexisting")
        check(PhraseDiscoverySelection.mnemonicCode(for: "今天下午确认样品") == "qjtxwqr")
        check(PhraseDiscoverySelection.mnemonicCode(for: "谢谢配合") == "qxxph")
        check(PhraseDiscoverySelection.mnemonicCode(for: "Only synthetic English words") == nil)
        check(PhraseDiscoverySelection.mnemonicCode(for: "谢谢") == nil)
        check(PhraseDiscoverySelection.mnemonicCode(for: "今天下午确认样品", transform: { _ in nil }) == nil)
        check(PhraseDiscoverySelection.mnemonicCode(for: "今天下午确认样品", transform: { $0 }) == nil)
        var mnemonicFirst = first, mnemonicSecond = second
        mnemonicFirst.text = "今天下午确认样品"
        mnemonicFirst.suggested_code = "qfallbackfirst"
        mnemonicSecond.text = "今天下午确认结果"
        mnemonicSecond.suggested_code = "qfallbacksecond"
        let mnemonicCandidates = [mnemonicFirst, mnemonicSecond]
        let initialCodes = PhraseDiscoverySelection.initialCodes(candidates: mnemonicCandidates, phrases: [], edits: [:])
        check(initialCodes[first.id] == "qjtxwqr")
        check(initialCodes[second.id] == "qfallbacksecond")
        let conflictCodes = PhraseDiscoverySelection.initialCodes(candidates: mnemonicCandidates,
            phrases: [Phrase(code: "qjtxwqr", category: "测试", text: "另一条已保存的合成表达")], edits: [:])
        check(conflictCodes[first.id] == "qfallbackfirst" && conflictCodes[second.id] == "qfallbacksecond")
        let preservedEdits = PhraseDiscoverySelection.initialCodes(candidates: mnemonicCandidates, phrases: [],
            edits: [first.id: " qcustomedit ", "obsolete": "qobsolete"])
        check(preservedEdits[first.id] == " qcustomedit " && preservedEdits["obsolete"] == "qobsolete")
        check(preservedEdits[second.id] == "qjtxwqr")
        let failedCodes = PhraseDiscoverySelection.initialCodes(candidates: mnemonicCandidates, phrases: [], edits: [:], transform: { _ in nil })
        check(failedCodes[first.id] == "qfallbackfirst" && failedCodes[second.id] == "qfallbacksecond")
        let unchangedCodes = PhraseDiscoverySelection.initialCodes(candidates: mnemonicCandidates, phrases: [], edits: [:], transform: { $0 })
        check(unchangedCodes[first.id] == "qfallbackfirst" && unchangedCodes[second.id] == "qfallbacksecond")
        let duplicateCodes = PhraseDiscoverySelection.initialCodes(candidates: [third], phrases: [], edits: [:])
        check(duplicateCodes[third.id] == "qexisting")
        var fallbackCollision = mnemonicSecond
        fallbackCollision.suggested_code = "qjtxwqr"
        let reservedFallback = PhraseDiscoverySelection.initialCodes(candidates: [mnemonicFirst, fallbackCollision], phrases: [], edits: [:])
        check(reservedFallback[first.id] == "qfallbackfirst")
        let model = ConsoleModel()
        check(model.discoveryDays == 30 && model.phraseDiscovery == nil && !model.busy)
        let existing = [Phrase(code: "qexisting", category: "常用", text: third.text),
                        Phrase(code: "qreply", category: "测试", text: "其他合成内容")]
        rejected { _ = try PhraseDiscoverySelection.additions(candidates: report.candidates, selected: [], edits: [:], phrases: existing) }
        check(PhraseDiscoverySelection.issue(for: third, candidates: report.candidates, selected: [], edits: [:], phrases: existing) != nil)
        check(PhraseDiscoverySelection.issue(for: second, candidates: report.candidates, selected: [second.id], edits: [:], phrases: existing) != nil)
        check(PhraseDiscoverySelection.issue(for: second, candidates: report.candidates, selected: [second.id], edits: [second.id: "qnew"], phrases: existing) == nil)
        check(PhraseDiscoverySelection.issue(for: second, candidates: report.candidates, selected: [second.id], edits: [:], phrases: []) != nil)
        check(PhraseDiscoverySelection.issue(for: third, candidates: report.candidates, selected: [], edits: [:], phrases: []) != nil)
        for code in ["", "x", "UPPER", "uabc", "vabc", "q123", String(repeating: "x", count: 21)] {
            rejected { _ = try PhraseDiscoverySelection.additions(candidates: [first], selected: [first.id], edits: [first.id: code], phrases: []) }
        }
        let chosen: Set<String> = [second.id, first.id]
        let safeEdits = [first.id: " qsafe ", second.id: "qother"]
        let additions = try PhraseDiscoverySelection.additions(candidates: report.candidates, selected: chosen, edits: safeEdits, phrases: existing)
        check(additions.map(\.code) == ["qsafe", "qother"])
        check(additions.allSatisfy { $0.category == "发现" })
        check(additions[0].text == first.text)
        rejected { _ = try PhraseDiscoverySelection.additions(candidates: report.candidates, selected: chosen,
                                                              edits: [first.id: "qduplicate", second.id: "qduplicate"], phrases: []) }
        var repeatedText = second
        repeatedText.text = " \(first.text) \n"
        repeatedText.code_conflict = false
        rejected { _ = try PhraseDiscoverySelection.additions(candidates: [first, repeatedText], selected: chosen,
                                                              edits: safeEdits, phrases: []) }
        let manyPhrases = (0..<299).map { Phrase(code: "qsynthetic\($0)", category: "测试", text: "合成旧表达\($0)") }
        rejected { _ = try PhraseDiscoverySelection.additions(candidates: report.candidates, selected: chosen,
                                                              edits: safeEdits, phrases: manyPhrases) }
        let stateJSON = """
        {"settings":{},"phrases":[],"revision":"r1","today":"2026-10-03",
         "status":{"demo":true,"kev_enabled":false,"recorder":{"running":true}},
         "deployment":{"pending":false,"message":"Synthetic fixture"},
         "prediction":{"enabled":false,"installed":true,"max_candidates":3,"max_iterations":1,"schema_id":"fixture"}}
        """
        model.state = try JSONDecoder().decode(ConsoleState.self, from: Data(stateJSON.utf8))
        model.preferences = model.state!.settings
        model.phraseDiscovery = report
        model.discoverySelected = chosen
        model.discoveryCodes = safeEdits
        check(model.discoveryCanAdd && !model.dirty)
        model.addDiscoveredPhrases()
        check(model.phrases == additions && model.dirty)
        check(model.discoverySelected.isEmpty && !model.discoveryCanAdd)
        check(model.discoveryIssue(first) != nil)
        model.discard()
        check(model.phrases.isEmpty && !model.dirty && model.discoverySelected.isEmpty)
        model.phrases = [Phrase(code: "qdraft", category: "测试", text: "尚未保存的合成草稿")]
        model.discoverySelected = chosen
        model.discoveryCodes = safeEdits
        let rejectionJSON = """
        {"message":"已记住拒绝","rejected_count":2,
         "rejected_ids":["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],"revision":"r1"}
        """
        let outcome = try JSONDecoder().decode(PhraseDiscoveryRejection.self, from: Data(rejectionJSON.utf8))
        let pending = model.phrases
        model.applyDiscoveryRejection(outcome)
        check(model.phrases == pending && model.state!.revision == "r1")
        check(model.phraseDiscovery?.candidates.map(\.id) == [second.id, third.id])
        check(model.phraseDiscovery?.rejected_count == 2 && model.discoverySelected == [second.id])
        check(model.discoveryCodes[first.id] == nil && model.discoveryCodes[second.id] == "qother")
        model.clearPhraseDiscovery()
        check(model.phraseDiscovery == nil && model.discoverySelected.isEmpty && model.discoveryCodes.isEmpty)
        check(model.phrases == pending && model.dirty)
        print("Native phrase discovery checks passed: \(checks) assertions; synthetic data only; no history or configuration requests.")
    }
}
