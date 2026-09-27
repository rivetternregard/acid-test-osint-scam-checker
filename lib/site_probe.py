#!/usr/bin/env python3
"""site_probe — the pipeline behind Acid: load, pace, parse, rank.

Part of Acid. License: MIT.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path

PACE_S = 0.35
MAX_PARALLEL = 8


@dataclass
class Hit:
    title: str
    url: str = ""
    date: str = ""
    snippet: str = ""
    seen_on: list = field(default_factory=list)
    score: int = 1
    rank: float = 0.0


@dataclass
class Source:
    name: str
    item: dict
    hits: list = field(default_factory=list)
    error: str | None = None

    def parse(self) -> list:
        raw = self.item.get("results", [])
        out = []
        if isinstance(raw, list):
            for row in raw:
                if not isinstance(row, dict):
                    continue
                out.append(Hit(
                    title=str(row.get("title") or row.get("name") or self.name),
                    url=str(row.get("url") or row.get("link") or ""),
                    date=str(row.get("date") or row.get("published") or ""),
                    snippet=str(row.get("snippet") or row.get("summary") or "")[:240],
                ))
        return out


class Pace:
    def __init__(self, interval: float = PACE_S):
        self.interval = interval
        self.last = 0.0

    def slot(self):
        wait = self.last + self.interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.last = time.monotonic()


def merge_hits(sources: list) -> list:
    by_key: dict = {}
    for src in sources:
        for hit in src.hits:
            key = hit.url or hit.title
            prev = by_key.get(key)
            if prev:
                prev.seen_on.append(src.name)
                prev.score += 1
            else:
                hit.seen_on = [src.name]
                by_key[key] = hit
    return sorted(by_key.values(), key=lambda h: h.score, reverse=True)


def _parse_iso(value: str):
    import datetime as dt
    try:
        return dt.datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def rank(hits: list) -> list:
    for h in hits:
        when = _parse_iso(h.date)
        age_days = 0.0
        if when is not None:
            import datetime as dt
            age_days = max(0.0, (dt.datetime.now() - when).total_seconds() / 86400.0)
        age_score = math.log10(age_days + 1) if age_days > 0 else 0.0
        len_score = min(1.0, len(h.snippet) / 240)
        h.rank = h.score * 2 + age_score + len_score
    return sorted(hits, key=lambda h: h.rank, reverse=True)


def run(path: str) -> dict:
    pace = Pace()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    sources = [Source(k, v) for k, v in data.items() if not k.startswith("_")]
    report = {"checked": 0, "ok": 0, "hits": []}
    for src in sources:
        pace.slot()
        try:
            src.hits = src.parse()
            report["ok"] += 1
        except Exception as exc:
            src.error = str(exc)
        report["checked"] += 1
    report["hits"] = [h.__dict__ for h in rank(merge_hits(sources))]
    return report


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parent.parent / "sources.json")
    rep = run(target)
    print("checked %d, ok %d, hits %d" % (rep["checked"], rep["ok"], len(rep["hits"])))
