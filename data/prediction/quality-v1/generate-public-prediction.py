#!/usr/bin/env python3
"""Offline, reproducible public next-word extraction from pinned LCCC JSONL.

This maintainer tool never reads input history or downloads data. Install the
pinned jieba tool separately; only the derived pairs are needed at runtime.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import random
import re
import sys
import tempfile

PROJECT = Path(__file__).resolve().parent.parent
CJK = re.compile(r"[\u4e00-\u9fff]+\Z")
# Conservative editorial exclusion, independent of the evaluation examples.
EXCLUDED = ("傻逼", "妈的", "他妈", "操你", "草泥马", "艹", "卧槽", "滚蛋", "色情", "约炮", "嫖", "援交", "强奸", "自杀", "去死", "杀人", "毒品", "微信号", "手机号", "电话号码", "身份证", "银行卡", "加群", "网址", "宅男", "屌", "尼玛", "操蛋", "贱人", "脑残", "废物", "畜生", "狗日")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def clean(value: str) -> bool:
    return (bool(CJK.fullmatch(value)) and len(value) <= 12
            and not re.search(r"(.)\1\1", value)
            and not any(word in value for word in EXCLUDED))


def pairs(tokens, max_words=3, max_chars=12):
    """None is a hard boundary: punctuation, non-Chinese and unknown tokens."""
    for end in range(1, len(tokens)):
        candidate = tokens[end]
        if candidate is None:
            continue
        for size in range(1, min(max_words, end) + 1):
            prefix = tokens[end - size:end]
            if any(token is None for token in prefix):
                break
            key = "".join(prefix)
            if len(key) <= max_chars:
                yield key, candidate


def select_records(counts, *, min_count=5, max_contexts=10000, max_candidates=8,
                   support=None, min_dialogues=3):
    grouped = defaultdict(list)
    for (key, candidate), count in counts.items():
        if (count >= min_count and clean(key) and clean(candidate)
                and not re.search(r"(.)\1\1", key + candidate)
                and (support is None or support[key, candidate] >= min_dialogues)):
            grouped[key].append((candidate, count))
    # Prefer keys supported by many observations, using lexical tie-breaks.
    keys = sorted(grouped, key=lambda key: (-sum(n for _, n in grouped[key]), key))[:max_contexts]
    chosen = {}
    for key in sorted(keys):
        values = sorted(grouped[key], key=lambda item: (-item[1], item[0]))[:max_candidates]
        total = sum(n for _, n in grouped[key])
        chosen[key] = [(word, max(1, n * 1000000 // total), n) for word, n in values]
    return chosen


def render(records):
    return "".join(f"{key} {word}\t{weight}\n" for key, values in records.items()
                   for word, weight, _ in values)


def merge_starter(corpus: str, starter: str) -> str:
    """Editorial starter owns its complete keys; never add incomparable weights."""
    starter_keys = {line.split(" ", 1)[0] for line in starter.splitlines()}
    lines = [line for line in corpus.splitlines() if line.split(" ", 1)[0] not in starter_keys]
    lines.extend(starter.splitlines())
    return "\n".join(sorted(lines, key=lambda line: (line.split(" ", 1)[0], -int(line.rsplit("\t", 1)[1]), line))) + "\n"


def validate_outputs(directory, sources):
    protected = {path.resolve() for path in sources}
    for name in ("lccc.ngram.tsv", "public.ngram.tsv", "public-review-sample.json", "public.provenance.json"):
        path = directory / name
        if path.is_symlink() or path.resolve() in protected:
            raise ValueError("outputs must not overwrite sources or follow symbolic links")


def generate(args):
    validate_outputs(args.output, [args.input, args.starter, Path(__file__)])
    if args.jieba_path:
        sys.path.insert(0, str(args.jieba_path))
    import jieba
    if jieba.__version__ != "0.42.1":
        raise ValueError("requires jieba==0.42.1")
    if args.sample_every < 1 or args.min_count < 1 or args.max_contexts < 1 or args.min_dialogues < 1:
        raise ValueError("sampling and limits must be positive")
    observed_hash = digest(args.input)
    if observed_hash != args.sha256:
        raise ValueError("corpus SHA-256 differs from pinned input")
    tool = Path(jieba.__file__).parent
    # Never trust a shared jieba.cache that could have been built from another
    # dictionary. The reported hash must describe the bytes actually loaded.
    with tempfile.TemporaryDirectory(prefix="keytrack-public-tokenizer-") as cache:
        tokenizer = jieba.Tokenizer(str(tool / "dict.txt"))
        tokenizer.tmp_dir = cache
        tokenizer.initialize()
    counts = Counter()
    support = Counter()
    seen_dialogues = set()
    stats = Counter()
    rng = random.Random(args.seed)
    opener = gzip.open if args.input.suffix == ".gz" else open
    with opener(args.input, "rt", encoding="utf-8") as stream:
        for line in stream:
            stats["source_dialogues"] += 1
            if rng.randrange(args.sample_every):
                continue
            dialog = json.loads(line)
            if isinstance(dialog, dict):
                dialog = dialog.get("dialog")
            if not isinstance(dialog, list) or any(not isinstance(x, str) for x in dialog):
                raise ValueError("expected a dialogue list of strings")
            fingerprint = hashlib.sha256(json.dumps(dialog, ensure_ascii=False).encode()).digest()
            if fingerprint in seen_dialogues:
                stats["duplicate_dialogues"] += 1
                continue
            seen_dialogues.add(fingerprint)
            stats["sampled_dialogues"] += 1
            dialogue_pairs = set()
            for utterance in dialog:
                # The official LCCC files use ASCII spaces between characters.
                text = utterance.replace(" ", "")
                stats["utterances"] += 1
                if len(text) > 120 or any(word in text for word in EXCLUDED):
                    stats["excluded_utterances"] += 1
                    continue
                tokens = [token if clean(token) and tokenizer.FREQ.get(token, 0) >= (10000 if len(token) == 1 else 1) else None
                          for token in tokenizer.cut(text, HMM=False)]
                # Do not connect separate utterances or dialogue turns.
                events = list(pairs(tokens))
                counts.update(events)
                dialogue_pairs.update(events)
            support.update(dialogue_pairs)
    selected = select_records(counts, min_count=args.min_count, max_contexts=args.max_contexts,
                              support=support, min_dialogues=args.min_dialogues)
    corpus = render(selected)
    public = merge_starter(corpus, args.starter.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    corpus_path = args.output / "lccc.ngram.tsv"
    public_path = args.output / "public.ngram.tsv"
    corpus_path.write_text(corpus, encoding="utf-8")
    public_path.write_text(public, encoding="utf-8")
    # Fixed review sample, not full source dialogue; inspect before promotion.
    audit_rng = random.Random(args.seed)
    head = sorted(selected, key=lambda key: (-sum(n for _, _, n in selected[key]), key))[:20]
    remaining = [key for key in selected if key not in head]
    keys = audit_rng.sample(remaining, min(100, len(remaining)))
    audit = [{"group": group, "key": key, "candidates": selected[key],
              "supporting_dialogues": {word: support[key, word] for word, _, _ in selected[key]}}
             for group, group_keys in (("head", head), ("uniform", sorted(keys))) for key in group_keys]
    (args.output / "public-review-sample.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    manifest = {
        "format_version": 1, "status": "candidate; evaluate and review before promotion",
        "source": {"url": args.source_url, "revision": args.revision, "file": args.input.name,
                   "sha256": observed_hash, "bytes": args.input.stat().st_size, "license": "MIT"},
        "tokenizer": {"name": "jieba", "version": "0.42.1", "license": "MIT", "hmm": False,
                      "module_sha256": digest(Path(jieba.__file__)),
                      "dictionary_sha256": digest(tool / "dict.txt")},
        "generator_sha256": digest(Path(__file__)),
        "parameters": {"seed": args.seed, "sample_every": args.sample_every,
                       "min_count": args.min_count, "max_contexts": args.max_contexts,
                       "min_dialogues": args.min_dialogues, "single_token_dictionary_min_frequency": 10000,
                       "max_candidates": 8, "prefix_words": 3, "prefix_characters": 12},
        "sampling": dict(sorted(stats.items())),
        "weighting": "per-key normalized corpus counts; starter replaces its entire keys; no weight summing",
        "starter_sha256": digest(args.starter),
        "review_sampling": "20 keys with highest retained count total; 100 uniform keys from the remainder; same seed",
        "corpus_contexts": len(selected), "corpus_records": sum(map(len, selected.values())),
        "public_contexts": len({line.split(" ", 1)[0] for line in public.splitlines()}),
        "public_records": len(public.splitlines()),
        "corpus_sha256": digest(corpus_path), "public_sha256": digest(public_path),
    }
    (args.output / "public.provenance.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--jieba-path", type=Path)
    parser.add_argument("--starter", type=Path, default=PROJECT / "data/prediction/starter.ngram.tsv")
    parser.add_argument("--output", type=Path, default=PROJECT / "data/prediction")
    parser.add_argument("--seed", type=int, default=20261002)
    parser.add_argument("--sample-every", type=int, default=32)
    parser.add_argument("--min-count", type=int, default=5)
    parser.add_argument("--min-dialogues", type=int, default=3)
    parser.add_argument("--max-contexts", type=int, default=10000)
    args = parser.parse_args()
    try:
        print(json.dumps(generate(args), ensure_ascii=False, indent=2))
    except (OSError, ValueError, ImportError) as error:
        parser.exit(1, f"public prediction generation failed: {error}\n")


if __name__ == "__main__":
    main()
