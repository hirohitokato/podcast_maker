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


def _audio_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("Failed to read audio duration:\n" + result.stderr)
    return float(result.stdout.strip())


def _background_volume_expression(segments: list[tuple[float, float]]) -> str:
    terms: list[str] = []
    start = 0.0
    for index, (duration, volume) in enumerate(segments):
        end = start + duration
        if index == len(segments) - 1:
            fade_start = end - 2
            terms.extend(
                [
                    f"{volume}*between(t\\,{start}\\,{fade_start})",
                    f"{volume}*({end}-t)/2*between(t\\,{fade_start}\\,{end})",
                ]
            )
        else:
            terms.append(f"{volume}*between(t\\,{start}\\,{end})")
        start = end
    return "+".join(terms)


def mix_background_music(
    foreground_path: Path,
    output_path: Path,
    background_path: Path,
    volume_paths: list[tuple[Path, float]],
    *,
    sample_rate: str,
) -> None:
    if not background_path.exists():
        raise FileNotFoundError(f"Audio file not found: {background_path}")

    duration = _audio_duration(foreground_path)
    segments = [(_audio_duration(path), volume) for path, volume in volume_paths]
    segments[-1] = (5.0, segments[-1][1])
    volume = _background_volume_expression(segments)
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(background_path),
            "-i",
            str(foreground_path),
            "-filter_complex",
            (
                f"[0:a]atrim=duration={duration},volume=volume='{volume}':eval=frame[bg];"
                "[1:a][bg]amix=inputs=2:duration=shortest:normalize=0[a]"
            ),
            "-map",
            "[a]",
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
        raise RuntimeError("FFmpeg failed to mix background music:\n" + result.stderr)


def build_final_audio(
    episode: dict[str, Any],
    output_dir: Path,
    final_output_path: Path,
    *,
    assets_dir: Path,
    background_music_path: Path,
) -> None:
    audio_config = episode["audio"]
    output_format = audio_config.get("outputFormat", "mp3")
    sample_rate = audio_config.get("sampleRate", "24000")
    pause_config = audio_config.get("pause", {})
    pauses = {
        "speaker": pause_config.get("betweenSpeakersMs", 350),
        "translation": pause_config.get("betweenTranslationMs", 500),
        "conversation": pause_config.get("beforeConversationMs", 1000),
        "section": pause_config.get("betweenSectionsMs", 1200),
        "opening": 3000,
        "closing": 5000,
    }
    work_dir = output_dir / ".work"
    work_dir.mkdir(parents=True, exist_ok=True)
    silence = {
        name: work_dir / f"silence_{sample_rate}_{duration}ms.mp3"
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
    introduction = assets_dir / "speech_introduction.mp3"
    bilingual_introduction = assets_dir / "speech_both_en_ja.mp3"
    concatenate_mp3_files(english, section1, sample_rate=sample_rate)
    concatenate_mp3_files(bilingual, section2, sample_rate=sample_rate)
    foreground = work_dir / "final_foreground.mp3"
    volume_paths = [
        (silence["opening"], 0.5),
        (introduction, 0.3),
        (silence["conversation"], 0.3),
        (section1, 0.1),
        (silence["section"], 0.2),
        (bilingual_introduction, 0.3),
        (silence["conversation"], 0.3),
        (section2, 0.1),
        (silence["closing"], 0.5),
    ]
    concatenate_mp3_files(
        [path for path, _ in volume_paths],
        foreground,
        sample_rate=sample_rate,
    )
    mix_background_music(
        foreground,
        final_output_path,
        background_music_path,
        volume_paths,
        sample_rate=sample_rate,
    )
    print(
        f"Final audio created\n-------------------\nSection 1 : {section1}\nSection 2 : {section2}\nFinal MP3 : {final_output_path}\n"
    )
