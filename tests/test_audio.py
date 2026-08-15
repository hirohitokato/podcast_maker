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
            background = assets_dir / "Kuru_kuru_world.mp3"
            introduction.touch()
            bilingual_introduction.touch()
            background.touch()
            calls: list[list[Path]] = []

            def concatenate(inputs: list[Path], output: Path, *, sample_rate: str) -> None:
                calls.append(inputs)
                output.touch()

            with (
                patch.object(audio, "create_silence_file"),
                patch.object(audio, "concatenate_mp3_files", side_effect=concatenate),
                patch.object(audio, "mix_background_music") as mix,
            ):
                audio.build_final_audio(
                    episode,
                    output_dir,
                    output_dir / "final.mp3",
                    assets_dir=assets_dir,
                    background_music_path=background,
                )

            work_dir = output_dir / ".work"
            self.assertEqual(
                [
                    work_dir / "silence_24000_3000ms.mp3",
                    introduction,
                    work_dir / "silence_24000_1000ms.mp3",
                    work_dir / "section_01_en_normal.mp3",
                    work_dir / "silence_24000_1200ms.mp3",
                    bilingual_introduction,
                    work_dir / "silence_24000_1000ms.mp3",
                    work_dir / "section_02_en_ja.mp3",
                    work_dir / "silence_24000_5000ms.mp3",
                ],
                calls[-1],
            )
            self.assertEqual(background, mix.call_args.args[2])

    def test_background_volume_expression_fades_the_final_two_seconds(self) -> None:
        expression = audio._background_volume_expression(
            [(3.0, 0.5), (4.0, 0.3), (5.0, 0.5)]
        )

        self.assertIn("0.5*between(t\\,0.0\\,3.0)", expression)
        self.assertIn("0.3*between(t\\,3.0\\,7.0)", expression)
        self.assertIn("0.5*between(t\\,7.0\\,10.0)", expression)
        self.assertIn("0.5*(12.0-t)/2*between(t\\,10.0\\,12.0)", expression)
