from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

DEFAULT_OUTPUT_DIR = "output"


def load_environment() -> None:
    env_path = Path(__file__).resolve().parent / ".env"

    load_dotenv(
        dotenv_path=env_path,
        override=True,
    )

    required = [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
    ]

    missing = [name for name in required if not os.getenv(name)]

    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
        )


def load_episode(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Input JSON file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if "dialogue" not in data:
        raise ValueError("JSON does not contain 'dialogue'")

    if "audio" not in data:
        raise ValueError("JSON does not contain 'audio'")

    return data


def create_aws_session() -> boto3.Session:
    kwargs: dict[str, str] = {
        "aws_access_key_id": os.environ["AWS_ACCESS_KEY_ID"],
        "aws_secret_access_key": os.environ["AWS_SECRET_ACCESS_KEY"],
        "region_name": os.environ["AWS_REGION"],
    }

    session_token = os.getenv("AWS_SESSION_TOKEN")

    if session_token:
        kwargs["aws_session_token"] = session_token

    return boto3.Session(**kwargs)


def verify_credentials(
    session: boto3.Session,
) -> None:
    sts = session.client("sts")

    identity = sts.get_caller_identity()

    print("AWS credentials verified")
    print(f"  Account: {identity['Account']}")
    print(f"  ARN:     {identity['Arn']}")
    print()


def get_voice_config(
    episode: dict[str, Any],
    speaker: str,
) -> dict[str, str]:
    voices = episode["audio"]["voices"]

    if speaker not in voices:
        raise ValueError(f"No voice configuration found " f"for speaker: {speaker}")

    config = voices[speaker]

    required = [
        "voiceId",
        "engine",
    ]

    missing = [key for key in required if key not in config]

    if missing:
        raise ValueError(
            f"Voice config for '{speaker}' " f"is missing: {', '.join(missing)}"
        )

    return config


def create_cache_key(
    *,
    ssml: str,
    voice_id: str,
    engine: str,
    output_format: str,
    sample_rate: str,
    language_code: str | None,
) -> str:
    """
    Create a hash representing every setting that can
    materially affect the generated audio.

    If any of these values change, the cached MP3 is
    automatically considered stale.
    """

    cache_data = {
        "ssml": ssml,
        "voiceId": voice_id,
        "engine": engine,
        "outputFormat": output_format,
        "sampleRate": sample_rate,
        "languageCode": language_code,
    }

    serialized = json.dumps(
        cache_data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def get_hash_path(
    audio_path: Path,
) -> Path:
    return Path(str(audio_path) + ".sha256")


def is_cache_valid(
    audio_path: Path,
    expected_hash: str,
) -> bool:
    """
    Cache is valid only if:
      1. MP3 exists
      2. MP3 is not empty
      3. Matching hash file exists
      4. Hash matches current generation parameters
    """

    if not audio_path.exists():
        return False

    if audio_path.stat().st_size == 0:
        return False

    hash_path = get_hash_path(audio_path)

    if not hash_path.exists():
        return False

    try:
        actual_hash = hash_path.read_text(encoding="utf-8").strip()
    except OSError:
        return False

    return actual_hash == expected_hash


def save_cache_hash(
    audio_path: Path,
    cache_hash: str,
) -> None:
    hash_path = get_hash_path(audio_path)

    hash_path.write_text(
        cache_hash + "\n",
        encoding="utf-8",
    )


def synthesize_line(
    polly,
    *,
    ssml: str,
    voice_id: str,
    engine: str,
    output_format: str,
    sample_rate: str,
    language_code: str | None,
) -> bytes:
    request: dict[str, Any] = {
        "Engine": engine,
        "VoiceId": voice_id,
        "OutputFormat": output_format,
        "SampleRate": sample_rate,
        "TextType": "ssml",
        "Text": ssml,
    }

    if language_code:
        request["LanguageCode"] = language_code

    response = polly.synthesize_speech(**request)

    audio_stream = response.get("AudioStream")

    if audio_stream is None:
        raise RuntimeError("Amazon Polly response did not " "contain AudioStream")

    try:
        return audio_stream.read()
    finally:
        audio_stream.close()


def generate_audio_files(
    episode: dict[str, Any],
    output_dir: Path,
    *,
    force: bool = False,
) -> None:
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    audio_config = episode["audio"]

    output_format = audio_config.get(
        "outputFormat",
        "mp3",
    )

    sample_rate = audio_config.get(
        "sampleRate",
        "24000",
    )

    dialogue = episode["dialogue"]

    session = create_aws_session()

    verify_credentials(session)

    polly = session.client("polly")

    total = len(dialogue)

    generated = 0
    cached = 0
    failed = 0

    for index, line in enumerate(
        dialogue,
        start=1,
    ):
        line_id = str(line.get("id", index)).zfill(3)

        speaker = line.get("speaker")

        if not speaker:
            raise ValueError(f"Dialogue item {line_id} " f"has no speaker")

        english = line.get("en")

        if not isinstance(english, dict):
            raise ValueError(f"Dialogue item {line_id} " f"has no 'en' object")

        ssml = english.get("ssml")

        if not ssml:
            raise ValueError(f"Dialogue item {line_id} " f"has no en.ssml")

        voice = get_voice_config(
            episode,
            speaker,
        )

        voice_id = voice["voiceId"]
        engine = voice["engine"]

        language_code = voice.get("languageCode")

        filename = f"{line_id}_" f"{speaker}_" f"en_normal." f"{output_format}"

        output_path = output_dir / filename

        cache_hash = create_cache_key(
            ssml=ssml,
            voice_id=voice_id,
            engine=engine,
            output_format=output_format,
            sample_rate=sample_rate,
            language_code=language_code,
        )

        prefix = f"[{index:03}/{total:03}]"

        # -----------------------------
        # Cache check
        # -----------------------------

        if not force and is_cache_valid(
            output_path,
            cache_hash,
        ):
            print(
                f"{prefix} "
                f"CACHED     "
                f"{speaker:<8} "
                f"{voice_id:<12} "
                f"{output_path.name}"
            )

            cached += 1
            continue

        # -----------------------------
        # Generate with Polly
        # -----------------------------

        print(
            f"{prefix} "
            f"GENERATING "
            f"{speaker:<8} "
            f"{voice_id:<12} "
            f"{engine:<10}"
        )

        try:
            audio_bytes = synthesize_line(
                polly,
                ssml=ssml,
                voice_id=voice_id,
                engine=engine,
                output_format=output_format,
                sample_rate=sample_rate,
                language_code=language_code,
            )

            # Write MP3 first.
            output_path.write_bytes(audio_bytes)

            # Only mark cache as valid after
            # successful audio generation.
            save_cache_hash(
                output_path,
                cache_hash,
            )

            generated += 1

            print(f"              " f"-> {output_path}")

        except (
            BotoCoreError,
            ClientError,
            OSError,
        ) as e:
            failed += 1

            print(
                f"              ERROR: {e}",
                file=sys.stderr,
            )

    print()
    print("Generation summary")
    print("------------------")
    print(f"Generated : {generated}")
    print(f"Cached    : {cached}")
    print(f"Failed    : {failed}")
    print(f"Total     : {total}")

    if failed:
        raise RuntimeError(f"{failed} audio file(s) " f"failed to generate")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate individual MP3 files " "from an AWS English Podcast episode."
        )
    )

    parser.add_argument(
        "input",
        type=Path,
        help="Episode JSON file",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path(DEFAULT_OUTPUT_DIR),
        help=("Output directory " f"(default: {DEFAULT_OUTPUT_DIR})"),
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help=("Ignore cache and regenerate " "all audio files"),
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        load_environment()

        episode = load_episode(args.input)

        generate_audio_files(
            episode,
            args.output,
            force=args.force,
        )

    except (
        FileNotFoundError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
        BotoCoreError,
        ClientError,
    ) as e:
        print(
            f"ERROR: {e}",
            file=sys.stderr,
        )

        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
