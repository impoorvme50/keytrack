"""Frozen public five-candidate Kev evaluation; never reads input history.

The live adapter calls the unchanged Rime bridge on loopback. It observes
response timing only; user input, model bodies and exception text are not logged.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from keytrack import kev_rime_bridge as bridge

PROJECT = Path(__file__).resolve().parent.parent
DATA = PROJECT / "data" / "kev-evaluation"
DIAGNOSTIC_DATASET = DATA / "evaluation-v1.json"
DEFAULT_DATASET = DATA / "evaluation-v2.json"
KINDS = ("complete_word", "complete_sentence", "ambiguous", "reject")
ERRORS = ("timeout", "connection", "invalid_response")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_dataset(path: Path = DEFAULT_DATASET) -> dict:
    """Verify the frozen data and provenance before any decision is requested."""
    manifest = json.loads(path.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    actual = digest(path)
    if manifest.get("sha256") != actual:
        raise ValueError("evaluation differs from its frozen manifest")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or manifest.get("schema_version") != 1:
        raise ValueError("unsupported evaluation schema")
    if data.get("dataset_id") != manifest.get("dataset_id"):
        raise ValueError("dataset identities differ")
    examples = data.get("examples")
    if (not isinstance(examples, list) or type(manifest.get("samples")) is not int
            or len(examples) != manifest["samples"] or not 40 <= len(examples) <= 10_000):
        raise ValueError("frozen evaluation requires at least 40 matching samples")
    if data.get("candidate_source") not in ("original_handcrafted_public_pool", "isolated_public_rime_pool"):
        raise ValueError("candidate provenance must be explicit")
    if manifest.get("license") != "MIT" or data.get("source_id") != "keytrack-original-public-v1":
        raise ValueError("unsupported evaluation provenance")
    license_path = path.parent / "LICENSE.txt"
    if manifest.get("license_sha256") != digest(license_path):
        raise ValueError("license differs from the frozen manifest")
    ids: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    counts = dict.fromkeys(KINDS, 0)
    domains = {"daily": 0, "work": 0}
    for row in examples:
        if not isinstance(row, dict):
            raise ValueError("sample must be an object")
        identity, kind = row.get("id"), row.get("kind")
        if not isinstance(identity, str) or not identity or identity in ids:
            raise ValueError("sample identities must be unique")
        if kind not in KINDS or row.get("domain") not in domains:
            raise ValueError("invalid sample kind or domain")
        if not isinstance(row.get("situation"), str) or not row["situation"]:
            raise ValueError("sample needs a public situation")
        bridge._request_data(row)
        if len(row["candidates"]) != 5 or len(set(row["candidates"])) != 5:
            raise ValueError("frozen pools must contain five unique candidates")
        acceptable = row.get("acceptable")
        if (not isinstance(acceptable, list)
                or any(not isinstance(x, str) or not x or len(x) > 48 for x in acceptable)
                or len(set(acceptable)) != len(acceptable)):
            raise ValueError("acceptable answers must be unique full strings")
        if (kind == "reject") != (not acceptable):
            raise ValueError("only reject samples have no acceptable answer")
        if kind == "ambiguous" and len(acceptable) < 2:
            raise ValueError("ambiguous samples require multiple acceptable answers")
        pair = (row["input"], row["previous_text"])
        if pair in pairs:
            raise ValueError("pinyin/context pairs must be unique")
        ids.add(identity)
        pairs.add(pair)
        counts[kind] += 1
        domains[row["domain"]] += 1
    if data.get("candidate_source") != manifest.get("candidate_source"):
        raise ValueError("candidate provenance differs from its manifest")
    if data.get("candidate_source") == "isolated_public_rime_pool":
        provenance = manifest.get("candidate_provenance", {})
        if (provenance.get("user_dictionary_enabled") is not False
                or provenance.get("text_commits") != 0 or provenance.get("lua_or_logger_loaded") is not False):
            raise ValueError("native pools require isolated public-only provenance")
    if counts != manifest.get("kind_counts") or domains != manifest.get("domain_counts"):
        raise ValueError("sample segmentation differs from its manifest")
    if any(not count for count in counts.values()) or any(not count for count in domains.values()):
        raise ValueError("evaluation must cover every kind and both domains")
    return {"data": data, "manifest": manifest, "sha256": actual}


def validate_decision(raw: dict, candidate_count: int = 5) -> bridge.Decision:
    if not isinstance(raw, dict):
        raise ValueError("decision must be an object")
    index, probability, margin = (raw.get(x) for x in ("index", "probability", "margin"))
    if type(index) is not int or not 1 <= index <= candidate_count:
        raise ValueError("decision index outside pool")
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in (probability, margin)):
        raise ValueError("decision strength must be finite numbers")
    if not 0 <= margin <= probability <= 1:
        raise ValueError("decision strength outside probability boundaries")
    return bridge.Decision(index, float(probability), float(margin))


def fraction(numerator: int, denominator: int) -> dict:
    return {"numerator": numerator, "denominator": denominator,
            "percent": round(100 * numerator / denominator, 6) if denominator else None}


def score_row(example: dict, raw_decision: dict) -> dict:
    """Use the exact current adoption inequalities, preserving first on failure."""
    acceptable = set(example["acceptable"])
    result = {"id": example["id"], "domain": example["domain"], "kind": example["kind"],
              "situation": example["situation"],
              "target_in_pool": bool(acceptable.intersection(example["candidates"])),
              "baseline_correct": example["candidates"][0] in acceptable,
              "decision": None, "error": None, "adopted": False,
              "abstained": False, "promoted": False, "effective_index": 1}
    if isinstance(raw_decision, dict) and "error" in raw_decision:
        if raw_decision["error"] not in ERRORS:
            raise ValueError("unknown error category")
        result["error"] = raw_decision["error"]
        result["outcome"] = "failure"
    else:
        decision = validate_decision(raw_decision, len(example["candidates"]))
        adopted = decision.probability >= bridge.MIN_PROBABILITY and decision.margin >= bridge.MIN_MARGIN
        result.update(decision={"index": decision.index, "probability": decision.probability,
                                "margin": decision.margin}, adopted=adopted,
                      abstained=not adopted, promoted=adopted and decision.index != 1,
                      effective_index=decision.index if adopted else 1)
        if not adopted:
            result["outcome"] = "abstained"
        elif decision.index == 1:
            result["outcome"] = "kept_first"
        else:
            after = example["candidates"][decision.index - 1] in acceptable
            before = result["baseline_correct"]
            result["outcome"] = ("equivalent_change" if before and after else "rescued" if after
                                 else "regressed" if before else "wrong_to_wrong")
    result["effective_correct"] = example["candidates"][result["effective_index"] - 1] in acceptable
    result["rescued"] = not result["baseline_correct"] and result["effective_correct"]
    result["regressed"] = result["baseline_correct"] and not result["effective_correct"]
    result["wrong_promotion"] = result["promoted"] and not result["effective_correct"]
    result["raw_correct"] = (example["candidates"][result["decision"]["index"] - 1] in acceptable
                             if result["decision"] is not None else None)
    raw_timing = raw_decision.get("timing") if isinstance(raw_decision, dict) else None
    result["timing"] = ({key: value for key, value in raw_timing.items()
                         if key in ("model_ms", "http_ms", "bridge_ms")
                         and type(value) in (int, float) and math.isfinite(value) and value >= 0}
                        if isinstance(raw_timing, dict) else None)
    return result


def metrics(rows: list[dict]) -> dict:
    answerable = [x for x in rows if x["kind"] != "reject"]
    covered = [x for x in answerable if x["target_in_pool"]]
    rejects = [x for x in rows if x["kind"] == "reject"]
    promoted = sum(x["promoted"] for x in rows)
    original_good = sum(x["baseline_correct"] for x in answerable)
    successful = [x for x in answerable if x["raw_correct"] is not None]
    return {"samples": len(rows), "answerable": len(answerable),
            "baseline_top1": fraction(original_good, len(answerable)),
            "effective_top1": fraction(sum(x["effective_correct"] for x in answerable), len(answerable)),
            "baseline_top1_given_pool_coverage": fraction(sum(x["baseline_correct"] for x in covered), len(covered)),
            "effective_top1_given_pool_coverage": fraction(sum(x["effective_correct"] for x in covered), len(covered)),
            "target_in_pool": fraction(len(covered), len(answerable)),
            "target_absent": len(answerable) - len(covered),
            "raw_model_top1_given_success": fraction(sum(x["raw_correct"] for x in successful), len(successful)),
            "raw_model_rescues_unadopted_diagnostic": sum(not x["baseline_correct"] and x["raw_correct"] for x in successful),
            "raw_model_regressions_unadopted_diagnostic": sum(x["baseline_correct"] and not x["raw_correct"] for x in successful),
            "rescued": sum(x["rescued"] for x in rows),
            "regressed": sum(x["regressed"] for x in rows),
            "wrong_promotion": sum(x["wrong_promotion"] for x in rows),
            "wrong_promotion_rate": fraction(sum(x["wrong_promotion"] for x in rows), promoted),
            "regression_rate_given_baseline_correct": fraction(sum(x["regressed"] for x in rows), original_good),
            "promoted": promoted, "adopted": sum(x["adopted"] for x in rows),
            "no_change": sum(not x["promoted"] for x in rows),
            "abstained": sum(x["abstained"] for x in rows),
            "failed": sum(x["error"] is not None for x in rows),
            "reject_no_promotion": fraction(sum(not x["promoted"] for x in rejects), len(rejects)),
            "outcomes": {name: sum(x["outcome"] == name for x in rows) for name in (
                "failure", "abstained", "kept_first", "equivalent_change", "rescued", "regressed", "wrong_to_wrong")}}


def timing_summary(values: list[float]) -> dict:
    if not values:
        return {"samples": 0, "median_ms": None, "p95_ms": None, "min_ms": None, "max_ms": None}
    values = sorted(values)
    return {"samples": len(values), "median_ms": round(statistics.median(values), 3),
            "p95_ms": round(values[max(0, math.ceil(0.95 * len(values)) - 1)], 3),
            "min_ms": round(values[0], 3), "max_ms": round(values[-1], 3)}


def latency_report(rows: list[dict]) -> dict:
    def group(items: list[dict]) -> dict:
        return {segment: timing_summary([x["timing"][segment] for x in items
                    if x.get("timing") and type(x["timing"].get(segment)) in (int, float)
                    and math.isfinite(x["timing"][segment]) and x["timing"][segment] >= 0])
                for segment in ("model_ms", "http_ms", "bridge_ms")}
    return {"cold_start": {"measured": False, "reason": "existing_service_not_restarted"},
            "first_request_on_existing_service": group(rows[:1]),
            "warm_subsequent_requests": group(rows[1:]),
            "menu_visible_latency": {"measured": False, "reason": "offline_bridge_only"}}


def build_report(frozen: dict, decisions: dict[str, dict], mode: str, model: dict | None = None) -> dict:
    examples = frozen["data"]["examples"]
    identities = {x["id"] for x in examples}
    if set(decisions) != identities:
        raise ValueError("decisions must cover the frozen dataset exactly")
    rows = [score_row(example, decisions[example["id"]]) for example in examples]
    def strength(field: str) -> dict:
        values = [x["decision"][field] for x in rows if x["decision"] is not None]
        return {"samples": len(values), "min": round(min(values), 6) if values else None,
                "median": round(statistics.median(values), 6) if values else None,
                "max": round(max(values), 6) if values else None}
    return {"schema_version": 1, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "dataset_id": frozen["data"]["dataset_id"], "dataset_sha256": frozen["sha256"],
            "candidate_source": frozen["data"]["candidate_source"], "mode": mode,
            "model": model, "thresholds": {"min_probability": bridge.MIN_PROBABILITY,
                "min_margin": bridge.MIN_MARGIN, "inclusive": True, "calibrated": False},
            "baseline": ("first_in_isolated_public_rime_pool_not_daily_schema"
                         if frozen["data"]["candidate_source"] == "isolated_public_rime_pool"
                         else "first_in_frozen_handcrafted_pool_not_live_rime_ranking"),
            "overall": metrics(rows),
            "observed_strength": {"probability": strength("probability"), "margin": strength("margin")},
            "by_kind": {kind: metrics([x for x in rows if x["kind"] == kind]) for kind in KINDS},
            "by_domain": {domain: metrics([x for x in rows if x["domain"] == domain]) for domain in ("daily", "work")},
            "latency": latency_report(rows), "rows": rows,
            "limitations": [("isolated_public_rime_snapshot_not_daily_filters_or_personal_frequency"
                if frozen["data"]["candidate_source"] == "isolated_public_rime_pool"
                else "original_synthetic_pools_not_real_rime_candidate_snapshots"),
                "small_public_convenience_sample_not_population_accuracy",
                "ambiguous_full_answers_use_multiple_acceptable_strings",
                "reject_means_preserve_order_not_generate_a_new_answer",
                "probabilities_are_uncalibrated_rounded_model_scores",
                "no_cold_model_load_or_process_queue_or_visible_menu_measurement",
                "no_threshold_tuning_or_input_behavior_changes"]}


def error_category(error: Exception) -> str:
    if isinstance(error, urllib.error.HTTPError):
        return "invalid_response"
    if isinstance(error, (TimeoutError, urllib.error.URLError)):
        reason = getattr(error, "reason", error)
        return "timeout" if isinstance(reason, TimeoutError) else "connection"
    if isinstance(error, OSError):
        return "connection"
    return "invalid_response"


@contextmanager
def observed_local(timing: dict):
    """Process-local, serial observer; original transport/validation remain in use."""
    original = bridge.open_local

    class Response:
        def __init__(self, response, started):
            self.response, self.started = response, started
            self.status = response.status

        def __enter__(self):
            self.response.__enter__()
            return self

        def __exit__(self, *args):
            return self.response.__exit__(*args)

        def read(self, size):
            data = self.response.read(size)
            timing["http_ms"] = (time.perf_counter() - self.started) * 1000
            # Capture only server inference time, never retain or print its body.
            try:
                model_ms = json.loads(data).get("latency_ms")
                if type(model_ms) in (int, float) and math.isfinite(model_ms) and model_ms >= 0:
                    timing["model_ms"] = model_ms
            except (ValueError, TypeError, AttributeError):
                pass
            return data

    def observed(request, timeout):
        started = time.perf_counter()
        return Response(original(request, timeout), started)

    bridge.open_local = observed
    try:
        yield
    finally:
        bridge.open_local = original


def live_decision(example: dict) -> dict:
    """No URL option, proxy, redirects, queue files, input history or model loading."""
    timing: dict = {}
    started = time.perf_counter()
    try:
        with observed_local(timing):
            decision = bridge.decide_candidate(example)
        result = {"index": decision.index, "probability": decision.probability, "margin": decision.margin}
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = {"error": error_category(error)}
    timing["bridge_ms"] = (time.perf_counter() - started) * 1000
    result["timing"] = {key: round(value, 3) for key, value in timing.items()}
    return result


def model_metadata() -> dict:
    request = urllib.request.Request("http://127.0.0.1:8009/v1/models")
    with bridge.open_local(request, timeout=bridge.TIMEOUT_SECONDS) as response:
        data = response.read(bridge.MAX_RESPONSE_BYTES + 1)
        if response.status != 200 or len(data) > bridge.MAX_RESPONSE_BYTES:
            raise ValueError("local model metadata unavailable")
        models = json.loads(data)["models"]
    if not isinstance(models, list) or not models or not isinstance(models[0], dict):
        raise ValueError("local model metadata invalid")
    # Exclude paths, cached states, logging and any other service state.
    metadata = {key: models[0].get(key) for key in ("id", "run", "device", "temperature")}
    if isinstance(metadata.get("run"), str) and metadata["run"].startswith(("/", "~", "./", "../")):
        metadata["run"] = "local_run_path_omitted"
    return metadata


def run_live(frozen: dict, progress: Callable[[int, int], None] | None = None) -> dict:
    metadata = model_metadata()  # Fail early; never start a stopped service.
    examples = frozen["data"]["examples"]
    decisions = {}
    for index, example in enumerate(examples, 1):
        decisions[example["id"]] = live_decision(example)
        if progress:
            progress(index, len(examples))
    return build_report(frozen, decisions, "live_local_bridge", metadata)


def render_markdown(report: dict) -> str:
    overall = report["overall"]
    def rate(value):
        return f'{value["numerator"]}/{value["denominator"]}' + (f' ({value["percent"]:.2f}%)' if value["percent"] is not None else "")
    lines = ["# Kev 中文五候选收益评测", "", f'模式：`{report["mode"]}`。样例：`{report["dataset_id"]}`。',
             f'冻结 SHA-256：`{report["dataset_sha256"]}`。', "",
             ("原首项来自隔离的公共 Rime 实际候选快照；它使用简化方案、关闭用户词典，不代表日常方案全部过滤器或个人调频。"
              if report["candidate_source"] == "isolated_public_rime_pool"
              else "原首项来自原创人工冻结候选池，尚不是实时 Rime 排名测量。")
             + "全部上下文和目标为公开原创样例，不读取用户输入。", "",
             "| 指标 | 结果 |", "| --- | --- |",
             f'| 可评分／全部样例 | {overall["answerable"]}/{overall["samples"]} |',
             f'| 原首项 Top 1 | {rate(overall["baseline_top1"])} |',
             f'| 当前策略 Top 1 | {rate(overall["effective_top1"])} |',
             f'| 模型原始选择 Top 1（未采用的诊断） | {rate(overall["raw_model_top1_given_success"])} |',
             f'| 原始选择的救回／弄坏（未采用的诊断） | {overall["raw_model_rescues_unadopted_diagnostic"]}/{overall["raw_model_regressions_unadopted_diagnostic"]} |',
             f'| 目标在池内 | {rate(overall["target_in_pool"])} |',
             f'| 救回／弄坏原正确首项 | {overall["rescued"]}/{overall["regressed"]} |',
             f'| 误提升／全部提升 | {rate(overall["wrong_promotion_rate"])} |',
             f'| 无变化／弃权／失败 | {overall["no_change"]}/{overall["abstained"]}/{overall["failed"]} |',
             f'| 拒绝样例保持原序 | {rate(overall["reject_no_promotion"])} |', "",
             "| 分组 | 样例 | 原首项 Top 1 | 当前策略 Top 1 | 救回 | 弄坏 | 误提升 |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for label, segment in {**report["by_kind"], **report["by_domain"]}.items():
        lines.append(f'| {label} | {segment["samples"]} | {rate(segment["baseline_top1"])} | {rate(segment["effective_top1"])} | {segment["rescued"]} | {segment["regressed"]} | {segment["wrong_promotion"]} |')
    lines.extend(["", "当前策略固定为概率 ≥0.90、领先 ≥0.30；本轮未校准概率、调整阈值或修改输入行为。", "",
                  "冷启动未测：既有服务没有重启。首请求与随后请求分别报告，随后请求也可能包含不同上下文的缓存未命中。", "",
                  "| 请求阶段 | 耗时段 | 样本 | 中位数 ms | P95 ms |", "| --- | --- | --- | --- | --- |"])
    for group in ("first_request_on_existing_service", "warm_subsequent_requests"):
        for segment, values in report["latency"][group].items():
            lines.append(f'| {group} | {segment} | {values["samples"]} | {values["median_ms"]} | {values["p95_ms"]} |')
    lines.extend(["", "模型耗时是服务自身推理计时；HTTP 包含请求／响应；bridge 包含序列化与解析。未测进程启动、Rime 队列和真实候选窗出现耗时。", "",
                  "这是小型便利样例基线。完整答案按全文精确匹配，歧义采用多个可接受答案；目标不在池内仍计入整体 Top 1 分母，拒绝样例单独计数。继续保留现有策略，另建真实 Rime 快照及独立盲测集后再考虑阈值。", ""])
    return "\n".join(lines)


def write_reports(report: dict, json_path: Path | None, markdown_path: Path | None,
                  protected: list[Path]) -> None:
    outputs = [path for path in (json_path, markdown_path) if path is not None]
    resolved = [path.resolve() for path in outputs]
    if len(set(resolved)) != len(resolved) or set(resolved).intersection(path.resolve() for path in protected):
        raise ValueError("report outputs must differ and cannot overwrite frozen inputs")
    for path in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
    if json_path:
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if markdown_path:
        markdown_path.write_text(render_markdown(report), encoding="utf-8")
