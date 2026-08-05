from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .live import LiveRunConfig, dry_run_preview, replay_live_run, run_live
from .live.openai_transport import OpenAIResponsesTransport


def _load_config(path: Path, model: str) -> LiveRunConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return LiveRunConfig.from_dict(raw, model=model)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run or replay the optional confined live model bridge."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    openai = subparsers.add_parser("openai")
    openai.add_argument("--config", type=Path, required=True)
    openai.add_argument("--output", type=Path, required=True)
    openai.add_argument("--model", required=True)
    openai.add_argument("--confirm-live", action="store_true")
    openai.add_argument("--dry-run", action="store_true")

    replay = subparsers.add_parser("replay")
    replay.add_argument("--input", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "replay":
        print(json.dumps(replay_live_run(args.input), sort_keys=True))
        return 0

    config = _load_config(args.config, args.model)
    if args.dry_run:
        print(json.dumps(dry_run_preview(config), sort_keys=True))
        return 0
    if not args.confirm_live:
        raise SystemExit("Live execution requires --confirm-live.")
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("Live execution requires OPENAI_API_KEY.")
    result = run_live(config, OpenAIResponsesTransport(), args.output)
    print(json.dumps(result.summary_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
