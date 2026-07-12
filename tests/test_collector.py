from ytrec_probe.collector import (
    _canonical_watch_url,
    _records_from_initial_data,
    _video_id_from_href,
)


def test_video_id_from_relative_and_absolute_watch_urls() -> None:
    assert _video_id_from_href("/watch?v=abcDEF_1234&list=x") == "abcDEF_1234"
    assert _video_id_from_href("https://www.youtube.com/watch?v=abcDEF_1234&t=10") == "abcDEF_1234"
    assert _canonical_watch_url("/watch?v=abcDEF_1234&list=x") == (
        "https://www.youtube.com/watch?v=abcDEF_1234"
    )


def test_records_from_legacy_renderer() -> None:
    data = {
        "contents": [
            {
                "videoRenderer": {
                    "videoId": "abcDEF_1234",
                    "title": {"runs": [{"text": "Video title"}]},
                    "shortBylineText": {
                        "runs": [
                            {
                                "text": "Channel name",
                                "navigationEndpoint": {
                                    "commandMetadata": {
                                        "webCommandMetadata": {"url": "/@channel"}
                                    }
                                },
                            }
                        ]
                    },
                }
            }
        ]
    }
    assert _records_from_initial_data(data) == [
        (
            "abcDEF_1234",
            "Video title",
            "Channel name",
            "https://www.youtube.com/@channel",
        )
    ]


def test_records_from_lockup_view_model() -> None:
    data = {
        "lockupViewModel": {
            "contentId": "xyzXYZ_9876",
            "metadata": {
                "lockupMetadataViewModel": {
                    "title": {"content": "New layout title"},
                }
            },
        }
    }
    assert _records_from_initial_data(data)[0][:2] == (
        "xyzXYZ_9876",
        "New layout title",
    )


def test_watch_next_extraction_is_limited_to_secondary_results() -> None:
    from ytrec_probe.collector import _records_from_watch_next_data

    data = {
        "contents": {
            "twoColumnWatchNextResults": {
                "results": {
                    "results": {
                        "contents": [
                            {
                                "videoPrimaryInfoRenderer": {
                                    "title": {"runs": [{"text": "Current video"}]}
                                }
                            }
                        ]
                    }
                },
                "secondaryResults": {
                    "secondaryResults": {
                        "results": [
                            {
                                "compactVideoRenderer": {
                                    "videoId": "sideBAR_123",
                                    "title": {"simpleText": "Sidebar video"},
                                    "shortBylineText": {
                                        "runs": [
                                            {
                                                "text": "Sidebar channel",
                                                "navigationEndpoint": {
                                                    "commandMetadata": {
                                                        "webCommandMetadata": {"url": "/@sidebar"}
                                                    }
                                                },
                                            }
                                        ]
                                    },
                                }
                            }
                        ]
                    }
                },
            }
        }
    }

    assert _records_from_watch_next_data(data) == [
        (
            "sideBAR_123",
            "Sidebar video",
            "Sidebar channel",
            "https://www.youtube.com/@sidebar",
        )
    ]


def test_duration_text_is_not_accepted_as_video_title() -> None:
    from ytrec_probe.collector import _valid_title

    assert _valid_title("4:19", "abcDEF_1234") == ""
    assert _valid_title("1:04:19", "abcDEF_1234") == ""
    assert _valid_title("Actual video title", "abcDEF_1234") == "Actual video title"


def test_extract_yt_initial_data_handles_braces_inside_strings() -> None:
    from ytrec_probe.collector import _extract_yt_initial_data

    html = '''
    <html><script>
    var ytInitialData = {"message":"brace } inside string", "contents":{"x":1}};
    </script></html>
    '''
    assert _extract_yt_initial_data(html) == {
        "message": "brace } inside string",
        "contents": {"x": 1},
    }


def test_extract_ytcfg_merges_context_and_direct_values() -> None:
    from ytrec_probe.collector import _extract_ytcfg

    html = '''
    <script>
      ytcfg.set({"INNERTUBE_CONTEXT":{"client":{"clientName":"WEB","clientVersion":"2.20260710.01.00"}}});
      ytcfg.set({"INNERTUBE_API_KEY":"page-key","VISITOR_DATA":"visitor-123","INNERTUBE_CONTEXT_CLIENT_NAME":1});
    </script>
    '''
    config = _extract_ytcfg(html)
    assert config["INNERTUBE_API_KEY"] == "page-key"
    assert config["VISITOR_DATA"] == "visitor-123"
    assert config["INNERTUBE_CONTEXT"]["client"]["clientVersion"] == "2.20260710.01.00"


def test_next_response_falls_back_to_video_renderers_and_excludes_current() -> None:
    from ytrec_probe.collector import _records_from_next_response

    data = {
        "responseContext": {},
        "renamedSidebarContainer": {
            "items": [
                {
                    "compactVideoRenderer": {
                        "videoId": "current_123",
                        "title": {"simpleText": "Current"},
                        "shortBylineText": {"runs": [{"text": "Current channel"}]},
                    }
                },
                {
                    "compactVideoRenderer": {
                        "videoId": "related_456",
                        "title": {"simpleText": "Related"},
                        "shortBylineText": {
                            "runs": [
                                {
                                    "text": "Related channel",
                                    "navigationEndpoint": {
                                        "browseEndpoint": {
                                            "canonicalBaseUrl": "/@related"
                                        }
                                    },
                                }
                            ]
                        },
                    }
                },
            ]
        },
    }
    assert _records_from_next_response(data, "current_123") == [
        (
            "related_456",
            "Related",
            "Related channel",
            "https://www.youtube.com/@related",
        )
    ]


def test_lockup_view_model_reads_nested_channel_command() -> None:
    from ytrec_probe.collector import _records_from_initial_data

    data = {
        "lockupViewModel": {
            "contentId": "lockup_1234",
            "metadata": {
                "lockupMetadataViewModel": {
                    "title": {"content": "Lockup title"},
                    "metadata": {
                        "contentMetadataViewModel": {
                            "metadataRows": [
                                {
                                    "metadataParts": [
                                        {
                                            "text": {
                                                "content": "Nested channel",
                                                "commandRuns": [
                                                    {
                                                        "onTap": {
                                                            "innertubeCommand": {
                                                                "browseEndpoint": {
                                                                    "canonicalBaseUrl": "/@nested"
                                                                }
                                                            }
                                                        }
                                                    }
                                                ],
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
    assert _records_from_initial_data(data) == [
        (
            "lockup_1234",
            "Lockup title",
            "Nested channel",
            "https://www.youtube.com/@nested",
        )
    ]


def test_fetch_next_response_posts_watch_next_request() -> None:
    import asyncio
    import json

    import httpx

    from ytrec_probe.collector import _fetch_next_response

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/youtubei/v1/next"
        assert request.url.params["prettyPrint"] == "false"
        assert request.url.params["key"] == "page-key"
        assert request.headers["x-youtube-client-name"] == "1"
        assert request.headers["x-youtube-client-version"] == "2.20260710.01.00"
        payload = json.loads(request.content)
        assert payload["videoId"] == "abcDEF_1234"
        assert payload["context"]["client"]["clientName"] == "WEB"
        assert payload["context"]["client"]["hl"] == "ja"
        assert payload["context"]["client"]["gl"] == "JP"
        return httpx.Response(200, json={"ok": True})

    html = '''
    <script>
    ytcfg.set({
      "INNERTUBE_API_KEY":"page-key",
      "INNERTUBE_CONTEXT_CLIENT_NAME":1,
      "INNERTUBE_CONTEXT":{"client":{"clientName":"WEB","clientVersion":"2.20260710.01.00"}}
    });
    </script>
    '''

    async def run() -> dict:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await _fetch_next_response(
                client,
                watch_url="https://www.youtube.com/watch?v=abcDEF_1234",
                video_id="abcDEF_1234",
                html=html,
                locale="ja-JP",
                user_agent="test-agent",
            )

    assert asyncio.run(run()) == {"ok": True}


def test_lockup_channel_name_from_first_metadata_part_without_url() -> None:
    from ytrec_probe.collector import _records_from_watch_next_data

    data = {
        "contents": {
            "twoColumnWatchNextResults": {
                "secondaryResults": {
                    "secondaryResults": {
                        "results": [
                            {
                                "lockupViewModel": {
                                    "contentId": "newLock_123",
                                    "metadata": {
                                        "lockupMetadataViewModel": {
                                            "title": {"content": "Current layout video"},
                                            "metadata": {
                                                "contentMetadataViewModel": {
                                                    "metadataRows": [
                                                        {
                                                            "metadataParts": [
                                                                {"text": {"content": "Owner without command"}}
                                                            ]
                                                        },
                                                        {
                                                            "metadataParts": [
                                                                {"text": {"content": "12万回視聴"}},
                                                                {"text": {"content": "3日前"}},
                                                            ]
                                                        },
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
    assert _records_from_watch_next_data(data) == [
        ("newLock_123", "Current layout video", "Owner without command", "")
    ]


def test_lockup_channel_url_from_browse_id() -> None:
    from ytrec_probe.collector import _records_from_initial_data

    data = {
        "lockupViewModel": {
            "contentId": "browseID_123",
            "metadata": {
                "lockupMetadataViewModel": {
                    "title": {"content": "Video"},
                    "metadata": {
                        "contentMetadataViewModel": {
                            "metadataRows": [
                                {
                                    "metadataParts": [
                                        {
                                            "text": {
                                                "content": "Owner",
                                                "commandRuns": [
                                                    {
                                                        "onTap": {
                                                            "innertubeCommand": {
                                                                "browseEndpoint": {
                                                                    "browseId": "UCabcdefghijklmnopqrstuv"
                                                                }
                                                            }
                                                        }
                                                    }
                                                ],
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
    assert _records_from_initial_data(data) == [
        (
            "browseID_123",
            "Video",
            "Owner",
            "https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv",
        )
    ]
