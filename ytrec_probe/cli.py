from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .analysis import analyze
from .collector import DEFAULT_USER_AGENT, collect
from .report import load_raw, save_csv, save_html, save_raw


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ytrec-probe",
        description="Read YouTube's watch-next recommendations without a browser or official Data API key.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser("collect", help="collect recommendations and build reports")
    collect_parser.add_argument("channel_url", help="YouTube channel URL, e.g. https://www.youtube.com/@handle")
    collect_parser.add_argument("--seeds", type=int, default=12, help="number of channel videos to probe (default: 12)")
    collect_parser.add_argument("--recommendations", type=int, default=20, help="right-side recommendations per seed (default: 20)")
    collect_parser.add_argument("--locale", default="ja-JP", help="request locale (default: ja-JP)")
    collect_parser.add_argument("--delay", type=float, default=1.0, help="seconds between watch-page requests (default: 1.0)")
    collect_parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds (default: 30)")
    collect_parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="HTTP User-Agent")
    collect_parser.add_argument("--output-dir", type=Path, default=Path("output"), help="output directory")
    collect_parser.add_argument("--debug-dir", type=Path, default=Path(".ytrec-debug"), help="failure response directory")
    # Backward-compatible no-op flags from the Playwright versions.
    collect_parser.add_argument("--headless", action="store_true", help=argparse.SUPPRESS)
    collect_parser.add_argument("--show-browser", action="store_true", help=argparse.SUPPRESS)
    collect_parser.add_argument("--fresh-profile", action="store_true", help=argparse.SUPPRESS)
    collect_parser.add_argument("--profile-dir", type=Path, help=argparse.SUPPRESS)
    collect_parser.add_argument("--slow-mo", type=int, default=0, help=argparse.SUPPRESS)

    analyze_parser = subparsers.add_parser("analyze", help="rebuild CSV/HTML from an existing raw JSON")
    analyze_parser.add_argument("raw_json", type=Path)
    analyze_parser.add_argument("--output-dir", type=Path, default=Path("output"))

    return parser


def _write_reports(raw: dict, output_dir: Path) -> None:
    scores = analyze(raw)
    output_dir.mkdir(parents=True, exist_ok=True)
    save_raw(output_dir / "raw.json", raw)
    save_csv(output_dir / "channels.csv", scores)
    save_html(output_dir / "report.html", raw, scores)
    print(f"raw:    {output_dir / 'raw.json'}")
    print(f"csv:    {output_dir / 'channels.csv'}")
    print(f"report: {output_dir / 'report.html'}")
    if not scores:
        print("warning: no candidate channels were scored", file=sys.stderr)


def main() -> None:
    args = build_parser().parse_args()
    try:
        if args.command == "collect":
            result = asyncio.run(
                collect(
                    channel_url=args.channel_url,
                    seed_limit=args.seeds,
                    recommendation_limit=args.recommendations,
                    locale=args.locale,
                    delay_seconds=args.delay,
                    timeout_seconds=args.timeout,
                    user_agent=args.user_agent,
                    debug_dir=args.debug_dir,
                )
            )
            _write_reports(result.to_dict(), args.output_dir)
        elif args.command == "analyze":
            _write_reports(load_raw(args.raw_json), args.output_dir)
        else:
            raise AssertionError(f"unknown command: {args.command}")
    except KeyboardInterrupt:
        print("cancelled", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
