from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


CACHE_VERSION = 1


def _hash_path(audio_path: Path) -> Path:
    return Path(str(audio_path) + ".sha256")


def _cache_key(data: dict[str, Any]) -> str:
    serialized = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cache_is_valid(audio_path: Path, expected_key: str) -> bool:
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        return False
    try:
        return _hash_path(audio_path).read_text(encoding="utf-8").strip() == expected_key
    except OSError:
        return False


def _save_cache_key(audio_path: Path, cache_key: str) -> None:
    _hash_path(audio_path).write_text(cache_key + "\n", encoding="utf-8")


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


def create_shadowing_section(
    input_files: list[Path], output_path: Path, *, sample_rate: str
) -> None:
    if not input_files:
        raise ValueError("No input audio files were specified")
    for path in input_files:
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {path}")

    pairs: list[str] = []
    for index in range(len(input_files)):
        pairs.extend(
            [
                f"[{index}:a]asplit=2[voice{index}][pause{index}]",
                f"[pause{index}]volume=0[silent{index}]",
                f"[voice{index}][silent{index}]concat=n=2:v=0:a=1[pair{index}]",
            ]
        )
    pairs.append(
        "".join(f"[pair{index}]" for index in range(len(input_files)))
        + f"concat=n={len(input_files)}:v=0:a=1[shadowing]"
    )
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            *[argument for path in input_files for argument in ("-i", str(path))],
            "-filter_complex",
            ";".join(pairs),
            "-map",
            "[shadowing]",
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
        raise RuntimeError("FFmpeg failed to create shadowing section:\n" + result.stderr)


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
            initial_volume = segments[index - 1][1]
            fade_in_end = start + 1
            fade_start = end - 2
            terms.extend(
                [
                    f"({initial_volume}+({volume}-{initial_volume})*(t-{start}))*between(t\\,{start}\\,{fade_in_end})",
                    f"{volume}*between(t\\,{fade_in_end}\\,{fade_start})",
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
    background_music_path: Path,
    jingle_path: Path,
    shared_work_dir: Path,
    guide_paths: dict[str, Path],
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
    episode_work_dir = output_dir / ".work"
    episode_work_dir.mkdir(parents=True, exist_ok=True)
    shared_work_dir.mkdir(parents=True, exist_ok=True)
    silence = {
        name: shared_work_dir / f"silence_{sample_rate}_{duration}ms.mp3"
        for name, duration in pauses.items()
    }
    for name, path in silence.items():
        cache_key = _cache_key(
            {
                "version": CACHE_VERSION,
                "kind": "silence",
                "sampleRate": sample_rate,
                "durationMs": pauses[name],
            }
        )
        if not _cache_is_valid(path, cache_key):
            create_silence_file(path, duration_ms=pauses[name], sample_rate=sample_rate)
            _save_cache_key(path, cache_key)

    dialogue = episode["dialogue"]
    english: list[Path] = []
    bilingual: list[Path] = []
    slow: list[Path] = []
    slow_lines: list[Path] = []
    for index, line in enumerate(dialogue, start=1):
        line_id = str(line.get("id", index)).zfill(3)
        en_path = episode_work_dir / f"{line_id}_{line['speaker']}_en_normal.{output_format}"
        ja_path = episode_work_dir / f"{line_id}_ja_normal.{output_format}"
        slow_path = episode_work_dir / f"{line_id}_{line['speaker']}_en_slow.{output_format}"
        english.append(en_path)
        bilingual.extend([en_path, silence["translation"], ja_path])
        slow.append(slow_path)
        slow_lines.append(slow_path)
        if index < len(dialogue):
            english.append(silence["speaker"])
            bilingual.append(silence["speaker"])
            slow.append(silence["speaker"])

    section1 = output_dir / "section_01_en_normal.mp3"
    section2 = output_dir / "section_02_en_ja.mp3"
    section3 = output_dir / "section_03_en_slow.mp3"
    section4 = output_dir / "section_04_en_shadowing.mp3"
    required_guides = (
        "0-introduction", "1-bilingual", "2-slow", "3-shadowing", "4-normal", "5-conclusion",
    )
    try:
        guides = {key: guide_paths[key] for key in required_guides}
    except KeyError as e:
        raise ValueError(f"Generated guide is missing: {e.args[0]}") from e
    concatenate_mp3_files(english, section1, sample_rate=sample_rate)
    concatenate_mp3_files(bilingual, section2, sample_rate=sample_rate)
    concatenate_mp3_files(slow, section3, sample_rate=sample_rate)
    create_shadowing_section(slow_lines, section4, sample_rate=sample_rate)
    volume_paths = [
        (silence["opening"], 0.5),
        (guides["0-introduction"], 0.3),
        (silence["conversation"], 0.3),
        (section1, 0.07),
        (silence["section"], 0.2),
        (jingle_path, 0.01),
        (guides["1-bilingual"], 0.3),
        (silence["conversation"], 0.3),
        (section2, 0.07),
        (silence["section"], 0.2),
        (jingle_path, 0.01),
        (guides["2-slow"], 0.3),
        (silence["conversation"], 0.3),
        (section3, 0.07),
        (silence["section"], 0.2),
        (jingle_path, 0.01),
        (guides["3-shadowing"], 0.3),
        (silence["conversation"], 0.3),
        (section4, 0.07),
        (silence["section"], 0.2),
        (jingle_path, 0.01),
        (guides["4-normal"], 0.3),
        (silence["conversation"], 0.3),
        (section1, 0.07),
        (silence["section"], 0.2),
        (guides["5-conclusion"], 0.3),
        (silence["closing"], 0.4),
    ]
    foreground_key = _cache_key(
        {
            "version": CACHE_VERSION,
            "kind": "foreground",
            "sampleRate": sample_rate,
            "inputs": [(_file_hash(path), volume) for path, volume in volume_paths],
        }
    )
    foreground = shared_work_dir / f"final_foreground_{foreground_key}.mp3"
    if not _cache_is_valid(foreground, foreground_key):
        concatenate_mp3_files(
            [path for path, _ in volume_paths],
            foreground,
            sample_rate=sample_rate,
        )
        _save_cache_key(foreground, foreground_key)
    mix_background_music(
        foreground,
        final_output_path,
        background_music_path,
        volume_paths,
        sample_rate=sample_rate,
    )
    print(
        f"Final audio created\n-------------------\nSection 1 : {section1}\nSection 2 : {section2}\nSection 3 : {section3}\nSection 4 : {section4}\nFinal MP3 : {final_output_path}\n"
    )
