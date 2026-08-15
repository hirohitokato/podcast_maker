from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any


def create_silence_file(path: Path, *, duration_ms: int, sample_rate: str) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={sample_rate}:cl=mono",
        "-t",
        str(duration_ms / 1000.0),
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
    input_files: list[Path], output_path: Path, *, sample_rate: str
) -> None:
    if not input_files:
        raise ValueError("No input audio files were specified")
    for path in input_files:
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".txt", delete=False
    ) as f:
        list_file = Path(f.name)
        for input_file in input_files:
            escaped_path = str(input_file.resolve()).replace("'", "'\\''")
            f.write(f"file '{escaped_path}'\n")

    try:
        result = subprocess.run(
            [
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
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "FFmpeg failed to concatenate audio files:\n" + result.stderr
            )
    finally:
        list_file.unlink(missing_ok=True)


def build_final_audio(
    episode: dict[str, Any], output_dir: Path, final_output_path: Path
) -> None:
    audio_config = episode["audio"]
    output_format = audio_config.get("outputFormat", "mp3")
    sample_rate = audio_config.get("sampleRate", "24000")
    pause_config = audio_config.get("pause", {})
    pauses = {
        "speaker": pause_config.get("betweenSpeakersMs", 350),
        "translation": pause_config.get("betweenTranslationMs", 500),
        "section": pause_config.get("betweenSectionsMs", 1200),
    }
    work_dir = output_dir / ".work"
    work_dir.mkdir(parents=True, exist_ok=True)
    silence = {
        name: work_dir / f"silence_{duration}ms.mp3"
        for name, duration in pauses.items()
    }
    for name, path in silence.items():
        if not path.exists():
            create_silence_file(path, duration_ms=pauses[name], sample_rate=sample_rate)

    dialogue = episode["dialogue"]
    english: list[Path] = []
    bilingual: list[Path] = []
    for index, line in enumerate(dialogue, start=1):
        line_id = str(line.get("id", index)).zfill(3)
        en_path = output_dir / f"{line_id}_{line['speaker']}_en_normal.{output_format}"
        ja_path = output_dir / f"{line_id}_ja_normal.{output_format}"
        english.append(en_path)
        bilingual.extend([en_path, silence["translation"], ja_path])
        if index < len(dialogue):
            english.append(silence["speaker"])
            bilingual.append(silence["speaker"])

    section1 = work_dir / "section_01_en_normal.mp3"
    section2 = work_dir / "section_02_en_ja.mp3"
    concatenate_mp3_files(english, section1, sample_rate=sample_rate)
    concatenate_mp3_files(bilingual, section2, sample_rate=sample_rate)
    concatenate_mp3_files(
        [section1, silence["section"], section2],
        final_output_path,
        sample_rate=sample_rate,
    )
    print(
        f"Final audio created\n-------------------\nSection 1 : {section1}\nSection 2 : {section2}\nFinal MP3 : {final_output_path}\n"
    )
