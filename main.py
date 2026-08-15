from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

DEFAULT_OUTPUT_DIR = "output"


def load_environment() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(dotenv_path=env_path, override=True)

    required = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION"]
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


def verify_credentials(session: boto3.Session) -> None:
    sts = session.client("sts")
    identity = sts.get_caller_identity()
    print("AWS credentials verified")
    print(f"  Account: {identity['Account']}")
    print(f"  ARN:     {identity['Arn']}")
    print()


def get_voice_config(episode: dict[str, Any], voice_key: str) -> dict[str, str]:
    voices = episode["audio"]["voices"]
    if voice_key not in voices:
        raise ValueError(f"No voice configuration found for: {voice_key}")

    config = voices[voice_key]
    required = ["voiceId", "engine"]
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(
            f"Voice config for '{voice_key}' is missing: {', '.join(missing)}"
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


def get_hash_path(audio_path: Path) -> Path:
    return Path(str(audio_path) + ".sha256")


def is_cache_valid(audio_path: Path, expected_hash: str) -> bool:
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        return False

    hash_path = get_hash_path(audio_path)
    if not hash_path.exists():
        return False

    try:
        actual_hash = hash_path.read_text(encoding="utf-8").strip()
    except OSError:
        return False

    return actual_hash == expected_hash


def save_cache_hash(audio_path: Path, cache_hash: str) -> None:
    get_hash_path(audio_path).write_text(cache_hash + "\n", encoding="utf-8")


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
        raise RuntimeError("Amazon Polly response did not contain AudioStream")

    try:
        return audio_stream.read()
    finally:
        audio_stream.close()


def ensure_audio_file(
    polly,
    *,
    output_path: Path,
    ssml: str,
    voice_id: str,
    engine: str,
    output_format: str,
    sample_rate: str,
    language_code: str | None,
    force: bool,
) -> bool:
    cache_hash = create_cache_key(
        ssml=ssml,
        voice_id=voice_id,
        engine=engine,
        output_format=output_format,
        sample_rate=sample_rate,
        language_code=language_code,
    )

    if not force and is_cache_valid(output_path, cache_hash):
        return False

    audio_bytes = synthesize_line(
        polly,
        ssml=ssml,
        voice_id=voice_id,
        engine=engine,
        output_format=output_format,
        sample_rate=sample_rate,
        language_code=language_code,
    )
    output_path.write_bytes(audio_bytes)
    save_cache_hash(output_path, cache_hash)
    return True


def generate_dialogue_audio(
    episode: dict[str, Any],
    output_dir: Path,
    *,
    force: bool = False,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    audio_config = episode["audio"]
    output_format = audio_config.get("outputFormat", "mp3")
    sample_rate = audio_config.get("sampleRate", "24000")
    dialogue = episode["dialogue"]

    session = create_aws_session()
    verify_credentials(session)
    polly = session.client("polly")

    japanese_voice = get_voice_config(episode, "ja")
    total_assets = len(dialogue) * 2
    asset_index = 0
    generated = 0
    cached = 0
    failed = 0

    for index, line in enumerate(dialogue, start=1):
        line_id = str(line.get("id", index)).zfill(3)
        speaker = line.get("speaker")
        if not speaker:
            raise ValueError(f"Dialogue item {line_id} has no speaker")

        english = line.get("en")
        if not isinstance(english, dict):
            raise ValueError(f"Dialogue item {line_id} has no 'en' object")
        en_ssml = english.get("ssml")
        if not en_ssml:
            raise ValueError(f"Dialogue item {line_id} has no en.ssml")

        english_voice = get_voice_config(episode, speaker)
        en_output_path = output_dir / (f"{line_id}_{speaker}_en_normal.{output_format}")
        asset_index += 1

        try:
            was_generated = ensure_audio_file(
                polly,
                output_path=en_output_path,
                ssml=en_ssml,
                voice_id=english_voice["voiceId"],
                engine=english_voice["engine"],
                output_format=output_format,
                sample_rate=sample_rate,
                language_code=english_voice.get("languageCode"),
                force=force,
            )
            state = "GENERATED" if was_generated else "CACHED"
            print(
                f"[{asset_index:03}/{total_assets:03}] "
                f"{state:<9} EN {speaker:<8} {en_output_path.name}"
            )
            generated += int(was_generated)
            cached += int(not was_generated)
        except (BotoCoreError, ClientError, OSError) as e:
            failed += 1
            print(f"ERROR generating EN {line_id}: {e}", file=sys.stderr)

        japanese = line.get("ja")
        if not isinstance(japanese, dict):
            raise ValueError(f"Dialogue item {line_id} has no 'ja' object")
        ja_ssml = japanese.get("ssml")
        if not ja_ssml:
            raise ValueError(f"Dialogue item {line_id} has no ja.ssml")

        ja_output_path = output_dir / f"{line_id}_ja_normal.{output_format}"
        asset_index += 1

        try:
            was_generated = ensure_audio_file(
                polly,
                output_path=ja_output_path,
                ssml=ja_ssml,
                voice_id=japanese_voice["voiceId"],
                engine=japanese_voice["engine"],
                output_format=output_format,
                sample_rate=sample_rate,
                language_code=japanese_voice.get("languageCode"),
                force=force,
            )
            state = "GENERATED" if was_generated else "CACHED"
            print(
                f"[{asset_index:03}/{total_assets:03}] "
                f"{state:<9} JA {'ja':<8} {ja_output_path.name}"
            )
            generated += int(was_generated)
            cached += int(not was_generated)
        except (BotoCoreError, ClientError, OSError) as e:
            failed += 1
            print(f"ERROR generating JA {line_id}: {e}", file=sys.stderr)

    print()
    print("Audio generation summary")
    print("------------------------")
    print(f"Generated : {generated}")
    print(f"Cached    : {cached}")
    print(f"Failed    : {failed}")
    print(f"Total     : {total_assets}")
    print()

    if failed:
        raise RuntimeError(f"{failed} audio file(s) failed to generate")


def create_silence_file(
    path: Path,
    *,
    duration_ms: int,
    sample_rate: str,
) -> None:
    duration_seconds = duration_ms / 1000.0
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={sample_rate}:cl=mono",
        "-t",
        str(duration_seconds),
        "-codec:a",
        "libmp3lame",
        "-ar",
        sample_rate,
        "-ac",
        "1",
        str(path),
    ]

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("Failed to generate silence:\n" + result.stderr)


def concatenate_mp3_files(
    input_files: list[Path],
    output_path: Path,
    *,
    sample_rate: str,
) -> None:
    if not input_files:
        raise ValueError("No input audio files were specified")

    for path in input_files:
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".txt",
        delete=False,
    ) as f:
        list_file = Path(f.name)
        for input_file in input_files:
            escaped_path = str(input_file.resolve()).replace("'", "'\\''")
            f.write(f"file '{escaped_path}'\n")

    try:
        command = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-codec:a",
            "libmp3lame",
            "-ar",
            sample_rate,
            "-ac",
            "1",
            str(output_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                "FFmpeg failed to concatenate audio files:\n" + result.stderr
            )
    finally:
        list_file.unlink(missing_ok=True)


def build_final_audio(
    episode: dict[str, Any],
    output_dir: Path,
    final_output_path: Path,
) -> None:
    audio_config = episode["audio"]
    output_format = audio_config.get("outputFormat", "mp3")
    sample_rate = audio_config.get("sampleRate", "24000")

    pause_config = audio_config.get("pause", {})
    between_speakers_ms = pause_config.get("betweenSpeakersMs", 350)
    between_translation_ms = pause_config.get("betweenTranslationMs", 500)
    between_sections_ms = pause_config.get("betweenSectionsMs", 1200)

    dialogue = episode["dialogue"]
    work_dir = output_dir / ".work"
    work_dir.mkdir(parents=True, exist_ok=True)

    speaker_pause = work_dir / f"silence_{between_speakers_ms}ms.mp3"
    translation_pause = work_dir / f"silence_{between_translation_ms}ms.mp3"
    section_pause = work_dir / f"silence_{between_sections_ms}ms.mp3"

    if not speaker_pause.exists():
        create_silence_file(
            speaker_pause,
            duration_ms=between_speakers_ms,
            sample_rate=sample_rate,
        )
    if not translation_pause.exists():
        create_silence_file(
            translation_pause,
            duration_ms=between_translation_ms,
            sample_rate=sample_rate,
        )
    if not section_pause.exists():
        create_silence_file(
            section_pause,
            duration_ms=between_sections_ms,
            sample_rate=sample_rate,
        )

    # Section 1: English normal speed only.
    section1_segments: list[Path] = []
    for index, line in enumerate(dialogue, start=1):
        line_id = str(line.get("id", index)).zfill(3)
        speaker = line["speaker"]
        en_path = output_dir / f"{line_id}_{speaker}_en_normal.{output_format}"
        section1_segments.append(en_path)
        if index < len(dialogue):
            section1_segments.append(speaker_pause)

    section1_path = work_dir / "section_01_en_normal.mp3"
    concatenate_mp3_files(
        section1_segments,
        section1_path,
        sample_rate=sample_rate,
    )

    # Section 2: English normal -> Japanese translation -> next English -> ...
    section2_segments: list[Path] = []
    for index, line in enumerate(dialogue, start=1):
        line_id = str(line.get("id", index)).zfill(3)
        speaker = line["speaker"]
        en_path = output_dir / f"{line_id}_{speaker}_en_normal.{output_format}"
        ja_path = output_dir / f"{line_id}_ja_normal.{output_format}"

        section2_segments.append(en_path)
        section2_segments.append(translation_pause)
        section2_segments.append(ja_path)

        if index < len(dialogue):
            section2_segments.append(speaker_pause)

    section2_path = work_dir / "section_02_en_ja.mp3"
    concatenate_mp3_files(
        section2_segments,
        section2_path,
        sample_rate=sample_rate,
    )

    # Final = Section 1 -> long pause -> Section 2.
    concatenate_mp3_files(
        [section1_path, section_pause, section2_path],
        final_output_path,
        sample_rate=sample_rate,
    )

    print("Final audio created")
    print("-------------------")
    print(f"Section 1 : {section1_path}")
    print(f"Section 2 : {section2_path}")
    print(f"Final MP3 : {final_output_path}")
    print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate English/Japanese dialogue audio with Amazon Polly "
            "and build a two-section MP3."
        )
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

        generate_dialogue_audio(
            episode,
            args.output,
            force=args.force,
        )

        final_name = args.final_name or f"{args.input.stem}.mp3"
        final_output_path = args.output / final_name

        build_final_audio(
            episode,
            args.output,
            final_output_path,
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
