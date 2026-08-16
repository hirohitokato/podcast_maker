from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

from .audio import build_final_audio
from .episode import load_episode, load_settings
from .polly import generate_dialogue_audio

DEFAULT_OUTPUT_DIR = "output"
PROJECT_DIR = Path(__file__).resolve().parents[1]


def load_environment() -> None:
    load_dotenv(dotenv_path=PROJECT_DIR / ".env", override=True)
    required = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate an English-learning dialogue MP3 with Amazon Polly."
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
        "--bgm",
        type=Path,
        default=None,
        help="Background music file. Overrides audio.backgroundMusic in config.toml.",
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
        episode["audio"] = load_settings(PROJECT_DIR / "config.toml")["audio"]
        assets_dir = PROJECT_DIR / "assets"
        configured_bgm = episode["audio"].get("backgroundMusic")
        if args.bgm:
            background_music_path = args.bgm if args.bgm.is_absolute() else Path.cwd() / args.bgm
        elif isinstance(configured_bgm, str):
            configured_path = Path(configured_bgm)
            background_music_path = (
                configured_path
                if configured_path.is_absolute()
                else PROJECT_DIR / configured_path
            )
        else:
            raise ValueError("audio.backgroundMusic must be configured in config.toml")
        rule_paths = [
            *[(rule if rule.is_absolute() else Path.cwd() / rule) for rule in args.pls],
            assets_dir / "aws-terms-ja.pls",
        ]
        rule_paths = list(dict.fromkeys(path.resolve() for path in rule_paths))
        episode_output_dir = args.output / args.input.stem
        print("[1/3] Generating dialogue and guide audio")
        guide_paths = generate_dialogue_audio(
            episode,
            episode_output_dir / ".work",
            shared_work_dir=args.output / ".work",
            rule_paths=rule_paths,
            force=args.force,
        )
        build_final_audio(
            episode,
            episode_output_dir,
            episode_output_dir / (args.final_name or f"{args.input.stem}.mp3"),
            background_music_path=background_music_path,
            jingle_path=assets_dir / "jingle.mp3",
            shared_work_dir=args.output / ".work",
            guide_paths=guide_paths,
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
