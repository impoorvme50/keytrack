"""Local Kev decision client and one-shot bridge for the optional Rime hotkey."""

from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path


DEFAULT_URL = "http://127.0.0.1:8009/v1/systemone"
MAX_REQUEST_BYTES = 16_384
MAX_RESPONSE_BYTES = 16_384
MAX_CANDIDATES = 5
TIMEOUT_SECONDS = 2.5
MIN_PROBABILITY = 0.90
MIN_MARGIN = 0.30


@dataclass(frozen=True)
class Decision:
    index: int
    probability: float
    margin: float


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("local Kev server must not redirect requests")


def open_local(request: urllib.request.Request, timeout: float):
    """Keep input on loopback even when system proxy settings are present."""
    if request.full_url not in (DEFAULT_URL, "http://127.0.0.1:8009/v1/models"):
        raise ValueError("Kev only accepts the local server")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    return opener.open(request, timeout=timeout)


def _request_data(raw: object) -> tuple[str, str, list[str]]:
    if not isinstance(raw, dict):
        raise ValueError("request must be an object")
    code = raw.get("input")
    previous = raw.get("previous_text")
    candidates = raw.get("candidates")
    if not isinstance(code, str) or not re.fullmatch(r"[a-z']{1,40}", code):
        raise ValueError("invalid pinyin input")
    if not isinstance(previous, str) or len(previous) > 160:
        raise ValueError("invalid previous text")
    if (
        not isinstance(candidates, list)
        or not 2 <= len(candidates) <= MAX_CANDIDATES
        or any(not isinstance(value, str) or not value or len(value) > 48 for value in candidates)
    ):
        raise ValueError("invalid candidates")
    return code, previous, candidates


def _kev_payload(code: str, previous: str, candidates: list[str]) -> dict:
    return {
        "model": "kev-latest",
        "state": (
            "用户正在使用拼音输入法。"
            f"已输入：{previous or '（无）'}。"
            f"当前拼音：{code}。"
        ),
        "questions": {
            "next": {
                "type": "choice",
                "instructions": "请选择最符合前文语境、接在已输入文字后最通顺的候选词。",
                "criteria": {f"c{index}": text for index, text in enumerate(candidates, 1)},
            }
        },
    }


def decide_candidate(
    raw: object, url: str = DEFAULT_URL, timeout_seconds: float = TIMEOUT_SECONDS
) -> Decision:
    """Return Kev's index and distribution strength for a validated request."""
    if url != DEFAULT_URL:
        raise ValueError("Kev bridge only accepts the local server")
    code, previous, candidates = _request_data(raw)
    payload = json.dumps(_kev_payload(code, previous, candidates), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with open_local(request, timeout=timeout_seconds) as response:
        if response.status != 200:
            raise ValueError("Kev request failed")
        data = response.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise ValueError("Kev response too large")
        result = json.loads(data)
    answer = result["answers"]["next"]
    choice = answer["choice"]
    if not isinstance(choice, str) or not re.fullmatch(r"c[1-5]", choice):
        raise ValueError("invalid Kev choice")
    index = int(choice[1:])
    if index > len(candidates):
        raise ValueError("Kev chose a missing candidate")
    distribution = answer["probabilities"]
    if not isinstance(distribution, dict) or set(distribution) != {
        f"c{i}" for i in range(1, len(candidates) + 1)
    }:
        raise ValueError("invalid Kev probability labels")
    values = list(distribution.values())
    if any(type(value) not in (float, int) or not math.isfinite(value) or value < 0 or value > 1 for value in values):
        raise ValueError("invalid Kev probabilities")
    # The server rounds displayed probabilities to two decimals.
    if not 0.95 <= sum(values) <= 1.05:
        raise ValueError("Kev probabilities do not sum to one")
    chosen = distribution[choice]
    runner_up = max((value for key, value in distribution.items() if key != choice), default=0)
    if chosen < runner_up:
        raise ValueError("Kev choice disagrees with probabilities")
    return Decision(index=index, probability=float(chosen), margin=float(chosen - runner_up))


def choose_candidate(raw: object, url: str = DEFAULT_URL) -> int:
    """Return the one-based index chosen by Kev for the manual hotkey."""
    return decide_candidate(raw, url=url).index


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: kev_rime_bridge.py REQUEST.json RESPONSE.txt", file=sys.stderr)
        return 2
    os.umask(0o077)
    request_path, response_path = map(Path, args)
    try:
        with request_path.open("rb") as source:
            data = source.read(MAX_REQUEST_BYTES + 1)
        if len(data) > MAX_REQUEST_BYTES:
            raise ValueError("request too large")
        decision = decide_candidate(json.loads(data))
        adopted = decision.probability >= MIN_PROBABILITY and decision.margin >= MIN_MARGIN
        temporary = response_path.with_name(f"{response_path.name}.{os.getpid()}.tmp")
        temporary.write_text(f"{decision.index}\t{int(adopted)}\n", encoding="ascii")
        os.replace(temporary, response_path)
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"Kev Rime bridge: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
