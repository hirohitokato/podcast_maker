from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any


ALLOWED_SPEAKERS = {"man", "woman"}


def load_episode(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Input JSON file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if "dialogue" not in data:
        raise ValueError("JSON does not contain 'dialogue'")
    dialogue = data["dialogue"]
    if not isinstance(dialogue, list):
        raise ValueError("JSON dialogue must be an array")
    for index, line in enumerate(dialogue, start=1):
        if not isinstance(line, dict) or line.get("speaker") not in ALLOWED_SPEAKERS:
            raise ValueError(
                f"Dialogue item {index} speaker must be one of: man, woman"
            )

    return data


def load_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Settings file not found: {path}")

    with path.open("rb") as f:
        data = tomllib.load(f)
    if not isinstance(data.get("audio"), dict):
        raise ValueError("Settings TOML must contain an 'audio' table")
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


def _apply_rate(
    ssml: str, audio_config: dict[str, Any], profile: str, default_rate: str | None
) -> str:
    profiles = audio_config.get("profiles", {})
    rate = profiles.get(profile, {}).get("rate", default_rate)

    if not isinstance(rate, str) or not re.fullmatch(r"[0-9]+%", rate):
        raise ValueError(f"audio.profiles.{profile}.rate must be a percentage")
    if "<speak>" not in ssml or "</speak>" not in ssml:
        raise ValueError("SSML must contain a <speak> root element")

    return ssml.replace("<speak>", f'<speak><prosody rate="{rate}">', 1).replace(
        "</speak>", "</prosody></speak>", 1
    )


def apply_japanese_rate(ssml: str, audio_config: dict[str, Any]) -> str:
    return _apply_rate(ssml, audio_config, "ja", "110%")


def apply_guide_rate(ssml: str, audio_config: dict[str, Any]) -> str:
    return _apply_rate(ssml, audio_config, "guide", None)
