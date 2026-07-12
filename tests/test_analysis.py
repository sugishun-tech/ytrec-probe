from ytrec_probe.analysis import analyze


def test_channels_repeated_across_seeds_rank_above_one_offs() -> None:
    raw = {
        "target_channel_url": "https://www.youtube.com/@target",
        "target_channel_name": "Target",
        "seed_videos": [
            {
                "title": "seed 1",
                "url": "https://www.youtube.com/watch?v=a123456",
                "recommendations": [
                    {"rank": 1, "channel_name": "OneOff", "channel_url": "https://www.youtube.com/@one", "video_title": "x"},
                    {"rank": 4, "channel_name": "Repeated", "channel_url": "https://www.youtube.com/@repeated", "video_title": "r1"},
                ],
            },
            {
                "title": "seed 2",
                "url": "https://www.youtube.com/watch?v=b123456",
                "recommendations": [
                    {"rank": 5, "channel_name": "Repeated", "channel_url": "https://www.youtube.com/@repeated", "video_title": "r2"},
                ],
            },
        ],
    }
    scores = analyze(raw)
    assert scores[0].channel_name == "Repeated"
    assert scores[0].seed_appearances == 2
    assert scores[0].seed_coverage == 1.0


def test_target_channel_is_excluded() -> None:
    raw = {
        "target_channel_url": "https://www.youtube.com/@target",
        "target_channel_name": "Target",
        "seed_videos": [
            {
                "title": "seed",
                "url": "u",
                "recommendations": [
                    {"rank": 1, "channel_name": "Target", "channel_url": "https://www.youtube.com/@target", "video_title": "own"},
                    {"rank": 2, "channel_name": "Other", "channel_url": "https://www.youtube.com/@other", "video_title": "other"},
                ],
            }
        ],
    }
    scores = analyze(raw)
    assert [row.channel_name for row in scores] == ["Other"]


def test_failed_seeds_do_not_reduce_coverage() -> None:
    raw = {
        "target_channel_url": "https://www.youtube.com/@target",
        "target_channel_name": "Target",
        "seed_videos": [
            {"title": "failed", "url": "u1", "recommendations": [], "error": "timeout"},
            {
                "title": "ok",
                "url": "u2",
                "recommendations": [
                    {"rank": 3, "channel_name": "Other", "channel_url": "https://www.youtube.com/@other", "video_title": "other"}
                ],
            },
        ],
    }
    scores = analyze(raw)
    assert scores[0].seed_coverage == 1.0
