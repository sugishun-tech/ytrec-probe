from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


@dataclass(slots=True)
class ChannelScore:
    rank: int
    channel_name: str
    channel_url: str
    score: float
    seed_coverage: float
    seed_appearances: int
    total_occurrences: int
    average_rank: float
    best_rank: int
    discounted_rank_score: float
    sample_videos: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "channel_name": self.channel_name,
            "channel_url": self.channel_url,
            "score": round(self.score, 2),
            "seed_coverage_pct": round(self.seed_coverage * 100, 2),
            "seed_appearances": self.seed_appearances,
            "total_occurrences": self.total_occurrences,
            "average_rank": round(self.average_rank, 2),
            "best_rank": self.best_rank,
            "discounted_rank_score": round(self.discounted_rank_score, 4),
            "sample_videos": " | ".join(self.sample_videos),
        }


def _channel_key(url: str, name: str) -> str:
    if url:
        parts = urlsplit(url)
        path = parts.path.rstrip("/").lower()
        if path:
            return path
    return "name:" + " ".join(name.lower().split())


def _target_keys(target_url: str, target_name: str) -> set[str]:
    keys = {_channel_key(target_url, target_name)}
    if target_name:
        keys.add(_channel_key("", target_name))
    return keys


def analyze(raw: dict[str, Any]) -> list[ChannelScore]:
    seeds = [seed for seed in raw.get("seed_videos", []) if not seed.get("error")]
    successful_seed_count = len(seeds)
    if successful_seed_count == 0:
        return []

    target_keys = _target_keys(raw.get("target_channel_url", ""), raw.get("target_channel_name", ""))
    buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "name": "",
            "url": "",
            "seed_ids": set(),
            "ranks": [],
            "discounted": 0.0,
            "videos": [],
        }
    )

    for seed_idx, seed in enumerate(seeds):
        seen_in_seed: set[str] = set()
        for rec in seed.get("recommendations", []):
            name = str(rec.get("channel_name", "")).strip()
            url = str(rec.get("channel_url", "")).strip()
            if not name:
                continue
            key = _channel_key(url, name)
            if key in target_keys or _channel_key("", name) in target_keys:
                continue
            rank = int(rec.get("rank") or 999)
            bucket = buckets[key]
            bucket["name"] = name
            bucket["url"] = url
            bucket["ranks"].append(rank)
            bucket["discounted"] += 1.0 / math.log2(rank + 1.0)
            if rec.get("video_title") and rec["video_title"] not in bucket["videos"]:
                bucket["videos"].append(str(rec["video_title"]))
            if key not in seen_in_seed:
                bucket["seed_ids"].add(seed_idx)
                seen_in_seed.add(key)

    max_discounted = max((bucket["discounted"] for bucket in buckets.values()), default=1.0)
    unsorted: list[ChannelScore] = []
    for bucket in buckets.values():
        appearances = len(bucket["seed_ids"])
        coverage = appearances / successful_seed_count
        discounted_norm = bucket["discounted"] / max_discounted if max_discounted else 0.0
        # Coverage gets most weight because repeating across independent seed videos is stronger
        # evidence than one very high placement on a single watch page.
        score = 100.0 * (0.72 * coverage + 0.28 * discounted_norm)
        ranks: list[int] = bucket["ranks"]
        unsorted.append(
            ChannelScore(
                rank=0,
                channel_name=bucket["name"],
                channel_url=bucket["url"],
                score=score,
                seed_coverage=coverage,
                seed_appearances=appearances,
                total_occurrences=len(ranks),
                average_rank=sum(ranks) / len(ranks),
                best_rank=min(ranks),
                discounted_rank_score=bucket["discounted"],
                sample_videos=bucket["videos"][:3],
            )
        )

    unsorted.sort(
        key=lambda row: (
            row.score,
            row.seed_appearances,
            -row.average_rank,
            row.total_occurrences,
        ),
        reverse=True,
    )
    for i, row in enumerate(unsorted, start=1):
        row.rank = i
    return unsorted
