import asyncio
import csv
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx

from ytrec_probe.analysis import analyze
from ytrec_probe.collector import (
    _fetch_oembed_channel,
    _resolve_missing_channel_urls,
)
from ytrec_probe.models import Recommendation
from ytrec_probe.report import save_csv


def _recommendation(
    video_id: str,
    channel_name: str,
    channel_url: str = "",
) -> Recommendation:
    return Recommendation(
        rank=1,
        video_title=f"video {video_id}",
        video_url=f"https://www.youtube.com/watch?v={video_id}",
        channel_name=channel_name,
        channel_url=channel_url,
    )


def test_fetch_oembed_channel_uses_author_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/oembed"
        assert request.url.params["format"] == "json"
        assert request.url.params["url"] == (
            "https://www.youtube.com/watch?v=abcDEF_1234"
        )
        assert request.headers["accept"] == "application/json"
        return httpx.Response(
            200,
            json={
                "author_name": "Owner",
                "author_url": "https://m.youtube.com/@owner/videos?view=0",
            },
        )

    async def run() -> tuple[str, str]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await _fetch_oembed_channel(
                client,
                video_url="https://www.youtube.com/watch?v=abcDEF_1234",
            )

    assert asyncio.run(run()) == (
        "Owner",
        "https://www.youtube.com/@owner",
    )


def test_fetch_oembed_channel_rejects_non_channel_author_url() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "author_name": "Not a channel link",
                "author_url": "https://www.youtube.com/watch?v=wrong_123",
            },
        )

    async def run() -> tuple[str, str]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await _fetch_oembed_channel(
                client,
                video_url="https://www.youtube.com/watch?v=abcDEF_1234",
            )

    assert asyncio.run(run()) == ("Not a channel link", "")


def test_missing_urls_are_resolved_once_per_unique_video() -> None:
    recommendations = [
        _recommendation("videoA_001", "Repeated owner"),
        _recommendation("videoA_002", "Repeated owner"),
        _recommendation("videoB_001", "Other owner"),
    ]
    responses = {
        "videoA_001": ("Repeated owner", "https://www.youtube.com/@repeated"),
        "videoA_002": ("Repeated owner", "https://www.youtube.com/@repeated"),
        "videoB_001": ("Other owner", "https://www.youtube.com/channel/UCother123"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        video_url = request.url.params["url"]
        video_id = parse_qs(httpx.URL(video_url).query.decode())["v"][0]
        name, url = responses[video_id]
        return httpx.Response(200, json={"author_name": name, "author_url": url})

    async def run() -> tuple[int, int]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await _resolve_missing_channel_urls(client, recommendations)

    assert asyncio.run(run()) == (3, 3)
    assert [rec.channel_url for rec in recommendations] == [
        "https://www.youtube.com/@repeated",
        "https://www.youtube.com/@repeated",
        "https://www.youtube.com/channel/UCother123",
    ]


def test_same_display_name_keeps_distinct_channel_urls() -> None:
    recommendations = [
        _recommendation("sameNm_001", "Same display name"),
        _recommendation("sameNm_002", "Same display name"),
    ]
    responses = {
        "sameNm_001": ("First actual owner", "https://www.youtube.com/@first"),
        "sameNm_002": ("Second actual owner", "https://www.youtube.com/@second"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        video_url = request.url.params["url"]
        video_id = parse_qs(httpx.URL(video_url).query.decode())["v"][0]
        name, url = responses[video_id]
        return httpx.Response(200, json={"author_name": name, "author_url": url})

    async def run() -> tuple[int, int]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await _resolve_missing_channel_urls(client, recommendations)

    assert asyncio.run(run()) == (2, 2)
    assert [rec.channel_url for rec in recommendations] == [
        "https://www.youtube.com/@first",
        "https://www.youtube.com/@second",
    ]


def test_sugishun_recording_populates_every_csv_channel_url(tmp_path: Path) -> None:
    """Replay the bundled 2026-07-12 @sugishun_tech collection.

    That real recording contains 400 recommendations and originally had zero
    channel URLs.  MockTransport keeps the test deterministic while exercising
    the exact missing-URL population and CSV paths on the full recording.
    """
    project_root = Path(__file__).resolve().parents[1]
    raw = json.loads(
        (
            project_root
            / "tests/fixtures/sugishun_tech_2026-07-12_v0.3.2.json"
        ).read_text(encoding="utf-8")
    )
    rec_dicts = [
        rec
        for seed in raw["seed_videos"]
        for rec in seed["recommendations"]
    ]
    assert len(rec_dicts) == 400
    assert sum(bool(rec["channel_url"]) for rec in rec_dicts) == 0

    recommendations = [
        Recommendation(
            rank=int(rec["rank"]),
            video_title=rec["video_title"],
            video_url=rec["video_url"],
            channel_name=rec["channel_name"],
            channel_url=rec["channel_url"],
        )
        for rec in rec_dicts
    ]
    name_by_video_url = {rec.video_url: rec.channel_name for rec in recommendations}

    def fixture_channel_url(channel_name: str) -> str:
        digest = hashlib.sha1(channel_name.encode("utf-8")).hexdigest()[:16]
        return f"https://www.youtube.com/@fixture_{digest}"

    def handler(request: httpx.Request) -> httpx.Response:
        video_url = request.url.params["url"]
        channel_name = name_by_video_url[video_url]
        return httpx.Response(
            200,
            json={
                "author_name": channel_name,
                "author_url": fixture_channel_url(channel_name),
            },
        )

    async def run() -> tuple[int, int]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await _resolve_missing_channel_urls(client, recommendations)

    unique_video_urls = {rec.video_url for rec in recommendations}
    assert asyncio.run(run()) == (len(unique_video_urls), 400)
    assert all(rec.channel_url for rec in recommendations)

    for rec_dict, rec in zip(rec_dicts, recommendations, strict=True):
        rec_dict["channel_url"] = rec.channel_url

    csv_path = tmp_path / "channels.csv"
    save_csv(csv_path, analyze(raw))
    with csv_path.open(encoding="utf-8-sig", newline="") as fp:
        rows = list(csv.DictReader(fp))
    assert rows
    assert all(row["channel_url"] for row in rows)


def test_collect_sugishun_flow_writes_resolved_channel_url(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Exercise channel page -> watch page -> oEmbed as one collection flow."""
    import ytrec_probe.collector as collector

    seed_id = "seedAA_1234"
    related_id = "recBBB_5678"
    channel_data = {
        "metadata": {"channelMetadataRenderer": {"title": "sugishun"}},
        "contents": [
            {
                "videoRenderer": {
                    "videoId": seed_id,
                    "title": {"simpleText": "Seed video"},
                    "shortBylineText": {"runs": [{"text": "sugishun"}]},
                }
            }
        ],
    }
    watch_data = {
        "contents": {
            "twoColumnWatchNextResults": {
                "secondaryResults": {
                    "secondaryResults": {
                        "results": [
                            {
                                "lockupViewModel": {
                                    "contentId": related_id,
                                    "metadata": {
                                        "lockupMetadataViewModel": {
                                            "title": {"content": "Related video"},
                                            "metadata": {
                                                "contentMetadataViewModel": {
                                                    "metadataRows": [
                                                        {
                                                            "metadataParts": [
                                                                {
                                                                    "text": {
                                                                        "content": "Related owner"
                                                                    }
                                                                }
                                                            ]
                                                        }
                                                    ]
                                                }
                                            },
                                        }
                                    },
                                }
                            }
                        ]
                    }
                }
            }
        }
    }

    def html_with_initial_data(data: dict) -> str:
        return (
            "<html><script>var ytInitialData = "
            + json.dumps(data, ensure_ascii=False)
            + ";</script></html>"
        )

    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path == "/@sugishun_tech/videos":
            return httpx.Response(200, text=html_with_initial_data(channel_data))
        if request.url.path == "/watch":
            assert request.url.params["v"] == seed_id
            return httpx.Response(200, text=html_with_initial_data(watch_data))
        if request.url.path == "/oembed":
            assert request.url.params["url"] == (
                f"https://www.youtube.com/watch?v={related_id}"
            )
            return httpx.Response(
                200,
                json={
                    "author_name": "Related owner",
                    "author_url": "https://www.youtube.com/@related_owner",
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    real_async_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        kwargs["http2"] = False
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(collector.httpx, "AsyncClient", client_factory)

    result = asyncio.run(
        collector.collect(
            channel_url="https://www.youtube.com/@sugishun_tech",
            seed_limit=1,
            recommendation_limit=1,
            locale="ja-JP",
            delay_seconds=0,
            debug_dir=tmp_path / "debug",
        )
    )

    assert result.target_channel_url == "https://www.youtube.com/@sugishun_tech"
    assert result.mode == "browserless-http+innertube-next+oembed"
    assert len(result.seed_videos) == 1
    assert result.seed_videos[0].error is None
    assert result.seed_videos[0].recommendations[0].channel_url == (
        "https://www.youtube.com/@related_owner"
    )
    assert sum("/oembed" in url for url in requests) == 1
