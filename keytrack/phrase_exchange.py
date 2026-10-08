"""Bounded, read-only phrase interchange for the console's draft workflow.

This module only parses supplied text and validates supplied phrases. It never
reads input history, saves configuration, or changes input-method switches.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json

MAX_BYTES = 2_000_000
MAX_ROWS = 600
MAX_JSON_DEPTH = 16
FORMATS = ("json", "tsv")
STATUSES = ("new", "duplicate", "conflict", "invalid")
FIELDS = ("code", "text", "category")


def _format(value: str) -> None:
    if not isinstance(value, str) or value not in FORMATS:
        raise ValueError("常用语文件格式须为 JSON 或 TSV")


def _content_bytes(content: str) -> bytes:
    if not isinstance(content, str):
        raise ValueError("导入内容须为 UTF-8 文本")
    if len(content) > MAX_BYTES:
        raise ValueError("常用语文件最多 2 MB")
    try:
        raw = content.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("导入内容须为有效的 UTF-8 文本") from error
    if len(raw) > MAX_BYTES:
        raise ValueError("常用语文件最多 2 MB")
    return raw


def _validate(items: object) -> list[dict]:
    # Console imports this module too; defer the shared validator to avoid a
    # circular import and keep saving and importing on the same phrase rules.
    from .console import validate_phrases

    validated = validate_phrases(items)
    try:
        for item in validated:
            for name in FIELDS:
                item[name].encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("常用语包含无法保存的 Unicode 字符") from error
    return validated


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("JSON 不允许重复字段")
        result[name] = value
    return result


def _safe_field(value: object) -> str:
    if not isinstance(value, str):
        return ""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return ""
    return value


def _nonstandard_constant(value: str):
    raise ValueError("JSON 不接受 NaN 或 Infinity 数值")


def _json_depth(content: str) -> None:
    # Bound container allocation before decoding. Some Python versions decode
    # deeply nested JSON iteratively, so RecursionError alone is not a budget.
    depth, quoted, escaped = 0, False, False
    for character in content:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ValueError("常用语 JSON 嵌套层数过多")
        elif character in "]}":
            depth -= 1


def _parse(content: str, format: str) -> list[tuple[object, str | None]]:
    if format == "json":
        _json_depth(content)
        try:
            document = json.loads(content, object_pairs_hook=_unique_object,
                                  parse_constant=_nonstandard_constant)
        except (json.JSONDecodeError, RecursionError, ValueError) as error:
            raise ValueError(f"常用语 JSON 无法读取：{error}") from error
        if (not isinstance(document, dict)
                or type(document.get("schema_version")) is not int
                or document["schema_version"] != 1
                or not isinstance(document.get("phrases"), list)):
            raise ValueError("JSON 须包含 schema_version: 1 和 phrases 列表")
        if len(document["phrases"]) > MAX_ROWS:
            raise ValueError(f"一次导入预览最多 {MAX_ROWS} 条")
        return [(item, None) for item in document["phrases"]]

    reader = csv.reader(io.StringIO(content, newline=""), delimiter="\t", strict=True)
    try:
        header = next(reader, None)
        if header not in (["code", "text", "category"], ["code", "text"]):
            raise ValueError("TSV 首行须为 code、text、category（可省略 category）三列标题")
        parsed = []
        for cells in reader:
            if len(parsed) == MAX_ROWS:
                raise ValueError(f"一次导入预览最多 {MAX_ROWS} 条")
            row = dict(zip(header, cells))
            issue = None if len(cells) == len(header) else "TSV 列数与标题不一致"
            parsed.append((row, issue))
        return parsed
    except csv.Error as error:
        raise ValueError(f"常用语 TSV 无法读取：{error}") from error


def preview(content: str, format: str, existing: list[dict]) -> dict:
    """Return bounded import rows and counts without changing the draft.

    Envelope/format/budget errors raise ValueError; individual phrase errors
    receive status ``invalid``. Only ``new`` rows may be selected for addition.
    Existing phrases can include the console's currently unsaved draft.
    """
    _format(format)
    raw = _content_bytes(content)
    prior = _validate(existing)
    parsed = _parse(content.removeprefix("\ufeff"), format)
    digest = hashlib.sha256(raw).hexdigest()
    rows = []
    valid = []
    by_code: dict[str, set[str]] = {}
    for index, (item, issue) in enumerate(parsed, 1):
        fields = {name: item.get(name, "常用" if name == "category" else "")
                  if isinstance(item, dict) else "" for name in FIELDS}
        row = {"id": hashlib.sha256(f"{digest}:{index}".encode("ascii")).hexdigest(),
               **{name: _safe_field(value) for name, value in fields.items()},
               "status": "invalid", "message": ""}
        try:
            if issue:
                raise ValueError(issue)
            normalized = _validate([item])[0]
            row.update(normalized)
            by_code.setdefault(row["code"], set()).add(row["text"])
            valid.append(row)
        except ValueError as error:
            row["message"] = str(error)
        rows.append(row)

    prior_codes = {item["code"]: item["text"] for item in prior}
    prior_texts = {item["text"] for item in prior}
    added_codes, added_texts = set(), set()
    for row in valid:
        code, phrase = row["code"], row["text"]
        if code in prior_codes:
            if phrase == prior_codes[code]:
                row.update(status="duplicate", message="草稿已有相同编码和内容，不会覆盖分类")
            else:
                row.update(status="conflict", message="短编码已被草稿中的其他内容使用")
        elif len(by_code[code]) > 1:
            row.update(status="conflict", message="导入文件中同一短编码对应不同内容")
        elif phrase in prior_texts:
            row.update(status="duplicate", message="草稿已有相同内容，不会新增或覆盖分类")
        elif code in added_codes or phrase in added_texts:
            row.update(status="duplicate", message="与文件中前面的可新增内容重复")
        else:
            row.update(status="new", message="可加入待保存草稿")
            added_codes.add(code)
            added_texts.add(phrase)

    counts = {"total": len(rows), **{status: 0 for status in STATUSES}}
    for row in rows:
        counts[row["status"]] += 1
    return {"rows": rows, "counts": counts}


def export_phrases(items: list[dict], format: str = "json") -> str:
    """Serialize validated phrases; the caller chooses and writes the file."""
    _format(format)
    phrases = _validate(items)
    if format == "json":
        content = json.dumps({"schema_version": 1, "phrases": phrases},
                             ensure_ascii=False, indent=2) + "\n"
    else:
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(FIELDS)
        writer.writerows([item[name] for name in FIELDS] for item in phrases)
        content = stream.getvalue()
    _content_bytes(content)
    return content
