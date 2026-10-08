"""Phrase interchange preserves data and keeps import proposals read-only."""
import copy
import csv
import io
import json
import unittest
from unittest.mock import patch

from keytrack import console, phrase_exchange as exchange


def phrase(code="qsample", text="合成表达", category="测试"):
    return {"code": code, "text": text, "category": category}


def document(items):
    return json.dumps({"schema_version": 1, "phrases": items}, ensure_ascii=True)


def unique_code(index):
    return "q" + "".join(chr(ord("a") + index // 26 ** place % 26) for place in (2, 1, 0))


class PhraseExchangeTests(unittest.TestCase):
    def test_json_and_tsv_round_trip_preserve_text_and_category(self):
        items = [phrase(text='  第一行\n\t第二行 "原话" \\ $HOME `literal`  ', category="  客户回复  "),
                 phrase("qemoji", "确认 ✅\n続き", "中日"),
                 phrase("qemptyline", "第一行\n\n最后一行\n", "多行")]
        normalized = console.validate_phrases(items)
        original = copy.deepcopy(items)
        for format in exchange.FORMATS:
            with self.subTest(format=format):
                exported = exchange.export_phrases(items, format)
                result = exchange.preview(exported, format, [])
                self.assertEqual(result["counts"], {"total": 3, "new": 3, "duplicate": 0,
                                                    "conflict": 0, "invalid": 0})
                self.assertEqual([{key: row[key] for key in exchange.FIELDS}
                                  for row in result["rows"]], normalized)
                self.assertEqual(exchange.preview(exported, format, normalized)["counts"]["duplicate"], 3)
                self.assertEqual(result, exchange.preview(exported, format, []))
        self.assertEqual(items, original)

    def test_export_json_schema_and_standard_tsv_are_interoperable(self):
        items = [phrase(text='制表符\t引号 " 和换行\n仍在原文中')]
        self.assertEqual(json.loads(exchange.export_phrases(items)), {"schema_version": 1, "phrases": items})
        cells = list(csv.reader(io.StringIO(exchange.export_phrases(items, "tsv"), newline=""), delimiter="\t"))
        self.assertEqual(cells, [["code", "text", "category"], [items[0][key] for key in exchange.FIELDS]])

    def test_existing_draft_conflicts_and_duplicates_never_overwrite(self):
        existing = [phrase("qoriginal", "已存在原话", "原分类")]
        incoming = [phrase("qoriginal", "已存在原话", "新分类"),
                    phrase("qoriginal", "另一句话"),
                    phrase("qother", "已存在原话"),
                    phrase("qnew", "已存在原话 ")]
        snapshot = copy.deepcopy(existing)
        result = exchange.preview(document(incoming), "json", existing)
        self.assertEqual([row["status"] for row in result["rows"]],
                         ["duplicate", "conflict", "duplicate", "new"])
        self.assertEqual(existing, snapshot)
        self.assertEqual(result["rows"][3]["text"], "已存在原话 ")

    def test_import_code_conflict_marks_all_competing_rows(self):
        incoming = [phrase("qclash", "竞争的第一句"), phrase("qclash", "竞争的第二句"),
                    phrase("qclash", "竞争的第一句"), phrase("qaccepted", "可导入表达")]
        result = exchange.preview(document(incoming), "json", [])
        self.assertEqual([row["status"] for row in result["rows"]], ["conflict"] * 3 + ["new"])
        self.assertEqual(result["counts"]["conflict"], 3)

    def test_repeated_content_keeps_only_the_first_addable_row(self):
        incoming = [phrase("qsame", "完整原话", "第一类"), phrase("qsame", "完整原话", "第二类"),
                    phrase("qdifferent", "完整原话"), phrase("qother", "完整原话\n")]
        result = exchange.preview(document(incoming), "json", [])
        self.assertEqual([row["status"] for row in result["rows"]], ["new", "duplicate", "duplicate", "new"])
        self.assertEqual(result["rows"][0]["category"], "第一类")
        self.assertEqual(len({row["id"] for row in result["rows"]}), 4)

    def test_invalid_rows_do_not_block_good_content(self):
        incoming = [phrase("qsame", "\x00"), phrase("qsame", "合格表达"), None,
                    {"code": 42, "text": "错误类型"}, {"code": "qdefault", "text": "默认分类"}]
        result = exchange.preview(document(incoming), "json", [])
        self.assertEqual([row["status"] for row in result["rows"]],
                         ["invalid", "new", "invalid", "invalid", "new"])
        self.assertEqual(result["rows"][-1]["category"], "常用")
        self.assertTrue(all(row["message"] for row in result["rows"]))
        self.assertTrue(all(isinstance(row[key], str) for row in result["rows"]
                            for key in ("id", *exchange.FIELDS, "status", "message")))

    def test_shared_save_rules_reject_reserved_codes_and_unsafe_fields(self):
        invalid = [phrase("vabc"), phrase("uabc"), phrase("QCAPS"), phrase("q"),
                   phrase("q" * 21), phrase(text=" "), phrase(text="x" * 2001),
                   phrase(text="控制\x01字符"), phrase(category=""), phrase(category="x" * 19),
                   phrase(category="分类\n换行")]
        with patch.object(console, "validate_phrases", wraps=console.validate_phrases) as validate:
            result = exchange.preview(document(invalid), "json", [])
            self.assertGreater(validate.call_count, 1)
        self.assertEqual(result["counts"]["invalid"], len(invalid))

    def test_tsv_two_column_header_bom_crlf_and_multiline(self):
        content = '\ufeffcode\ttext\r\nqmultiline\t"第一行\n第二行\t\"\"引号\"\""\r\n'
        row = exchange.preview(content, "tsv", [])["rows"][0]
        self.assertEqual(row["status"], "new")
        self.assertEqual(row["category"], "常用")
        self.assertEqual(row["text"], '第一行\n第二行\t"引号"')
        self.assertEqual(exchange.preview("\ufeff" + document([phrase()]), "json", [])["counts"]["new"], 1)

    def test_tsv_column_errors_are_visible_without_silent_truncation(self):
        content = "code\ttext\tcategory\nqextra\t原话\t测试\t不能丢失\nqmissing\t原话\n\nqgood\t合格表达\t测试\n"
        result = exchange.preview(content, "tsv", [])
        self.assertEqual([row["status"] for row in result["rows"]], ["invalid", "invalid", "invalid", "new"])
        self.assertEqual(result["counts"]["total"], 4)

    def test_unknown_formats_and_broken_envelopes_are_rejected(self):
        for format in ("yaml", "JSON", "../json", None, 1):
            with self.subTest(format=format), self.assertRaises(ValueError):
                exchange.preview(document([]), format, [])
            with self.subTest(export_format=format), self.assertRaises(ValueError):
                exchange.export_phrases([], format)
        bad_json = ['[]', '{}', '{"schema_version":true,"phrases":[]}',
                    '{"schema_version":2,"phrases":[]}', '{"schema_version":1,"phrases":{}}',
                    '{"schema_version":1,"phrases":[}',
                    '{"schema_version":1,"phrases":[],"extra":NaN}',
                    '{"schema_version":1,"schema_version":1,"phrases":[]}',
                    '{"schema_version":1,"phrases":[{"code":"qone","text":"a","text":"b"}]}']
        for content in bad_json:
            with self.subTest(content=content), self.assertRaises(ValueError):
                exchange.preview(content, "json", [])
        for content in ("", "text\tcode\n原话\tqcode\n", 'code\ttext\nqcode\t"未闭合\n'):
            with self.subTest(content=content), self.assertRaises(ValueError):
                exchange.preview(content, "tsv", [])

    def test_unicode_surrogates_are_rejected_without_breaking_the_response(self):
        result = exchange.preview(document([phrase(text="\ud800"), phrase("qvalid", "合格 ✅")]), "json", [])
        self.assertEqual([row["status"] for row in result["rows"]], ["invalid", "new"])
        json.dumps(result, ensure_ascii=False).encode("utf-8")
        with self.assertRaisesRegex(ValueError, "Unicode"):
            exchange.export_phrases([phrase(text="\ud800")])
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            exchange.preview("\ud800", "json", [])

    def test_file_budget_counts_bytes_not_characters(self):
        base = document([])
        boundary = base + " " * (exchange.MAX_BYTES - len(base.encode("utf-8")))
        self.assertEqual(exchange.preview(boundary, "json", [])["counts"]["total"], 0)
        with self.assertRaisesRegex(ValueError, "2 MB"):
            exchange.preview(boundary + " ", "json", [])
        multibyte = "汉" * (exchange.MAX_BYTES // 3 + 1)
        self.assertLess(len(multibyte), exchange.MAX_BYTES)
        with self.assertRaisesRegex(ValueError, "2 MB"):
            exchange.preview(multibyte, "json", [])

    def test_maximum_chinese_draft_round_trips_and_export_obeys_budget(self):
        items = [phrase(unique_code(index), "汉" * 1996 + f"{index:04}") for index in range(300)]
        for format in exchange.FORMATS:
            with self.subTest(format=format):
                content = exchange.export_phrases(items, format)
                self.assertLessEqual(len(content.encode("utf-8")), exchange.MAX_BYTES)
                self.assertEqual(exchange.preview(content, format, [])["counts"]["new"], 300)
        over_budget = [phrase(unique_code(index), "😀" * 2000) for index in range(300)]
        with self.assertRaisesRegex(ValueError, "2 MB"):
            exchange.export_phrases(over_budget)

    def test_six_hundred_preview_rows_can_be_selected_before_save(self):
        items = [phrase(unique_code(index), f"合成表达 {index}") for index in range(exchange.MAX_ROWS)]
        result = exchange.preview(document(items), "json", [])
        self.assertEqual(result["counts"]["new"], 600)
        for content, format in ((document(items + [phrase("qoverflow", "超过行数")]), "json"),
                                ("code\ttext\n" + "qone\t原话\n" * 601, "tsv")):
            with self.subTest(format=format), self.assertRaisesRegex(ValueError, "600"):
                exchange.preview(content, format, [])
        with self.assertRaisesRegex(ValueError, "300"):
            exchange.export_phrases(items)

    def test_malicious_content_is_data_and_no_history_or_files_are_touched(self):
        items = [phrase(text='__import__("os").system("echo unsafe")\nreturn {code = "x"}\n<script>alert(1)</script>')]
        original = copy.deepcopy(items)
        with patch.object(console, "atomic", side_effect=AssertionError("write forbidden")), \
                patch.object(console.sqlite3, "connect", side_effect=AssertionError("history forbidden")), \
                patch.object(console.subprocess, "run", side_effect=AssertionError("execution forbidden")):
            for format in exchange.FORMATS:
                result = exchange.preview(exchange.export_phrases(items, format), format, [])
                self.assertEqual(result["rows"][0]["text"], items[0]["text"])
                self.assertEqual(result["rows"][0]["status"], "new")
        self.assertEqual(items, original)
        with self.assertRaises(ValueError):
            exchange.preview('{"schema_version":1,"phrases":' + "[" * 100_000 + "0" + "]" * 100_000 + "}", "json", [])

    def test_existing_draft_and_export_must_pass_current_save_validation(self):
        duplicates = [phrase("qduplicate", "第一句"), phrase("qduplicate", "第二句")]
        for format in exchange.FORMATS:
            with self.subTest(format=format), self.assertRaisesRegex(ValueError, "重复"):
                exchange.export_phrases(duplicates, format)
        with self.assertRaisesRegex(ValueError, "重复"):
            exchange.preview(document([]), "json", duplicates)
        with self.assertRaises(ValueError):
            exchange.preview(b"not text", "json", [])


if __name__ == "__main__":
    unittest.main()
