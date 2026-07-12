from __future__ import annotations

import asyncio
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import httpx

from .models import ProbeResult, Recommendation, SeedVideo

YOUTUBE_ORIGIN = "https://www.youtube.com"
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
DURATION_RE = re.compile(r"^\s*\d{1,2}:\d{2}(?::\d{2})?\s*$")
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)


def normalize_channel_url(url: str) -> str:
    value = url.strip()
    if not value:
        raise ValueError("channel URL is empty")
    if not value.startswith(("http://", "https://")):
        value = "https://" + value.lstrip("/")
    parts = urlsplit(value)
    if "youtube.com" not in parts.netloc.lower():
        raise ValueError("only youtube.com channel URLs are supported")
    path = parts.path.rstrip("/")
    for suffix in ("/videos", "/featured", "/shorts", "/streams", "/playlists", "/community"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return urlunsplit(("https", "www.youtube.com", path, "", ""))


def videos_tab_url(channel_url: str) -> str:
    return normalize_channel_url(channel_url) + "/videos"


def absolute_youtube_url(href: str | None) -> str:
    if not href:
        return ""
    return urljoin(YOUTUBE_ORIGIN, href)


def _video_id_from_href(href: str | None) -> str:
    if not href:
        return ""
    parts = urlsplit(absolute_youtube_url(href))
    if parts.path != "/watch":
        return ""
    value = parse_qs(parts.query).get("v", [""])[0]
    return value if VIDEO_ID_RE.fullmatch(value) else ""


def _canonical_watch_url(href: str | None) -> str:
    video_id = _video_id_from_href(href)
    return f"{YOUTUBE_ORIGIN}/watch?v={video_id}" if video_id else ""


def _valid_title(value: str, video_id: str = "") -> str:
    value = " ".join(value.split()).strip()
    if not value or DURATION_RE.fullmatch(value):
        return ""
    return value if value != video_id else ""


def _text(value: Any) -> str:
    """Extract user-visible text from common YouTube renderer shapes."""
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    for key in ("simpleText", "content", "text"):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()
    runs = value.get("runs")
    if isinstance(runs, list):
        joined = "".join(_text(run) for run in runs).strip()
        if joined:
            return joined
    return ""


def _endpoint_url(endpoint: Any) -> str:
    """Find a navigable URL inside legacy or view-model command wrappers."""
    if not isinstance(endpoint, dict):
        return ""

    command = endpoint.get("commandMetadata", {}).get("webCommandMetadata", {})
    url = command.get("url")
    if isinstance(url, str) and url:
        return absolute_youtube_url(url)

    browse = endpoint.get("browseEndpoint", {})
    canonical = browse.get("canonicalBaseUrl")
    if isinstance(canonical, str) and canonical:
        return absolute_youtube_url(canonical)
    browse_id = browse.get("browseId")
    if isinstance(browse_id, str) and browse_id:
        if browse_id.startswith("UC"):
            return absolute_youtube_url(f"/channel/{browse_id}")

    # New view-model responses wrap the actual endpoint under onTap /
    # innertubeCommand. Walk only command-shaped children before falling back
    # to a shallow recursive search.
    for key in ("innertubeCommand", "navigationEndpoint", "onTap", "command"):
        nested = endpoint.get(key)
        found = _endpoint_url(nested)
        if found:
            return found
    for value in endpoint.values():
        if isinstance(value, dict):
            found = _endpoint_url(value)
            if found:
                return found
    return ""


def _channel_from_renderer(renderer: dict[str, Any]) -> tuple[str, str]:
    for key in ("shortBylineText", "longBylineText", "ownerText", "channelName"):
        value = renderer.get(key)
        name = _text(value)
        if not name:
            continue
        if isinstance(value, dict):
            runs = value.get("runs")
            if isinstance(runs, list) and runs and isinstance(runs[0], dict):
                return name, _endpoint_url(runs[0].get("navigationEndpoint"))
        return name, ""
    return "", ""


def _parse_renderer(renderer: dict[str, Any]) -> tuple[str, str, str, str] | None:
    video_id = renderer.get("videoId")
    if not isinstance(video_id, str) or not VIDEO_ID_RE.fullmatch(video_id):
        return None
    title = ""
    for key in ("title", "headline", "accessibilityText"):
        title = _valid_title(_text(renderer.get(key)), video_id)
        if title:
            break
    channel_name, channel_url = _channel_from_renderer(renderer)
    return video_id, title or video_id, channel_name, channel_url


_NON_CHANNEL_METADATA_RE = re.compile(
    r"(?:\bviews?\b|watching|streamed|premiered|subscribers?|"
    r"回視聴|視聴中|登録者|配信済み|プレミア公開|"
    r"\b(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?) ago\b|"
    r"(?:秒|分|時間|日|週間|か月|ヶ月|年)前)",
    re.IGNORECASE,
)


def _looks_like_channel_name(value: str) -> bool:
    value = " ".join(value.split()).strip(" •·|-")
    if not value or DURATION_RE.fullmatch(value):
        return False
    if _NON_CHANNEL_METADATA_RE.search(value):
        return False
    if value.isdigit():
        return False
    return True


def _command_run_endpoint(text_obj: Any) -> str:
    if not isinstance(text_obj, dict):
        return ""
    runs = text_obj.get("commandRuns")
    if not isinstance(runs, list):
        return ""
    for run in runs:
        if not isinstance(run, dict):
            continue
        for key in ("onTap", "navigationEndpoint", "command"):
            url = _endpoint_url(run.get(key))
            if url:
                return url
    return ""


def _parse_lockup(lockup: dict[str, Any]) -> tuple[str, str, str, str] | None:
    video_id = lockup.get("contentId")
    if not isinstance(video_id, str) or not VIDEO_ID_RE.fullmatch(video_id):
        return None
    metadata = lockup.get("metadata", {}).get("lockupMetadataViewModel", {})
    title = _valid_title(_text(metadata.get("title")), video_id) or video_id
    channel_name = ""
    channel_url = ""
    fallback_names: list[str] = []

    rows = metadata.get("metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows", [])
    if isinstance(rows, list):
        for row_index, row in enumerate(rows):
            parts = row.get("metadataParts", []) if isinstance(row, dict) else []
            for part in parts if isinstance(parts, list) else []:
                if not isinstance(part, dict):
                    continue
                text_obj = part.get("text", {})
                candidate = " ".join(_text(text_obj).split()).strip()
                candidate_url = _command_run_endpoint(text_obj)

                # Current watch-next lockups commonly expose the owner as
                # metadataRows[0].metadataParts[0].text.content.  The command
                # may contain only browseId, without canonicalBaseUrl.
                if candidate and candidate_url and (
                    "/@" in candidate_url or "/channel/" in candidate_url
                ):
                    return video_id, title, candidate, candidate_url

                if candidate and _looks_like_channel_name(candidate):
                    fallback_names.append(candidate)
                    # The first metadata row is the owner line in current
                    # watch-next payloads. Keep it even when YouTube omits the
                    # navigation command entirely.
                    if row_index == 0 and not channel_name:
                        channel_name = candidate
                        channel_url = candidate_url

    if not channel_name and fallback_names:
        channel_name = fallback_names[0]
    return video_id, title, channel_name, channel_url


def _record_from_node(node: Any) -> tuple[str, str, str, str] | None:
    if not isinstance(node, dict):
        return None
    for key in ("compactVideoRenderer", "videoRenderer", "gridVideoRenderer"):
        renderer = node.get(key)
        if isinstance(renderer, dict):
            return _parse_renderer(renderer)
    lockup = node.get("lockupViewModel")
    if isinstance(lockup, dict):
        return _parse_lockup(lockup)
    return None


def _records_from_initial_data(data: Any) -> list[tuple[str, str, str, str]]:
    """Walk ytInitialData and preserve renderer order while de-duplicating videos."""
    records: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()

    def add(record: tuple[str, str, str, str] | None) -> None:
        if record is None or record[0] in seen:
            return
        seen.add(record[0])
        records.append(record)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            add(_record_from_node(node))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return records


def _dig(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _records_from_watch_next_data(data: Any) -> list[tuple[str, str, str, str]]:
    """Extract right-side Up Next items across legacy and current layouts."""
    roots: list[Any] = []

    # Fast paths for known response shapes.
    for root in (
        _dig(
            data,
            "contents",
            "twoColumnWatchNextResults",
            "secondaryResults",
            "secondaryResults",
            "results",
        ),
        _dig(
            data,
            "contents",
            "singleColumnWatchNextResults",
            "results",
            "results",
            "contents",
        ),
    ):
        if isinstance(root, (dict, list)):
            roots.append(root)

    # YouTube frequently inserts another wrapper or moves secondaryResults.
    # Find every container with that semantic name rather than betting the
    # parser on one exact nesting path.
    def find_secondary(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "secondaryResults" and isinstance(value, (dict, list)):
                    roots.append(value)
                find_secondary(value)
        elif isinstance(node, list):
            for value in node:
                find_secondary(value)

    find_secondary(data)

    records: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            record = _record_from_node(node)
            if record is not None and record[0] not in seen:
                seen.add(record[0])
                records.append(record)
                return
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for root in roots:
        walk(root)
    return records


def _records_from_next_response(
    data: Any, current_video_id: str
) -> list[tuple[str, str, str, str]]:
    """Parse /youtubei/v1/next, with a conservative generic fallback."""
    records = _records_from_watch_next_data(data)
    if not records:
        # The `next` endpoint is dedicated to watch-next data. If YouTube has
        # renamed the sidebar container, video renderers in this response are
        # still the least-wrong fallback and are far safer than scraping every
        # watch-page link.
        records = _records_from_initial_data(data)
    return [record for record in records if record[0] != current_video_id]

def _extract_balanced_object(source: str, object_start: int) -> str:
    depth = 0
    in_string = False
    escaped = False
    for index in range(object_start, len(source)):
        char = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[object_start : index + 1]
    raise ValueError("unterminated ytInitialData JSON object")


def _extract_yt_initial_data(html: str) -> dict[str, Any]:
    markers = (
        "var ytInitialData =",
        "window['ytInitialData'] =",
        'window["ytInitialData"] =',
        "ytInitialData =",
    )
    for marker in markers:
        search_from = 0
        while True:
            marker_index = html.find(marker, search_from)
            if marker_index < 0:
                break
            object_start = html.find("{", marker_index + len(marker))
            if object_start < 0:
                break
            try:
                payload = _extract_balanced_object(html, object_start)
                data = json.loads(payload)
            except (ValueError, json.JSONDecodeError):
                search_from = marker_index + len(marker)
                continue
            if isinstance(data, dict):
                return data
            search_from = marker_index + len(marker)
    raise ValueError("ytInitialData was not found in the HTML response")



def _extract_ytcfg(html: str) -> dict[str, Any]:
    """Merge ytcfg.set({...}) objects embedded in a YouTube HTML page."""
    config: dict[str, Any] = {}
    marker = "ytcfg.set("
    search_from = 0
    while True:
        marker_index = html.find(marker, search_from)
        if marker_index < 0:
            break
        object_start = html.find("{", marker_index + len(marker))
        if object_start < 0:
            break
        try:
            payload = _extract_balanced_object(html, object_start)
            value = json.loads(payload)
        except (ValueError, json.JSONDecodeError):
            search_from = marker_index + len(marker)
            continue
        if isinstance(value, dict):
            config.update(value)
        search_from = object_start + len(payload)

    # Some variants inline these values outside a ytcfg.set call. Preserve a
    # regex fallback so a harmless packaging experiment does not zero the run.
    for key in (
        "INNERTUBE_API_KEY",
        "INNERTUBE_CLIENT_VERSION",
        "INNERTUBE_CLIENT_NAME",
        "INNERTUBE_CONTEXT_CLIENT_NAME",
        "VISITOR_DATA",
    ):
        if key in config:
            continue
        match = re.search(
            rf'"{re.escape(key)}"\s*:\s*("(?:\\.|[^"\\])*"|\d+)',
            html,
        )
        if not match:
            continue
        raw = match.group(1)
        try:
            config[key] = json.loads(raw)
        except json.JSONDecodeError:
            pass
    return config


def _locale_parts(locale: str) -> tuple[str, str]:
    normalized = locale.replace("_", "-")
    pieces = [piece for piece in normalized.split("-") if piece]
    language = pieces[0].lower() if pieces else "en"
    region = pieces[1].upper() if len(pieces) > 1 else "US"
    return language, region


def _innertube_context(
    config: dict[str, Any], *, locale: str, user_agent: str
) -> dict[str, Any]:
    base = config.get("INNERTUBE_CONTEXT")
    context = deepcopy(base) if isinstance(base, dict) else {}
    client = context.setdefault("client", {})
    if not isinstance(client, dict):
        client = {}
        context["client"] = client

    language, region = _locale_parts(locale)
    client.setdefault("clientName", "WEB")
    version = config.get("INNERTUBE_CLIENT_VERSION")
    if isinstance(version, str) and version:
        client["clientVersion"] = version
    client["hl"] = language
    client["gl"] = region
    client["userAgent"] = user_agent
    client.setdefault("utcOffsetMinutes", 0)

    visitor = config.get("VISITOR_DATA")
    if isinstance(visitor, str) and visitor:
        client.setdefault("visitorData", visitor)
    return context

def _target_channel_name(data: dict[str, Any]) -> str:
    for path in (
        ("metadata", "channelMetadataRenderer", "title"),
        ("header", "c4TabbedHeaderRenderer", "title"),
    ):
        value = _dig(data, *path)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _renderer_stats(data: Any) -> dict[str, Any]:
    counts = {
        "compactVideoRenderer": 0,
        "videoRenderer": 0,
        "gridVideoRenderer": 0,
        "lockupViewModel": 0,
        "parsed_video_records": 0,
        "records_with_channel_name": 0,
    }
    samples: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("compactVideoRenderer", "videoRenderer", "gridVideoRenderer", "lockupViewModel"):
                if isinstance(node.get(key), dict):
                    counts[key] += 1
            record = _record_from_node(node)
            if record is not None:
                counts["parsed_video_records"] += 1
                if record[2]:
                    counts["records_with_channel_name"] += 1
                elif len(samples) < 5:
                    samples.append({
                        "video_id": record[0],
                        "title": record[1],
                        "node_keys": sorted(node.keys()),
                    })
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    counts["unresolved_samples"] = samples
    return counts


def _diagnostic_path(debug_dir: Path, stem: str, suffix: str) -> Path:
    debug_dir.mkdir(parents=True, exist_ok=True)
    return debug_dir / f"{stem}{suffix}"


async def _fetch_document(
    client: httpx.AsyncClient,
    url: str,
    *,
    debug_dir: Path,
    debug_stem: str,
) -> tuple[dict[str, Any], str, str]:
    response = await client.get(url)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"HTTP {response.status_code} while fetching {url}") from exc

    final_url = str(response.url)
    final_host = urlsplit(final_url).netloc.lower()
    if "consent.youtube.com" in final_host:
        raise RuntimeError("YouTube redirected the request to its consent page")

    try:
        return _extract_yt_initial_data(response.text), response.text, final_url
    except ValueError as exc:
        html_path = _diagnostic_path(debug_dir, debug_stem, ".html")
        meta_path = _diagnostic_path(debug_dir, debug_stem, ".json")
        html_path.write_text(response.text, encoding="utf-8")
        meta_path.write_text(
            json.dumps(
                {
                    "requested_url": url,
                    "final_url": final_url,
                    "status_code": response.status_code,
                    "content_type": response.headers.get("content-type", ""),
                    "response_bytes": len(response.content),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        raise RuntimeError(
            f"Could not parse ytInitialData. Diagnostics: {html_path} and {meta_path}"
        ) from exc


async def _fetch_next_response(
    client: httpx.AsyncClient,
    *,
    watch_url: str,
    video_id: str,
    html: str,
    locale: str,
    user_agent: str,
) -> dict[str, Any]:
    config = _extract_ytcfg(html)
    context = _innertube_context(config, locale=locale, user_agent=user_agent)
    client_config = context.get("client", {})
    version = client_config.get("clientVersion") if isinstance(client_config, dict) else None
    if not isinstance(version, str) or not version:
        raise RuntimeError("INNERTUBE_CLIENT_VERSION was not present in the watch HTML")

    api_key = config.get("INNERTUBE_API_KEY")
    params: dict[str, str] = {"prettyPrint": "false"}
    if isinstance(api_key, str) and api_key:
        params["key"] = api_key

    client_name_header = config.get("INNERTUBE_CONTEXT_CLIENT_NAME")
    if client_name_header is None:
        client_name_header = config.get("INNERTUBE_CLIENT_NAME", "1")
    headers = {
        "Content-Type": "application/json",
        "Origin": YOUTUBE_ORIGIN,
        "Referer": watch_url,
        "X-YouTube-Client-Name": str(client_name_header),
        "X-YouTube-Client-Version": version,
    }
    visitor = client_config.get("visitorData") if isinstance(client_config, dict) else None
    if isinstance(visitor, str) and visitor:
        headers["X-Goog-Visitor-Id"] = visitor

    payload = {
        "context": context,
        "videoId": video_id,
        "contentCheckOk": True,
        "racyCheckOk": True,
    }
    response = await client.post(
        f"{YOUTUBE_ORIGIN}/youtubei/v1/next",
        params=params,
        headers=headers,
        json=payload,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"HTTP {response.status_code} from youtubei/v1/next"
        ) from exc
    try:
        value = response.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError("youtubei/v1/next returned non-JSON content") from exc
    if not isinstance(value, dict):
        raise RuntimeError("youtubei/v1/next returned an unexpected JSON value")
    return value


async def collect(
    *,
    channel_url: str,
    seed_limit: int,
    recommendation_limit: int,
    locale: str,
    delay_seconds: float,
    timeout_seconds: float = 30.0,
    user_agent: str = DEFAULT_USER_AGENT,
    debug_dir: Path = Path(".ytrec-debug"),
) -> ProbeResult:
    if seed_limit < 1 or recommendation_limit < 1:
        raise ValueError("seed and recommendation limits must be positive")
    if timeout_seconds <= 0:
        raise ValueError("timeout must be positive")

    language = locale.replace("_", "-")
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": f"{language},ja;q=0.9,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    cookies = {
        # Avoid the consent interstitial where this cookie is honored.
        "SOCS": "CAI",
        "CONSENT": "YES+cb.20210328-17-p0.en+FX+917",
    }

    async with httpx.AsyncClient(
        headers=headers,
        cookies=cookies,
        follow_redirects=True,
        timeout=httpx.Timeout(timeout_seconds),
        http2=True,
    ) as client:
        channel_data, _channel_html, _channel_final_url = await _fetch_document(
            client,
            videos_tab_url(channel_url),
            debug_dir=debug_dir,
            debug_stem="seed-page",
        )
        target_name = _target_channel_name(channel_data)
        seed_records = _records_from_initial_data(channel_data)
        seeds: list[tuple[str, str]] = []
        seen_seed_ids: set[str] = set()
        for video_id, title, _channel_name, _channel_url in seed_records:
            if video_id in seen_seed_ids:
                continue
            seen_seed_ids.add(video_id)
            seeds.append(
                (
                    f"{YOUTUBE_ORIGIN}/watch?v={video_id}",
                    _valid_title(title, video_id) or video_id,
                )
            )
            if len(seeds) >= seed_limit:
                break

        if not seeds:
            raise RuntimeError(
                "No seed videos were found in the channel page's ytInitialData. "
                f"Diagnostics are under {debug_dir}."
            )

        result = ProbeResult(
            target_channel_url=normalize_channel_url(channel_url),
            target_channel_name=target_name,
            collected_at=datetime.now(timezone.utc).isoformat(),
            mode="browserless-http+innertube-next",
            locale=locale,
            seed_limit=seed_limit,
            recommendation_limit=recommendation_limit,
        )

        for index, (url, title) in enumerate(seeds, start=1):
            seed = SeedVideo(title=title, url=url)
            print(f"[{index}/{len(seeds)}] {title}", flush=True)
            try:
                current_video_id = _video_id_from_href(url)
                watch_data, watch_html, _watch_final_url = await _fetch_document(
                    client,
                    url,
                    debug_dir=debug_dir,
                    debug_stem=f"watch-{index:03d}",
                )
                seen_urls: set[str] = set()

                def append_records(
                    records: list[tuple[str, str, str, str]]
                ) -> None:
                    for video_id, rec_title, channel_name, channel_url in records:
                        if not channel_name:
                            continue
                        video_url = f"{YOUTUBE_ORIGIN}/watch?v={video_id}"
                        if video_url in seen_urls:
                            continue
                        seen_urls.add(video_url)
                        seed.recommendations.append(
                            Recommendation(
                                rank=len(seed.recommendations) + 1,
                                video_title=_valid_title(rec_title, video_id) or video_id,
                                video_url=video_url,
                                channel_name=channel_name,
                                channel_url=channel_url,
                            )
                        )
                        if len(seed.recommendations) >= recommendation_limit:
                            break

                # Old/complete watch pages still expose the right column in
                # ytInitialData. Use it first and avoid the extra request.
                append_records(_records_from_watch_next_data(watch_data))

                next_data: dict[str, Any] | None = None
                if len(seed.recommendations) < recommendation_limit:
                    next_data = await _fetch_next_response(
                        client,
                        watch_url=url,
                        video_id=current_video_id,
                        html=watch_html,
                        locale=locale,
                        user_agent=user_agent,
                    )
                    append_records(
                        _records_from_next_response(next_data, current_video_id)
                    )

                if not seed.recommendations:
                    html_path = _diagnostic_path(
                        debug_dir, f"watch-{index:03d}", ".html"
                    )
                    html_path.write_text(watch_html, encoding="utf-8")
                    stats = {"initial": _renderer_stats(watch_data)}
                    if next_data is not None:
                        next_path = _diagnostic_path(
                            debug_dir, f"watch-{index:03d}-next", ".json"
                        )
                        next_path.write_text(
                            json.dumps(next_data, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                        stats["next"] = _renderer_stats(next_data)
                    stats_path = _diagnostic_path(
                        debug_dir, f"watch-{index:03d}-stats", ".json"
                    )
                    stats_path.write_text(
                        json.dumps(stats, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    next_stats = stats.get("next", {})
                    seed.error = (
                        "No usable right-side recommendations were found. "
                        f"next parsed={next_stats.get('parsed_video_records', 0)}, "
                        f"with_channel={next_stats.get('records_with_channel_name', 0)}. "
                        f"Diagnostics: {stats_path}."
                    )
            except Exception as exc:
                seed.error = f"{type(exc).__name__}: {exc}"
            result.seed_videos.append(seed)
            if delay_seconds > 0 and index < len(seeds):
                await asyncio.sleep(delay_seconds)

        return result
