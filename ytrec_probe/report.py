from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any

from .analysis import ChannelScore


def save_raw(path: Path, raw: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")


def load_raw(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_csv(path: Path, scores: list[ChannelScore]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [score.to_dict() for score in scores]
    fieldnames = list(rows[0].keys()) if rows else [
        "rank",
        "channel_name",
        "channel_url",
        "score",
        "seed_coverage_pct",
        "seed_appearances",
        "total_occurrences",
        "average_rank",
        "best_rank",
        "discounted_rank_score",
        "sample_videos",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def save_html(path: Path, raw: dict[str, Any], scores: list[ChannelScore]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    successful = sum(1 for seed in raw.get("seed_videos", []) if not seed.get("error"))
    failed = sum(1 for seed in raw.get("seed_videos", []) if seed.get("error"))

    rows_html = []
    for score in scores:
        channel = html.escape(score.channel_name)
        if score.channel_url:
            channel = f'<a href="{html.escape(score.channel_url, quote=True)}">{channel}</a>'
        samples = "<br>".join(html.escape(value) for value in score.sample_videos)
        rows_html.append(
            "<tr>"
            f"<td>{score.rank}</td>"
            f"<td>{channel}</td>"
            f"<td>{score.score:.2f}</td>"
            f"<td>{score.seed_coverage * 100:.1f}%</td>"
            f"<td>{score.seed_appearances}</td>"
            f"<td>{score.total_occurrences}</td>"
            f"<td>{score.average_rank:.2f}</td>"
            f"<td>{score.best_rank}</td>"
            f"<td>{samples}</td>"
            "</tr>"
        )

    target_name = html.escape(raw.get("target_channel_name") or "(unknown)")
    target_url = html.escape(raw.get("target_channel_url") or "", quote=True)
    page = f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>YouTube Recommendation Probe</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 1400px; margin: 2rem auto; padding: 0 1rem; color: #1f2328; }}
h1 {{ margin-bottom: .25rem; }}
.meta {{ color: #59636e; margin-bottom: 1.5rem; }}
.notice {{ background: #fff8c5; border: 1px solid #d4a72c; padding: .9rem; border-radius: 8px; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 1.25rem; font-size: .92rem; }}
th, td {{ border-bottom: 1px solid #d8dee4; padding: .65rem; text-align: left; vertical-align: top; }}
th {{ position: sticky; top: 0; background: white; }}
.number {{ font-variant-numeric: tabular-nums; }}
</style>
</head>
<body>
<h1>YouTube Recommendation Probe</h1>
<div class="meta">
対象: <a href="{target_url}">{target_name}</a><br>
取得日時: {html.escape(raw.get("collected_at", ""))}<br>
プロファイル: {html.escape(raw.get("mode", ""))} / 成功シード {successful} / 失敗 {failed}
</div>
<div class="notice">
これは、取得時点・このブラウザプロファイル・地域・端末条件で実際に表示された「次の動画」欄の観測値です。
YouTube内部の推薦確率や、全視聴者への推薦を直接測った値ではありません。
</div>
<table>
<thead><tr>
<th>#</th><th>チャンネル</th><th>スコア</th><th>シード出現率</th><th>出現シード数</th>
<th>総出現数</th><th>平均順位</th><th>最高順位</th><th>表示例</th>
</tr></thead>
<tbody>{''.join(rows_html)}</tbody>
</table>
</body>
</html>"""
    path.write_text(page, encoding="utf-8")
