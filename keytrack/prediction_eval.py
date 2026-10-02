"""Frozen, exact-key next-word quality evaluation; never reads user history.

This evaluates the builder's candidate table, not a live Rime menu. Native
fixture, latency and normal-input acceptance remain separate release checks.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Iterable

PROJECT = Path(__file__).resolve().parent.parent
DATA = PROJECT / "data" / "prediction"
DEFAULT_DATASET = DATA / "evaluation-v1.json"
DEFAULT_BASELINE = DATA / "starter.ngram.tsv"
KINDS = ("word", "phrase", "unmatched", "boundary")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_dataset(path: Path = DEFAULT_DATASET, manifest_path: Path | None = None) -> dict:
    """Require a frozen manifest before consulting any source."""
    manifest_path = manifest_path or path.with_suffix(".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_digest = digest(path)
    if manifest.get("sha256") != actual_digest:
        raise ValueError("evaluation set differs from its frozen manifest")
    dataset = json.loads(path.read_text(encoding="utf-8"))
    if dataset.get("schema_version") != 1 or manifest.get("schema_version") != 1:
        raise ValueError("unsupported evaluation schema")
    if dataset.get("dataset_id") != manifest.get("dataset_id"):
        raise ValueError("dataset and manifest identities differ")
    examples = dataset.get("examples")
    samples = manifest.get("samples")
    if (type(samples) is not int or not 100 <= samples <= 10_000
            or not isinstance(examples, list) or len(examples) != samples):
        raise ValueError("frozen evaluation sample count differs from its manifest")
    if dataset.get("dataset_id") == "keytrack-next-word-v1" and samples != 200:
        raise ValueError("frozen v1 evaluation must contain exactly 200 samples")
    ids = set()
    situations = set()
    kinds = dict.fromkeys(KINDS, 0)
    for example in examples:
        if not isinstance(example, dict):
            raise ValueError("evaluation sample must be an object")
        identity = example.get("id")
        situation = example.get("situation")
        kind = example.get("kind")
        acceptable = example.get("acceptable_next")
        if not isinstance(identity, str) or not identity or identity in ids:
            raise ValueError("sample identities must be nonempty and unique")
        if not isinstance(situation, str) or not situation:
            raise ValueError("sample situation must be nonempty")
        if kind not in KINDS:
            raise ValueError("sample kind must be word, phrase, unmatched or boundary")
        if not isinstance(example.get("commit"), str) or not example["commit"]:
            raise ValueError("sample must contain a nonempty full commit unit")
        if not isinstance(acceptable, list) or any(not isinstance(x, str) or not x for x in acceptable):
            raise ValueError("acceptable next words must be a list of nonempty strings")
        if len(set(acceptable)) != len(acceptable):
            raise ValueError("acceptable next words must be unique")
        if (kind == "boundary") != (not acceptable):
            raise ValueError("only boundary samples have empty acceptable sets")
        ids.add(identity)
        situations.add(situation)
        kinds[kind] += 1
    if len(situations) < 10 or manifest.get("situations") != len(situations):
        raise ValueError("frozen evaluation must cover at least 10 situations")
    if manifest.get("kind_counts") != kinds or any(not n for n in kinds.values()):
        raise ValueError("frozen manifest kind counts differ from the samples")
    return {"data": dataset, "manifest": manifest, "sha256": actual_digest}


def read_candidates(paths: list[Path], max_candidates: int = 8) -> dict:
    """Use the real builder contract, including stable ties and duplicate max."""
    builder_path = PROJECT / "scripts" / "build-predict-db.py"
    spec = importlib.util.spec_from_file_location("keytrack_eval_builder", builder_path)
    if spec is None or spec.loader is None:
        raise ValueError("prediction builder could not be loaded")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    text = builder.preprocess(paths, max_candidates)
    candidates: dict[str, list[str]] = {}
    for line in text.splitlines():
        key, candidate, _weight = line.split("\t")
        candidates.setdefault(key, []).append(candidate)
    return {"candidates": candidates, "preprocessed_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "contexts": len(candidates), "records": len(text.splitlines())}


def fraction(numerator: int, denominator: int) -> dict:
    return {"numerator": numerator, "denominator": denominator,
            "percent": round(100 * numerator / denominator, 6) if denominator else None}


def metrics(rows: Iterable[dict]) -> dict:
    rows = list(rows)
    total = len(rows)
    hits = sum(x["lookup_hit"] for x in rows)
    top1 = sum(x["first_acceptable_rank"] == 1 for x in rows)
    top3 = sum(x["first_acceptable_rank"] is not None and x["first_acceptable_rank"] <= 3 for x in rows)
    boundary = [x for x in rows if x["kind"] == "boundary"]
    return {"samples": total, "lookup_hit": fraction(hits, total),
            "top1_acceptable_overall": fraction(top1, total),
            "top3_acceptable_overall": fraction(top3, total),
            "top3_acceptable_given_hit": fraction(top3, hits),
            "boundary_no_prediction": fraction(sum(not x["lookup_hit"] for x in boundary), len(boundary))}


def evaluate(examples: list[dict], candidates: dict[str, list[str]]) -> dict:
    rows = []
    for example in examples:
        # Deliberately no trim, segmentation, suffix lookup, or normalization.
        predictions = candidates.get(example["commit"], [])
        accepted = set(example["acceptable_next"])
        rank = next((i for i, word in enumerate(predictions, 1) if word in accepted), None)
        rows.append({"id": example["id"], "situation": example["situation"], "kind": example["kind"],
                     "commit": example["commit"], "acceptable_next": example["acceptable_next"],
                     "predictions": predictions, "lookup_hit": bool(predictions), "first_acceptable_rank": rank})
    return {"overall": metrics(rows),
            "by_kind": {kind: metrics(x for x in rows if x["kind"] == kind) for kind in KINDS},
            "by_situation": {s: metrics(x for x in rows if x["situation"] == s)
                             for s in sorted({x["situation"] for x in rows})},
            "rows": rows}


def quality_gate(baseline: dict, candidate: dict) -> dict:
    """Compare integer counts so rounding never changes the 10 pp decision."""
    old = baseline["overall"]
    new = candidate["overall"]
    old_hit, new_hit = old["lookup_hit"], new["lookup_hit"]
    old_top3, new_top3 = old["top3_acceptable_overall"], new["top3_acceptable_overall"]
    total = old["samples"]
    if not total or total != new["samples"]:
        raise ValueError("quality gate requires equal nonempty sample denominators")
    hit_pass = (new_hit["numerator"] - old_hit["numerator"]) * 10 >= total
    top3_pass = new_top3["numerator"] >= old_top3["numerator"]
    return {"minimum_hit_improvement_pp": 10,
            "hit_improvement_pp": round(100 * (new_hit["numerator"] - old_hit["numerator"]) / total, 6),
            "top3_change_pp": round(100 * (new_top3["numerator"] - old_top3["numerator"]) / total, 6),
            "hit_improvement_passed": hit_pass, "overall_top3_not_lower": top3_pass,
            "quality_gate_passed": hit_pass and top3_pass,
            "required_separate_checks": ["exact native fixture", "normal input", "latency", "real candidate window"]}


def display_path(path: Path) -> str:
    path = path.resolve()
    return str(path.relative_to(PROJECT)) if path.is_relative_to(PROJECT) else str(path)


def source_result(examples: list[dict], paths: list[Path], max_candidates: int) -> dict:
    table = read_candidates(paths, max_candidates)
    return {"sources": [{"file": display_path(path), "sha256": digest(path)} for path in paths],
            "preprocessed_sha256": table["preprocessed_sha256"], "contexts": table["contexts"],
            "records": table["records"], **evaluate(examples, table["candidates"])}


def build_report(baseline: list[Path], candidate: list[Path] | None = None,
                 dataset_path: Path = DEFAULT_DATASET, max_candidates: int = 8) -> dict:
    frozen = load_dataset(dataset_path)
    examples = frozen["data"]["examples"]
    report = {"schema_version": 1, "dataset_id": frozen["data"]["dataset_id"],
              "dataset_sha256": frozen["sha256"], "samples": len(examples),
              "situations": frozen["manifest"]["situations"],
              "situation_labels": {x["situation"]: x.get("situation_label", x["situation"]) for x in examples},
              "candidate_cap_in_data": max_candidates, "displayed_candidates_scored": 3,
              "lookup_contract": "exact full commit; builder preprocessing; no suffix fallback",
              "builder_sha256": digest(PROJECT / "scripts" / "build-predict-db.py"),
              "measurement": "offline source-table quality; not a live engine, input or latency test",
              "baseline": source_result(examples, baseline, max_candidates),
              "candidate": None, "gate": None}
    if candidate is not None:
        report["candidate"] = source_result(examples, candidate, max_candidates)
        report["gate"] = quality_gate(report["baseline"], report["candidate"])
    return report


def score_cell(value: dict) -> str:
    numerator, denominator, percent = value["numerator"], value["denominator"], value["percent"]
    return f"{numerator}/{denominator}（{percent:.2f}%）" if denominator else "0/0（不适用）"


def render_markdown(report: dict) -> str:
    lines = ["# 冻结接词评测", "", f"评测集：`{report['dataset_id']}`；{report['samples']} 条独立自造样例，{report['situations']} 种情境。",
             f"SHA-256：`{report['dataset_sha256']}`。", "",
             "按完整上屏文本精确查键，使用现有 builder 的预处理与稳定排序。Top 1/Top 3 的整体分母包括无匹配与边界样例。",
             "边界输入没有可接受后词，独立统计不出候选率；未匹配探针按实际查键结果计分。此报告不证明真实菜单、按键行为或延迟。", ""]
    for name, label in (("baseline", "基线数据"), ("candidate", "候选数据")):
        result = report[name]
        if result is None:
            continue
        lines += [f"## {label}", "", f"前键 {result['contexts']}；词对 {result['records']}。", ""]
        for source in result["sources"]:
            lines += [f"- `{source['file']}`；SHA-256 `{source['sha256']}`"]
        lines += ["", "| 分组 | 查键命中 | 整体 Top 1 | 整体 Top 3 | 命中内 Top 3 |",
                  "| --- | --- | --- | --- | --- |"]
        kind_labels = {"word": "单词", "phrase": "短语", "unmatched": "未匹配探针", "boundary": "边界"}
        grouped = [("全部", result["overall"])] + [(kind_labels[k], v) for k, v in result["by_kind"].items()]
        for label, metric in grouped:
            cells = [score_cell(metric[key]) for key in
                     ("lookup_hit", "top1_acceptable_overall", "top3_acceptable_overall", "top3_acceptable_given_hit")]
            lines.append("| " + " | ".join([label, *cells]) + " |")
        lines += ["", f"边界不出候选：{score_cell(result['overall']['boundary_no_prediction'])}。", "",
                  "| 情境 | 查键命中 | 整体 Top 1 | 整体 Top 3 | 命中内 Top 3 |",
                  "| --- | --- | --- | --- | --- |"]
        for situation, metric in result["by_situation"].items():
            cells = [score_cell(metric[key]) for key in
                     ("lookup_hit", "top1_acceptable_overall", "top3_acceptable_overall", "top3_acceptable_given_hit")]
            lines.append("| " + " | ".join([report["situation_labels"].get(situation, situation), *cells]) + " |")
        lines.append("")
    gate = report["gate"]
    if gate is not None:
        lines += ["## 数据质量门槛", "",
                  f"命中变化：{gate['hit_improvement_pp']:+.2f} 个百分点；整体 Top 3 变化：{gate['top3_change_pp']:+.2f} 个百分点。",
                  f"命中至少提高 10 个百分点：{'通过' if gate['hit_improvement_passed'] else '未通过'}；"
                  f"整体 Top 3 不下降：{'通过' if gate['overall_top3_not_lower'] else '未通过'}。",
                  f"数据质量门槛：{'通过' if gate['quality_gate_passed'] else '未通过'}。",
                  "仍需精确 native fixture、正常输入、性能与真实候选窗检查后才能替换默认资源。", ""]
        old_conditional = report["baseline"]["overall"]["top3_acceptable_given_hit"]
        new_conditional = report["candidate"]["overall"]["top3_acceptable_given_hit"]
        lines += [f"命中内 Top 3：{score_cell(old_conditional)} → {score_cell(new_conditional)}。",
                  "这一指标的分母随覆盖变化，单独展示以检查新增命中的候选质量；数据门槛仍使用全部样例的整体 Top 3。", ""]
    return "\n".join(lines)


def write_reports(report: dict, json_path: Path | None, markdown_path: Path | None,
                  protected: Iterable[Path] = ()) -> None:
    outputs = [p for p in (json_path, markdown_path) if p is not None]
    resolved = [p.resolve() for p in outputs]
    if len(set(resolved)) != len(resolved):
        raise ValueError("JSON and Markdown report paths must differ")
    if set(resolved) & {p.resolve() for p in protected}:
        raise ValueError("report output must not overwrite a dataset, manifest, or source")
    rendered = ((json_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n"),
                (markdown_path, render_markdown(report)))
    for path, text in rendered:
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
