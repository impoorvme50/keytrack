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
NUMERAL = re.compile(r"[零〇一二三四五六七八九十百千万亿两廿卅]+\Z")
QUALITY_RULES_VERSION = 2
PREFIX_INITIAL_PARTICLES = ("u", "y", "e", "q")
FUNCTIONAL_TAILS = ("u", "y", "p", "c", "q", "m", "e", "x", "w", "eng")
UNSUITABLE_ACTION_TOKENS = frozenset(("杀", "砍", "揍", "虐"))
# Conservative editorial exclusion, independent of the evaluation examples.
EXCLUDED = ("傻逼", "妈的", "他妈", "操你", "草泥马", "艹", "卧槽", "滚蛋", "色情", "约炮", "嫖", "援交", "强奸", "自杀", "去死", "杀人", "毒品", "微信号", "手机号", "电话号码", "身份证", "银行卡", "加群", "网址", "宅男", "屌", "尼玛", "操蛋", "贱人", "脑残", "废物", "畜生", "狗日", "车祸", "虐待", "家暴", "打老婆", "打女人", "报复社会")


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


def dictionary_metadata(path):
    """Read POS hints from the very dictionary used by the tokenizer."""
    tags, frequencies = {}, {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        fields = line.split()
        if len(fields) != 3 or not fields[1].isdecimal():
            raise ValueError(f"invalid tokenizer dictionary entry at line {number}")
        word, frequency, tag = fields
        tags[word], frequencies[word] = tag, int(frequency)
    return tags, frequencies


def ordinary_repetition(tokens, tags):
    """Only grammatical A-not-A repetition is accepted among word tokens."""
    return (len(tokens) == 3 and tokens[0] == tokens[2] and tokens[1] in ("不", "没")
            and tags.get(tokens[0], "").startswith(("v", "a")))


def prefix_quality(tokens, tags):
    if tags.get(tokens[0], "").startswith(PREFIX_INITIAL_PARTICLES):
        return False
    return len(set(tokens)) == len(tokens) or ordinary_repetition(tokens, tags)


def semantic_tail(word, tags, frequencies):
    tag = tags.get(word, "x")
    if word in ("不", "没"):
        return False
    if tag.startswith("nr"):
        return len(word) >= 2 and frequencies.get(word, 0) >= 1000
    if tag.startswith(FUNCTIONAL_TAILS) or tag.endswith("g") or (len(word) == 1 and tag.startswith("d")):
        return len(word) >= 2 and frequencies.get(word, 0) >= 10000
    return True


def contexts(tokens, max_words=3, max_chars=12, tags=None, segment_initial_phrases=False):
    """Each yielded end position is one complete-key observation."""
    segment_start = 0
    for end in range(1, len(tokens)):
        if tokens[end - 1] is None:
            segment_start = end
        if tokens[end] is None:
            continue
        for size in range(1, min(max_words, end) + 1):
            prefix = tokens[end - size:end]
            if any(token is None for token in prefix):
                break
            if segment_initial_phrases and size > 1 and end - size != segment_start:
                continue
            key = "".join(prefix)
            if len(key) <= max_chars and (tags is None or prefix_quality(prefix, tags)):
                yield key, end, prefix


def pairs(tokens, max_words=3, max_chars=12, *, tags=None, frequencies=None,
          max_candidate_words=1, max_candidate_chars=8, shapes=None):
    """None is a hard boundary; optional POS rules produce complete spans."""
    for key, end, prefix in contexts(tokens, max_words, max_chars, tags,
                                      segment_initial_phrases=tags is not None):
        for size in range(1, min(max_candidate_words, len(tokens) - end) + 1):
            span = tokens[end:end + size]
            if any(token is None for token in span):
                break
            candidate = "".join(span)
            if len(candidate) > max_candidate_chars:
                break
            if tags is not None:
                if prefix[-1] == span[0] or (len(set(span)) != len(span) and not ordinary_repetition(span, tags)):
                    continue
                if not semantic_tail(span[-1], tags, frequencies):
                    continue
            if shapes is not None:
                shapes[candidate].add(tuple(span))
            yield key, candidate


def is_token_extension(short, long, shapes):
    return any(len(b) > len(a) and b[:len(a)] == a for a in shapes.get(short, ())
               for b in shapes.get(long, ()))


def collapse_completions(key, values, support, shapes, retained_percent=70):
    """Remove a short completion only when an actual longer token span dominates."""
    removed = set()
    for short, short_count in values:
        for long, long_count in values:
            if (short != long and long_count * 100 >= short_count * retained_percent
                    and is_token_extension(short, long, shapes)
                    and support[key, long] * 100 >= support[key, short] * retained_percent):
                removed.add(short)
                break
    return [(word, count) for word, count in values if word not in removed]


def select_records(counts, *, min_count=5, max_contexts=10000, max_candidates=8,
                   support=None, min_dialogues=3, observations=None, min_share_percent=0,
                   shapes=None, retained_percent=70, selection_stats=None,
                   utterance_support=None, min_utterances=3):
    grouped = defaultdict(list)
    for (key, candidate), count in counts.items():
        if (count >= min_count and clean(key) and clean(candidate)
                and not re.search(r"(.)\1\1", key + candidate)
                and (support is None or support[key, candidate] >= min_dialogues)
                and (utterance_support is None or utterance_support[key, candidate] >= min_utterances)
                and (observations is None or count * 100 >= observations[key] * min_share_percent)):
            grouped[key].append((candidate, count))
    if shapes is not None and support is not None:
        for key, values in grouped.items():
            revised = collapse_completions(key, values, support, shapes, retained_percent)
            if selection_stats is not None:
                selection_stats["nested_candidates_removed"] += len(values) - len(revised)
            grouped[key] = revised
    # Prefer keys supported by many observations, using lexical tie-breaks.
    keys = sorted(grouped, key=lambda key: (-sum(n for _, n in grouped[key]), key))[:max_contexts]
    chosen = {}
    for key in sorted(keys):
        values = sorted(grouped[key], key=lambda item: (-item[1], item[0]))[:max_candidates]
        total = observations[key] if observations is not None else sum(n for _, n in grouped[key])
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
    if args.min_utterances < 1:
        raise ValueError("utterance support must be positive")
    if not 0 <= args.min_share_percent <= 100:
        raise ValueError("minimum candidate share must be between 0 and 100 percent")
    observed_hash = digest(args.input)
    if observed_hash != args.sha256:
        raise ValueError("corpus SHA-256 differs from pinned input")
    tool = Path(jieba.__file__).parent
    tags, frequencies = dictionary_metadata(tool / "dict.txt")
    # Never trust a shared jieba.cache that could have been built from another
    # dictionary. The reported hash must describe the bytes actually loaded.
    with tempfile.TemporaryDirectory(prefix="keytrack-public-tokenizer-") as cache:
        tokenizer = jieba.Tokenizer(str(tool / "dict.txt"))
        tokenizer.tmp_dir = cache
        tokenizer.initialize()
    counts = Counter()
    support = Counter()
    observations = Counter()
    utterance_support = Counter()
    seen_utterances = set()
    shapes = defaultdict(set)
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
                raw_tokens = list(tokenizer.cut(text, HMM=False))
                if any(token in UNSUITABLE_ACTION_TOKENS for token in raw_tokens):
                    stats["excluded_utterances"] += 1
                    continue
                tokens = [token if clean(token) and not NUMERAL.fullmatch(token)
                          and tokenizer.FREQ.get(token, 0) >= (10000 if len(token) == 1 else 100) else None
                          for token in raw_tokens]
                # Do not connect separate utterances or dialogue turns.
                observations.update(key for key, _, _ in contexts(tokens, tags=tags, segment_initial_phrases=True))
                events = list(pairs(tokens, tags=tags, frequencies=frequencies,
                                    max_candidate_words=3, shapes=shapes))
                counts.update(events)
                dialogue_pairs.update(events)
                utterance_fingerprint = hashlib.sha256(text.encode("utf-8")).digest()
                if utterance_fingerprint not in seen_utterances:
                    seen_utterances.add(utterance_fingerprint)
                    utterance_support.update(set(events))
                else:
                    stats["repeated_utterances"] += 1
            support.update(dialogue_pairs)
    selected = select_records(counts, min_count=args.min_count, max_contexts=args.max_contexts,
                              support=support, min_dialogues=args.min_dialogues,
                              observations=observations, min_share_percent=args.min_share_percent,
                              shapes=shapes, selection_stats=stats,
                              utterance_support=utterance_support, min_utterances=args.min_utterances)
    stats["distinct_usable_utterances"] = len(seen_utterances)
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
              "supporting_dialogues": {word: support[key, word] for word, _, _ in selected[key]},
              "key_observations": observations[key],
              "distinct_utterances": {word: utterance_support[key, word] for word, _, _ in selected[key]},
              "candidate_tokenizations": {word: sorted(shapes[word]) for word, _, _ in selected[key]}}
             for group, group_keys in (("head", head), ("uniform", sorted(keys))) for key in group_keys]
    (args.output / "public-review-sample.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    manifest = {
        "format_version": 2, "quality_rules_version": QUALITY_RULES_VERSION,
        "status": "candidate; evaluate and review before promotion",
        "source": {"url": args.source_url, "revision": args.revision, "file": args.input.name,
                   "sha256": observed_hash, "bytes": args.input.stat().st_size, "license": "MIT"},
        "tokenizer": {"name": "jieba", "version": "0.42.1", "license": "MIT", "hmm": False,
                      "module_sha256": digest(Path(jieba.__file__)),
                      "dictionary_sha256": digest(tool / "dict.txt")},
        "generator_sha256": digest(Path(__file__)),
        "parameters": {"seed": args.seed, "sample_every": args.sample_every,
                       "min_count": args.min_count, "max_contexts": args.max_contexts,
                       "min_dialogues": args.min_dialogues, "single_token_dictionary_min_frequency": 10000,
                       "multi_token_dictionary_min_frequency": 100,
                       "min_distinct_utterances": args.min_utterances,
                       "min_share_percent": args.min_share_percent,
                       "max_candidates": 8, "prefix_words": 3, "prefix_characters": 12,
                       "candidate_words": 3, "candidate_characters": 8,
                       "complete_word_frequency_override": 10000, "name_tag_min_frequency": 1000,
                       "nested_completion_retained_percent": 70},
        "sampling": dict(sorted(stats.items())),
        "weighting": "count / full-key observation count in integer millionths; overlapping completions are not probabilities; starter replaces its entire keys; no weight summing",
        "structural_rules": ["pure Chinese numerals are hard boundaries",
                             "no particle-initial or mechanical repeated-token prefixes; grammatical A-not-A retained",
                             "constructed phrase keys begin at a hard-boundary-separated segment start",
                             "distinct utterance support prevents copied text in different dialogues inflating coverage",
                             "completions end with content words or frequent dictionary lexical units",
                             "standalone negative particles and dictionary morpheme tags are not completions",
                             "utterances containing standalone violent-action tokens are excluded",
                             "dominant longer token spans replace nested short spans"],
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
    parser.add_argument("--min-count", type=int, default=8)
    parser.add_argument("--min-dialogues", type=int, default=5)
    parser.add_argument("--min-utterances", type=int, default=3)
    parser.add_argument("--min-share-percent", type=int, default=3)
    parser.add_argument("--max-contexts", type=int, default=10000)
    args = parser.parse_args()
    try:
        print(json.dumps(generate(args), ensure_ascii=False, indent=2))
    except (OSError, ValueError, ImportError) as error:
        parser.exit(1, f"public prediction generation failed: {error}\n")


if __name__ == "__main__":
    main()
