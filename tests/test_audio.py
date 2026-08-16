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
                {"id": "001", "speaker": "woman"},
                {"id": "002", "speaker": "man"},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "output"
            output_dir.mkdir()
            work_dir = output_dir / ".work"
            shared_work_dir = root / "shared-work"
            work_dir.mkdir()
            shared_work_dir.mkdir()
            introduction = work_dir / "guide_0-introduction.mp3"
            bilingual_introduction = shared_work_dir / "guide_1-bilingual.mp3"
            background = root / "bgm.mp3"
            introduction.write_bytes(b"introduction")
            bilingual_introduction.write_bytes(b"bilingual")
            background.touch()
            calls: list[list[Path]] = []

            def concatenate(inputs: list[Path], output: Path, *, sample_rate: str) -> None:
                calls.append(inputs)
                output.write_bytes(b"audio")

            def create_silence(path: Path, **_: object) -> None:
                path.write_bytes(b"silence")

            with (
                patch.object(audio, "create_silence_file", side_effect=create_silence),
                patch.object(audio, "concatenate_mp3_files", side_effect=concatenate),
                patch.object(audio, "mix_background_music") as mix,
            ):
                audio.build_final_audio(
                    episode,
                    output_dir,
                    output_dir / "final.mp3",
                    background_music_path=background,
                    shared_work_dir=shared_work_dir,
                    guide_paths={
                        "0-introduction": introduction,
                        "1-bilingual": bilingual_introduction,
                    },
                )

            self.assertEqual(
                [
                    shared_work_dir / "silence_24000_3000ms.mp3",
                    introduction,
                    shared_work_dir / "silence_24000_1000ms.mp3",
                    output_dir / "section_01_en_normal.mp3",
                    shared_work_dir / "silence_24000_1200ms.mp3",
                    bilingual_introduction,
                    shared_work_dir / "silence_24000_1000ms.mp3",
                    output_dir / "section_02_en_ja.mp3",
                    shared_work_dir / "silence_24000_5000ms.mp3",
                ],
                calls[-1],
            )
            self.assertTrue((shared_work_dir / "silence_24000_1000ms.mp3.sha256").exists())
            self.assertFalse(any(work_dir.glob("silence_*.mp3")))
            self.assertEqual(background, mix.call_args.args[2])

    def test_reuses_shared_foreground_cache_when_inputs_are_unchanged(self) -> None:
        episode = {
            "audio": {"outputFormat": "mp3", "sampleRate": "24000"},
            "dialogue": [{"id": "001", "speaker": "woman"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "episode"
            work_dir = output_dir / ".work"
            work_dir.mkdir(parents=True)
            for name in ("001_woman_en_normal.mp3", "001_ja_normal.mp3"):
                (work_dir / name).write_bytes(name.encode())
            shared_work_dir = root / ".work"
            shared_work_dir.mkdir()
            introduction = work_dir / "guide_0-introduction.mp3"
            bilingual_introduction = shared_work_dir / "guide_1-bilingual.mp3"
            introduction.write_bytes(b"introduction")
            bilingual_introduction.write_bytes(b"bilingual")
            background = root / "bgm.mp3"
            background.write_bytes(b"bgm")
            calls: list[Path] = []

            def create_silence(path: Path, **_: object) -> None:
                path.write_bytes(b"silence")

            def concatenate(inputs: list[Path], output: Path, *, sample_rate: str) -> None:
                calls.append(output)
                output.write_bytes(b"|".join(path.read_bytes() for path in inputs))

            with (
                patch.object(audio, "create_silence_file", side_effect=create_silence),
                patch.object(audio, "concatenate_mp3_files", side_effect=concatenate),
                patch.object(audio, "mix_background_music"),
            ):
                kwargs = {
                    "background_music_path": background,
                    "shared_work_dir": shared_work_dir,
                    "guide_paths": {
                        "0-introduction": introduction,
                        "1-bilingual": bilingual_introduction,
                    },
                }
                audio.build_final_audio(episode, output_dir, output_dir / "final.mp3", **kwargs)
                audio.build_final_audio(episode, output_dir, output_dir / "final.mp3", **kwargs)
                introduction.write_bytes(b"updated guide")
                audio.build_final_audio(episode, output_dir, output_dir / "final.mp3", **kwargs)

            self.assertEqual(8, len(calls))
            foregrounds = list((root / ".work").glob("final_foreground_*.mp3"))
            self.assertEqual(2, len(foregrounds))
            self.assertTrue(all(Path(str(path) + ".sha256").exists() for path in foregrounds))

    def test_background_volume_expression_fades_the_final_two_seconds(self) -> None:
        expression = audio._background_volume_expression(
            [(3.0, 0.5), (4.0, 0.3), (5.0, 0.5)]
        )

        self.assertIn("0.5*between(t\\,0.0\\,3.0)", expression)
        self.assertIn("0.3*between(t\\,3.0\\,7.0)", expression)
        self.assertIn("0.5*between(t\\,7.0\\,10.0)", expression)
        self.assertIn("0.5*(12.0-t)/2*between(t\\,10.0\\,12.0)", expression)
