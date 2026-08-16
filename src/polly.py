from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from html import escape
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .episode import apply_guide_rate, apply_japanese_rate, get_voice_config

MAX_LEXICONS_PER_LANGUAGE = 5


def create_aws_session() -> boto3.Session:
    kwargs: dict[str, str] = {
        "aws_access_key_id": os.environ["AWS_ACCESS_KEY_ID"],
        "aws_secret_access_key": os.environ["AWS_SECRET_ACCESS_KEY"],
        "region_name": os.environ["AWS_REGION"],
    }
    if session_token := os.getenv("AWS_SESSION_TOKEN"):
        kwargs["aws_session_token"] = session_token
    return boto3.Session(**kwargs)


def verify_credentials(session: boto3.Session) -> None:
    identity = session.client("sts").get_caller_identity()
    print("AWS credentials verified")
    print(f"  Account: {identity['Account']}")
    print(f"  ARN:     {identity['Arn']}")
    print()


def create_cache_key(
    *,
    ssml: str,
    voice_id: str,
    engine: str,
    output_format: str,
    sample_rate: str,
    language_code: str | None,
    lexicon_cache_tokens: list[str],
) -> str:
    cache_data = {
        "ssml": ssml,
        "voiceId": voice_id,
        "engine": engine,
        "outputFormat": output_format,
        "sampleRate": sample_rate,
        "languageCode": language_code,
        "lexiconNames": sorted(lexicon_cache_tokens),
    }
    serialized = json.dumps(
        cache_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _hash_path(audio_path: Path) -> Path:
    return Path(str(audio_path) + ".sha256")


def _cache_is_valid(audio_path: Path, expected_hash: str) -> bool:
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        return False

    try:
        actual_hash = _hash_path(audio_path).read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return actual_hash == expected_hash


def _save_cache_hash(audio_path: Path, cache_hash: str) -> None:
    _hash_path(audio_path).write_text(cache_hash + "\n", encoding="utf-8")


def _lexicon_name_from_path(path: Path) -> str:
    stem = re.sub(r"[^0-9A-Za-z]", "", path.stem) or "lexicon"
    digest = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:6]
    return f"{stem[:14]}{digest}"[:20]


def _lexicon_language(content: str) -> str:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise ValueError(f"Invalid PLS/XML content: {e}") from e

    if root.tag.rsplit("}", 1)[-1] != "lexicon":
        raise ValueError("Invalid PLS/XML content: root element must be <lexicon>")
    language_code = root.attrib.get("{http://www.w3.org/XML/1998/namespace}lang")
    if not language_code:
        raise ValueError("Invalid PLS/XML content: <lexicon> must have xml:lang")
    return language_code


def register_lexicons(polly, rule_paths: list[Path]) -> list[dict[str, str]]:
    prepared: list[dict[str, str]] = []
    for rule_path in rule_paths:
        if not rule_path.exists():
            raise FileNotFoundError(f"PLS rule file not found: {rule_path}")
        if not rule_path.is_file():
            raise ValueError(f"PLS rule path is not a file: {rule_path}")

        content = rule_path.read_text(encoding="utf-8")
        name = _lexicon_name_from_path(rule_path)
        prepared.append(
            {
                "path": str(rule_path),
                "name": name,
                "languageCode": _lexicon_language(content),
                "cacheToken": f"{name}:{hashlib.sha256(content.encode('utf-8')).hexdigest()}",
                "content": content,
            }
        )

    for language_code in {item["languageCode"] for item in prepared}:
        count = sum(item["languageCode"] == language_code for item in prepared)
        if count > MAX_LEXICONS_PER_LANGUAGE:
            raise ValueError(
                f"At most {MAX_LEXICONS_PER_LANGUAGE} PLS lexicons can be "
                f"applied for language {language_code} (got {count})"
            )

    registered: list[dict[str, str]] = []
    for lexicon in prepared:
        print(
            f"Registering Polly lexicon: {lexicon['path']} -> "
            f"{lexicon['name']} ({lexicon['languageCode']})"
        )
        polly.put_lexicon(Name=lexicon["name"], Content=lexicon["content"])
        registered.append(
            {key: lexicon[key] for key in ("name", "languageCode", "cacheToken")}
        )

    if registered:
        print()
    return registered


def _applicable_lexicons(
    lexicons: list[dict[str, str]], language_code: str | None
) -> list[dict[str, str]]:
    if not language_code:
        return []
    return [item for item in lexicons if item["languageCode"] == language_code]


def _lexicon_names(
    lexicons: list[dict[str, str]], language_code: str | None
) -> list[str]:
    return [item["name"] for item in _applicable_lexicons(lexicons, language_code)]


def _lexicon_cache_tokens(
    lexicons: list[dict[str, str]], language_code: str | None
) -> list[str]:
    return [
        item["cacheToken"] for item in _applicable_lexicons(lexicons, language_code)
    ]


def _synthesize_line(
    polly,
    *,
    ssml: str,
    voice_id: str,
    engine: str,
    output_format: str,
    sample_rate: str,
    language_code: str | None,
    lexicon_names: list[str],
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
    if lexicon_names:
        request["LexiconNames"] = lexicon_names

    audio_stream = polly.synthesize_speech(**request).get("AudioStream")
    if audio_stream is None:
        raise RuntimeError("Amazon Polly response did not contain AudioStream")
    try:
        return audio_stream.read()
    finally:
        audio_stream.close()


def _ensure_audio_file(
    polly,
    *,
    output_path: Path,
    ssml: str,
    voice: dict[str, str],
    output_format: str,
    sample_rate: str,
    lexicons: list[dict[str, str]],
    force: bool,
) -> bool:
    language_code = voice.get("languageCode")
    cache_hash = create_cache_key(
        ssml=ssml,
        voice_id=voice["voiceId"],
        engine=voice["engine"],
        output_format=output_format,
        sample_rate=sample_rate,
        language_code=language_code,
        lexicon_cache_tokens=_lexicon_cache_tokens(lexicons, language_code),
    )
    if not force and _cache_is_valid(output_path, cache_hash):
        return False

    output_path.write_bytes(
        _synthesize_line(
            polly,
            ssml=ssml,
            voice_id=voice["voiceId"],
            engine=voice["engine"],
            output_format=output_format,
            sample_rate=sample_rate,
            language_code=language_code,
            lexicon_names=_lexicon_names(lexicons, language_code),
        )
    )
    _save_cache_hash(output_path, cache_hash)
    return True


def _guide_text(episode: dict[str, Any], key: str, template: str) -> str:
    if key != "0-introduction":
        return template
    if template.count("%s") != 1:
        raise ValueError("audio.guides.0-introduction must contain exactly one %s")
    services = episode.get("aws_services")
    if (
        not isinstance(services, list)
        or not services
        or not all(isinstance(service, str) and service for service in services)
    ):
        raise ValueError("Episode aws_services must be a non-empty list of strings")
    return template.replace("%s", ", ".join(services))


def generate_dialogue_audio(
    episode: dict[str, Any],
    output_dir: Path,
    *,
    shared_work_dir: Path,
    rule_paths: list[Path],
    force: bool = False,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    shared_work_dir.mkdir(parents=True, exist_ok=True)
    audio_config = episode["audio"]
    output_format = audio_config.get("outputFormat", "mp3")
    sample_rate = audio_config.get("sampleRate", "24000")
    dialogue = episode["dialogue"]
    guides = audio_config.get("guides")
    if not isinstance(guides, dict) or not all(
        isinstance(key, str) and isinstance(template, str)
        for key, template in guides.items()
    ):
        raise ValueError("audio.guides must be an object of guide text strings")
    if "0-introduction" not in guides:
        raise ValueError("audio.guides must contain 0-introduction")
    guide_paths = {
        key: (output_dir if key == "0-introduction" else shared_work_dir)
        / f"guide_{key}.{output_format}"
        for key in guides
    }

    session = create_aws_session()
    verify_credentials(session)
    polly = session.client("polly")
    lexicons = register_lexicons(polly, rule_paths)
    guide_voice = get_voice_config(episode, "guide")
    total_assets = len(dialogue) * 2 + len(guides)
    generated = cached = failed = 0

    for index, line in enumerate(dialogue, start=1):
        line_id = str(line.get("id", index)).zfill(3)
        speaker = line.get("speaker")
        if not speaker:
            raise ValueError(f"Dialogue item {line_id} has no speaker")

        english = line.get("en")
        if not isinstance(english, dict):
            raise ValueError(f"Dialogue item {line_id} has no 'en' object")
        japanese = line.get("ja")
        if not isinstance(japanese, dict):
            raise ValueError(f"Dialogue item {line_id} has no 'ja' object")

        for language, voice, ssml in (
            ("EN", get_voice_config(episode, speaker), english.get("ssml")),
            ("JA", get_voice_config(episode, f"{speaker}-ja"), japanese.get("ssml")),
        ):
            if not ssml:
                raise ValueError(
                    f"Dialogue item {line_id} has no {language.lower()}.ssml"
                )
            if language == "JA":
                ssml = apply_japanese_rate(ssml, audio_config)
                filename = f"{line_id}_ja_normal.{output_format}"
                label = "ja"
            else:
                filename = f"{line_id}_{speaker}_en_normal.{output_format}"
                label = speaker

            output_path = output_dir / filename
            try:
                was_generated = _ensure_audio_file(
                    polly,
                    output_path=output_path,
                    ssml=ssml,
                    voice=voice,
                    output_format=output_format,
                    sample_rate=sample_rate,
                    lexicons=lexicons,
                    force=force,
                )
                state = "GENERATED" if was_generated else "CACHED"
                asset_index = generated + cached + failed + 1
                print(
                    f"[{asset_index:03}/{total_assets:03}] "
                    f"{state:<9} {language} {label:<8} {output_path.name}"
                )
                generated += int(was_generated)
                cached += int(not was_generated)
            except (BotoCoreError, ClientError, OSError) as e:
                failed += 1
                print(f"ERROR generating {language} {line_id}: {e}", file=sys.stderr)

    for key, template in guides.items():
        ssml = apply_guide_rate(
            f"<speak>{escape(_guide_text(episode, key, template))}</speak>",
            audio_config,
        )
        try:
            was_generated = _ensure_audio_file(
                polly,
                output_path=guide_paths[key],
                ssml=ssml,
                voice=guide_voice,
                output_format=output_format,
                sample_rate=sample_rate,
                lexicons=lexicons,
                force=force,
            )
            state = "GENERATED" if was_generated else "CACHED"
            asset_index = generated + cached + failed + 1
            print(
                f"[{asset_index:03}/{total_assets:03}] "
                f"{state:<9} GUIDE    {guide_paths[key].name}"
            )
            generated += int(was_generated)
            cached += int(not was_generated)
        except (BotoCoreError, ClientError, OSError) as e:
            failed += 1
            print(f"ERROR generating guide {key}: {e}", file=sys.stderr)

    print(f"\nAudio generation summary\n------------------------")
    print(
        f"Generated : {generated}\nCached    : {cached}\nFailed    : {failed}\nTotal     : {total_assets}\n"
    )
    if failed:
        raise RuntimeError(f"{failed} audio file(s) failed to generate")
    return guide_paths
