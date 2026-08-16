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
            guides = {
                key: (work_dir if key == "0-introduction" else shared_work_dir)
                / f"guide_{key}.mp3"
                for key in (
                    "0-introduction", "1-bilingual", "2-slow", "3-shadowing", "4-normal", "5-conclusion",
                )
            }
            background = root / "bgm.mp3"
            jingle = root / "jingle.mp3"
            for path in guides.values():
                path.write_bytes(path.name.encode())
            background.touch()
            jingle.touch()
            calls: list[list[Path]] = []
            shadow_calls: list[list[Path]] = []

            def concatenate(inputs: list[Path], output: Path, *, sample_rate: str) -> None:
                calls.append(inputs)
                output.write_bytes(b"audio")

            def create_silence(path: Path, **_: object) -> None:
                path.write_bytes(b"silence")

            def shadow(inputs: list[Path], output: Path, *, sample_rate: str) -> None:
                shadow_calls.append(inputs)
                output.write_bytes(b"shadowing")

            with (
                patch.object(audio, "create_silence_file", side_effect=create_silence),
                patch.object(audio, "concatenate_mp3_files", side_effect=concatenate),
                patch.object(audio, "create_shadowing_section", side_effect=shadow),
                patch.object(audio, "mix_background_music") as mix,
            ):
                audio.build_final_audio(
                    episode,
                    output_dir,
                    output_dir / "final.mp3",
                    background_music_path=background,
                    jingle_path=jingle,
                    shared_work_dir=shared_work_dir,
                    guide_paths=guides,
                )

            self.assertEqual(
                [
                    shared_work_dir / "silence_24000_3000ms.mp3",
                    guides["0-introduction"],
                    shared_work_dir / "silence_24000_1000ms.mp3",
                    output_dir / "section_01_en_normal.mp3",
                    shared_work_dir / "silence_24000_1200ms.mp3",
                    jingle,
                    guides["1-bilingual"],
                    shared_work_dir / "silence_24000_1000ms.mp3",
                    output_dir / "section_02_en_ja.mp3",
                    shared_work_dir / "silence_24000_1200ms.mp3",
                    jingle,
                    guides["2-slow"],
                    shared_work_dir / "silence_24000_1000ms.mp3",
                    output_dir / "section_03_en_slow.mp3",
                    shared_work_dir / "silence_24000_1200ms.mp3",
                    jingle,
                    guides["3-shadowing"],
                    shared_work_dir / "silence_24000_1000ms.mp3",
                    output_dir / "section_04_en_shadowing.mp3",
                    shared_work_dir / "silence_24000_1200ms.mp3",
                    jingle,
                    guides["4-normal"],
                    shared_work_dir / "silence_24000_1000ms.mp3",
                    output_dir / "section_01_en_normal.mp3",
                    shared_work_dir / "silence_24000_1200ms.mp3",
                    guides["5-conclusion"],
                    shared_work_dir / "silence_24000_5000ms.mp3",
                ],
                calls[-1],
            )
            self.assertTrue((shared_work_dir / "silence_24000_1000ms.mp3.sha256").exists())
            self.assertFalse(any(work_dir.glob("silence_*.mp3")))
            self.assertEqual(background, mix.call_args.args[2])
            self.assertEqual(
                [
                    work_dir / "001_woman_en_slow.mp3",
                    work_dir / "002_man_en_slow.mp3",
                ],
                shadow_calls[0],
            )

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
            for name in (
                "001_woman_en_normal.mp3", "001_woman_en_slow.mp3", "001_ja_normal.mp3",
            ):
                (work_dir / name).write_bytes(name.encode())
            shared_work_dir = root / ".work"
            shared_work_dir.mkdir()
            introduction = work_dir / "guide_0-introduction.mp3"
            guides = {
                key: (work_dir if key == "0-introduction" else shared_work_dir)
                / f"guide_{key}.mp3"
                for key in (
                    "0-introduction", "1-bilingual", "2-slow", "3-shadowing", "4-normal", "5-conclusion",
                )
            }
            for path in guides.values():
                path.write_bytes(path.name.encode())
            background = root / "bgm.mp3"
            jingle = root / "jingle.mp3"
            background.write_bytes(b"bgm")
            jingle.write_bytes(b"jingle")
            calls: list[Path] = []

            def create_silence(path: Path, **_: object) -> None:
                path.write_bytes(b"silence")

            def concatenate(inputs: list[Path], output: Path, *, sample_rate: str) -> None:
                calls.append(output)
                output.write_bytes(b"|".join(path.read_bytes() for path in inputs))

            def shadow(_: list[Path], output: Path, *, sample_rate: str) -> None:
                calls.append(output)
                output.write_bytes(b"shadowing")

            with (
                patch.object(audio, "create_silence_file", side_effect=create_silence),
                patch.object(audio, "concatenate_mp3_files", side_effect=concatenate),
                patch.object(audio, "create_shadowing_section", side_effect=shadow),
                patch.object(audio, "mix_background_music"),
            ):
                kwargs = {
                    "background_music_path": background,
                    "jingle_path": jingle,
                    "shared_work_dir": shared_work_dir,
                    "guide_paths": guides,
                }
                audio.build_final_audio(episode, output_dir, output_dir / "final.mp3", **kwargs)
                audio.build_final_audio(episode, output_dir, output_dir / "final.mp3", **kwargs)
                guides["0-introduction"].write_bytes(b"updated guide")
                audio.build_final_audio(episode, output_dir, output_dir / "final.mp3", **kwargs)

            self.assertEqual(14, len(calls))
            foregrounds = list((root / ".work").glob("final_foreground_*.mp3"))
            self.assertEqual(2, len(foregrounds))
            self.assertTrue(all(Path(str(path) + ".sha256").exists() for path in foregrounds))

    def test_background_volume_expression_fades_in_and_out_at_the_end(self) -> None:
        expression = audio._background_volume_expression(
            [(3.0, 0.5), (4.0, 0.3), (5.0, 0.5)]
        )

        self.assertIn("0.5*between(t\\,0.0\\,3.0)", expression)
        self.assertIn("0.3*between(t\\,3.0\\,7.0)", expression)
        self.assertIn("(0.3+(0.5-0.3)*(t-7.0))*between(t\\,7.0\\,8.0)", expression)
        self.assertIn("0.5*between(t\\,8.0\\,10.0)", expression)
        self.assertIn("0.5*(12.0-t)/2*between(t\\,10.0\\,12.0)", expression)
