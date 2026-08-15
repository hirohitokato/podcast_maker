from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def load_episode(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Input JSON file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if "dialogue" not in data:
        raise ValueError("JSON does not contain 'dialogue'")

    return data


def _strip_jsonc_comments(content: str) -> str:
    result: list[str] = []
    in_string = escaped = False
    index = 0
    while index < len(content):
        char = content[index]
        next_char = content[index + 1] if index + 1 < len(content) else ""
        if in_string:
            result.append(char)
            if char == '"' and not escaped:
                in_string = False
            escaped = char == "\\" and not escaped
        elif char == '"':
            in_string = True
            result.append(char)
        elif char == "/" and next_char == "/":
            index = content.find("\n", index)
            if index == -1:
                break
            result.append("\n")
        elif char == "/" and next_char == "*":
            index = content.find("*/", index + 2)
            if index == -1:
                raise ValueError("Unterminated comment in settings file")
            index += 1
        else:
            result.append(char)
        index += 1
    return "".join(result)


def _strip_jsonc_trailing_commas(content: str) -> str:
    result: list[str] = []
    in_string = escaped = False
    for index, char in enumerate(content):
        if in_string:
            result.append(char)
            if char == '"' and not escaped:
                in_string = False
            escaped = char == "\\" and not escaped
            continue
        if char == '"':
            in_string = True
            result.append(char)
        elif char == "," and content[index + 1 :].lstrip().startswith(("}", "]")):
            continue
        else:
            result.append(char)
    return "".join(result)


def load_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Settings file not found: {path}")

    content = _strip_jsonc_comments(path.read_text(encoding="utf-8"))
    data = json.loads(_strip_jsonc_trailing_commas(content))
    if not isinstance(data.get("audio"), dict):
        raise ValueError("Settings JSONC must contain an 'audio' object")
    return data


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


def apply_japanese_rate(ssml: str, audio_config: dict[str, Any]) -> str:
    profiles = audio_config.get("profiles", {})
    rate = profiles.get("ja", {}).get("rate", "110%")

    if not isinstance(rate, str) or not re.fullmatch(r"[0-9]+%", rate):
        raise ValueError("audio.profiles.ja.rate must be a percentage")
    if "<speak>" not in ssml or "</speak>" not in ssml:
        raise ValueError("Japanese SSML must contain a <speak> root element")

    return ssml.replace("<speak>", f'<speak><prosody rate="{rate}">', 1).replace(
        "</speak>", "</prosody></speak>", 1
    )
