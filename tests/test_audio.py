import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import audio


class AudioTests(unittest.TestCase):
    def test_final_audio_includes_introductions_and_configured_pauses(self) -> None:
        episode = {
            "audio": {
                "outputFormat": "mp3",
                "sampleRate": "24000",
                "pause": {"beforeConversationMs": 1000, "betweenSectionsMs": 1200},
            },
            "dialogue": [
                {"id": "001", "speaker": "emma"},
                {"id": "002", "speaker": "daniel"},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "output"
            output_dir.mkdir()
            assets_dir = root / "assets"
            assets_dir.mkdir()
            introduction = assets_dir / "speech_introduction.mp3"
            bilingual_introduction = assets_dir / "speech_both_en_ja.mp3"
            introduction.touch()
            bilingual_introduction.touch()
            calls: list[list[Path]] = []

            def concatenate(inputs: list[Path], output: Path, *, sample_rate: str) -> None:
                calls.append(inputs)
                output.touch()

            with (
                patch.object(audio, "create_silence_file"),
                patch.object(audio, "concatenate_mp3_files", side_effect=concatenate),
            ):
                audio.build_final_audio(
                    episode, output_dir, output_dir / "final.mp3", assets_dir=assets_dir
                )

            work_dir = output_dir / ".work"
            self.assertEqual(
                [
                    introduction,
                    work_dir / "silence_24000_1000ms.mp3",
                    work_dir / "section_01_en_normal.mp3",
                    work_dir / "silence_24000_1200ms.mp3",
                    bilingual_introduction,
                    work_dir / "silence_24000_1000ms.mp3",
                    work_dir / "section_02_en_ja.mp3",
                ],
                calls[-1],
            )
