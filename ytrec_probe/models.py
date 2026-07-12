from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Recommendation:
    rank: int
    video_title: str
    video_url: str
    channel_name: str
    channel_url: str


@dataclass(slots=True)
class SeedVideo:
    title: str
    url: str
    recommendations: list[Recommendation] = field(default_factory=list)
    error: str | None = None


@dataclass(slots=True)
class ProbeResult:
    target_channel_url: str
    target_channel_name: str
    collected_at: str
    mode: str
    locale: str
    seed_limit: int
    recommendation_limit: int
    seed_videos: list[SeedVideo] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
