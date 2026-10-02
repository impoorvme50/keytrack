#!/usr/bin/env python3
"""Conservatively refine frozen v1 pairs, keeping full-key source ownership.

No corpus re-counting, personal history, network, runtime segmentation or
cross-source weight addition. This generates a separate candidate resource.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import re
import sys
import tempfile

PROJECT = Path(__file__).resolve().parent.parent
DATA = PROJECT / "data" / "prediction"
PINNED_DICTIONARY = "7197c3211ddd98962b036cdf40324d1ea2bfaa12bd028e68faa70111a88e12a8"
PINNED_V1 = "b1709b748ec1824c194e430b80b80d1fcf724835f34f0c1f703a36ee4415fbcd"
NUMERAL = re.compile(r"[零〇一二三四五六七八九十百千万亿两廿卅]+\Z")
VIOLENT_ACTIONS = frozenset(("杀", "砍", "揍", "虐"))
RULES = (
    "pure Chinese numeral candidates only",
    "single-character candidates explicitly tagged as dictionary morphemes (*g)",
    "adjacent identical tokens or A-particle-A key repetition; ordinary A-not-A retained",
    "standalone violent-action tokens in keys or candidates; not substring matching",
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def display_path(path):
    path = path.resolve()
    return str(path.relative_to(PROJECT)) if path.is_relative_to(PROJECT) else str(path)


def read_table(path):
    grouped = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        fields = line.split("\t")
        if len(fields) != 2:
            raise ValueError(f"{path}:{number}: expected explicit pair TAB unsigned weight")
        text, weight = fields
        words = text.split(" ")
        if (len(words) != 2 or any(not word or any(char.isspace() or ord(char) < 32 or ord(char) == 127
                                                   for char in word) for word in words)):
            raise ValueError(f"{path}:{number}: expected two nonempty full-key words")
        if not weight.isascii() or not weight.isdecimal() or int(weight) > 0xFFFFFFFF:
            raise ValueError(f"{path}:{number}: weight must fit unsigned u32")
        key, candidate = words
        entries = grouped.setdefault(key, [])
        if any(word == candidate for word, _ in entries):
            raise ValueError(f"{path}:{number}: duplicate pair in an already aggregated table")
        entries.append((candidate, int(weight)))
        if len(entries) > 8:
            raise ValueError(f"{path}:{number}: source key exceeds eight candidates")
    if not grouped:
        raise ValueError("source table must not be empty")
    # Stable ties preserve the input's builder order, never lexically reshuffle.
    return {key: sorted(values, key=lambda item: -item[1]) for key, values in sorted(grouped.items())}


def read_tags(path):
    tags = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        fields = line.split()
        if len(fields) != 3 or not fields[1].isdecimal():
            raise ValueError(f"invalid dictionary metadata at line {number}")
        tags[fields[0]] = fields[2]
    return tags


def abnormal_repetition(tokens, tags):
    if any(a == b for a, b in zip(tokens, tokens[1:])):
        return True
    for a, middle, b in zip(tokens, tokens[1:], tokens[2:]):
        if a != b:
            continue
        if middle in ("不", "没") and tags.get(a, "").startswith(("v", "a")):
            continue
        if tags.get(middle, "").startswith(("u", "y", "e", "q")):
            return True
    return False


def filter_table(base, starter, tokenize, tags):
    filtered = {}
    removed = []
    reason_counts = Counter()
    removed_keys = Counter()
    cache = {}

    def tokens(text):
        if text not in cache:
            cache[text] = tuple(tokenize(text))
        return cache[text]

    for key, entries in base.items():
        # Highest-priority manual ownership is preserved as a complete unit.
        if key in starter:
            filtered[key] = list(entries)
            continue
        key_tokens = tokens(key)
        reason = ("abnormal_key_repetition" if abnormal_repetition(key_tokens, tags)
                  else "independent_violent_key" if any(t in VIOLENT_ACTIONS for t in key_tokens) else None)
        kept = []
        for candidate, weight in entries:
            candidate_reason = reason
            if candidate_reason is None:
                if NUMERAL.fullmatch(candidate):
                    candidate_reason = "chinese_numeral_candidate"
                elif len(candidate) == 1 and tags.get(candidate, "").endswith("g"):
                    candidate_reason = "single_dictionary_morpheme_candidate"
                elif any(t in VIOLENT_ACTIONS for t in tokens(candidate)):
                    candidate_reason = "independent_violent_candidate"
            if candidate_reason:
                reason_counts[candidate_reason] += 1
                removed.append({"key": key, "candidate": candidate, "weight": weight, "reason": candidate_reason})
            else:
                kept.append((candidate, weight))
        if kept:
            filtered[key] = kept
        else:
            removed_keys[reason or "all_candidates_filtered"] += 1
    return filtered, {"removed_pairs": len(removed), "removed_keys": sum(removed_keys.values()),
                      "removed_pairs_by_reason": dict(sorted(reason_counts.items())),
                      "removed_keys_by_reason": dict(sorted(removed_keys.items())),
                      "starter_keys_protected": sum(key in starter for key in base), "rows": removed}


def merge_tables(base, supplement, starter):
    merged = {key: list(values) for key, values in base.items()}
    sources = dict.fromkeys(merged, "public_v1")
    for name, table in (("original_supplement", supplement), ("starter", starter)):
        for key, values in table.items():
            merged[key] = list(values)
            sources[key] = name
    return dict(sorted(merged.items())), sources


def table_pairs(table):
    return {(key, candidate): weight for key, values in table.items() for candidate, weight in values}


def changes(before, after):
    old, new = table_pairs(before), table_pairs(after)
    return {"before_keys": len(before), "before_pairs": len(old), "after_keys": len(after), "after_pairs": len(new),
            "removed_keys": len(before.keys() - after.keys()), "added_keys": len(after.keys() - before.keys()),
            "removed_pairs": len(old.keys() - new.keys()), "added_pairs": len(new.keys() - old.keys()),
            "reweighted_shared_pairs": sum(old[pair] != new[pair] for pair in old.keys() & new.keys())}


def render(table):
    return "".join(f"{key} {word}\t{weight}\n" for key, values in table.items() for word, weight in values)


def protect_outputs(output, protected):
    if output.is_symlink():
        raise ValueError("candidate directory must not be a symbolic link")
    protected = {p.resolve() for p in protected}
    for name in ("refined.ngram.tsv", "public.ngram.tsv", "public.provenance.json", "public-review-sample.json", "public-filter-report.json"):
        path = output / name
        if path.is_symlink() or path.resolve() in protected:
            raise ValueError("candidate outputs must not overwrite inputs or follow symbolic links")


def generate(args):
    protected = [args.input, args.source_provenance, args.starter, Path(__file__)]
    if args.supplement:
        protected += [args.supplement, args.supplement_provenance]
    protect_outputs(args.output, protected)
    original_provenance = json.loads(args.source_provenance.read_text(encoding="utf-8"))
    if digest(args.input) != args.sha256 or original_provenance.get("public_sha256") != args.sha256:
        raise ValueError("v1 table hash differs from its pinned provenance")
    if args.jieba_path:
        sys.path.insert(0, str(args.jieba_path))
    import jieba
    if jieba.__version__ != "0.42.1":
        raise ValueError("requires jieba==0.42.1")
    tool = Path(jieba.__file__).parent
    dictionary = tool / "dict.txt"
    if digest(dictionary) != PINNED_DICTIONARY:
        raise ValueError("tokenizer dictionary differs from pinned v1 dictionary")
    tags = read_tags(dictionary)
    with tempfile.TemporaryDirectory(prefix="keytrack-refine-tokenizer-") as cache:
        tokenizer = jieba.Tokenizer(str(dictionary))
        tokenizer.tmp_dir = cache
        tokenizer.initialize()
    base, starter = read_table(args.input), read_table(args.starter)
    supplement = read_table(args.supplement) if args.supplement else {}
    supplement_provenance = json.loads(args.supplement_provenance.read_text()) if args.supplement else None
    if args.supplement:
        file_metadata = supplement_provenance.get("file", {})
        authored_hash = (supplement_provenance.get("sha256")
                         or (file_metadata.get("sha256") if isinstance(file_metadata, dict) else None))
        if authored_hash != digest(args.supplement):
            raise ValueError("original supplement differs from its authored provenance")
        expected_counts = supplement_provenance.get("counts")
        if expected_counts is not None and (expected_counts.get("keys") != len(supplement)
                                           or expected_counts.get("pairs") != sum(map(len, supplement.values()))):
            raise ValueError("original supplement counts differ from its authored provenance")
    refined, filtering = filter_table(base, starter, lambda text: tokenizer.cut(text, HMM=False), tags)
    public, owners = merge_tables(refined, supplement, starter)
    if any(public[key] != values for key, values in starter.items()):
        raise ValueError("starter complete-key ownership was not preserved")
    supplement_keys = {key for key, owner in owners.items() if owner == "original_supplement"}
    counts = {"input_keys": len(supplement), "input_pairs": sum(map(len, supplement.values())),
              "winning_keys": len(supplement_keys), "winning_pairs": sum(len(public[key]) for key in supplement_keys),
              "blocked_keys_by_starter": len(supplement.keys() & starter.keys()),
              "replaced_old_keys": len(supplement_keys & base.keys()),
              "new_keys": len(supplement_keys - base.keys()),
              "reintroduced_filtered_keys": len(supplement_keys & (base.keys() - refined.keys()))}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "refined.ngram.tsv").write_text(render(refined), encoding="utf-8")
    (args.output / "public.ngram.tsv").write_text(render(public), encoding="utf-8")
    (args.output / "public-filter-report.json").write_text(json.dumps(filtering, ensure_ascii=False, indent=2) + "\n")
    # Review the new original table completely, then a fixed sample of old keys.
    old_keys = [key for key in public if owners[key] == "public_v1"]
    head = sorted(old_keys, key=lambda key: (-len(public[key]), key))[:20]
    remaining = [key for key in old_keys if key not in head]
    uniform = random.Random(args.seed).sample(remaining, min(100, len(remaining)))
    audit = [{"group": group, "key": key, "source": owners[key], "candidates": public[key]}
             for group, keys in (("original_supplement", sorted(supplement_keys)), ("old_head", head), ("old_uniform", sorted(uniform)))
             for key in keys]
    (args.output / "public-review-sample.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    manifest = {
        "format_version": 3, "quality_rules_version": "conservative-v3", "status": "candidate; no post-scoring tuning",
        "source": {"file": display_path(args.input), "sha256": digest(args.input), "license": "MIT",
                   "original_provenance_file": display_path(args.source_provenance),
                   "original_provenance_sha256": digest(args.source_provenance)},
        "original_source_chain": original_provenance,
        "tokenizer": {"name": "jieba", "version": "0.42.1", "hmm": False, "license": "MIT",
                      "module_sha256": digest(Path(jieba.__file__)), "dictionary_sha256": digest(dictionary)},
        "generator_sha256": digest(Path(__file__)), "rules": list(RULES),
        "weighting": "unchanged per-source weights; starter > original supplement > public v1; complete-key replacement; no addition",
        "starter": {"file": display_path(args.starter), "sha256": digest(args.starter), "license": "MIT"},
        "original_supplement": {"file": display_path(args.supplement), "sha256": digest(args.supplement),
                                "provenance": supplement_provenance} if args.supplement else None,
        "filtering": {key: value for key, value in filtering.items() if key != "rows"},
        "supplement_merge": counts, "difference_from_public_v1": changes(base, public),
        "review": {"seed": args.seed, "all_original_winning_keys": len(supplement_keys),
                   "old_head_keys": len(head), "old_uniform_keys": len(uniform),
                   "method": "all winning original keys; 20 old keys with most candidates then lexical ties; 100 uniform old remainder"},
        "public_contexts": len(public), "public_records": sum(map(len, public.values())),
        "refined_sha256": digest(args.output / "refined.ngram.tsv"), "public_sha256": digest(args.output / "public.ngram.tsv"),
    }
    (args.output / "public.provenance.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DATA / "quality-v1/public.ngram.tsv")
    parser.add_argument("--sha256", default=PINNED_V1)
    parser.add_argument("--source-provenance", type=Path, default=DATA / "quality-v1/public.provenance.json")
    parser.add_argument("--starter", type=Path, default=DATA / "starter.ngram.tsv")
    parser.add_argument("--supplement", type=Path)
    parser.add_argument("--supplement-provenance", type=Path)
    parser.add_argument("--jieba-path", type=Path)
    parser.add_argument("--output", type=Path, default=DATA / "quality-v3")
    parser.add_argument("--seed", type=int, default=20261003)
    args = parser.parse_args()
    if bool(args.supplement) != bool(args.supplement_provenance):
        parser.error("original supplement and its provenance must be supplied together")
    try:
        print(json.dumps(generate(args), ensure_ascii=False, indent=2))
    except (OSError, ValueError, ImportError) as error:
        parser.exit(1, f"public prediction refinement failed: {error}\n")


if __name__ == "__main__":
    main()
