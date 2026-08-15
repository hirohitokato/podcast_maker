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
    if "audio" not in data:
        raise ValueError("JSON does not contain 'audio'")

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
