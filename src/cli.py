from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError

from .audio import build_final_audio
from .episode import load_episode
from .polly import PROJECT_DIR, generate_dialogue_audio, load_environment

DEFAULT_OUTPUT_DIR = "output"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate English/Japanese dialogue audio with Amazon Polly and build a two-section MP3."
    )
    parser.add_argument("input", type=Path, help="Episode JSON file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path(DEFAULT_OUTPUT_DIR),
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--pls",
        action="append",
        type=Path,
        default=[],
        help="Additional Amazon Polly PLS pronunciation lexicon. May be specified multiple times. assets/aws-terms-ja.pls is always loaded automatically.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore audio cache and regenerate all Polly audio files",
    )
    parser.add_argument(
        "--final-name",
        default=None,
        help="Filename for the combined MP3. Default: <episode-json-stem>.mp3",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        load_environment()
        episode = load_episode(args.input)
        rule_paths = [
            *[(rule if rule.is_absolute() else Path.cwd() / rule) for rule in args.pls],
            PROJECT_DIR / "assets" / "aws-terms-ja.pls",
        ]
        rule_paths = list(dict.fromkeys(path.resolve() for path in rule_paths))
        generate_dialogue_audio(
            episode, args.output, rule_paths=rule_paths, force=args.force
        )
        build_final_audio(
            episode,
            args.output,
            args.output / (args.final_name or f"{args.input.stem}.mp3"),
        )
    except (
        FileNotFoundError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
        BotoCoreError,
        ClientError,
    ) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
