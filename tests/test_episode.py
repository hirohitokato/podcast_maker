import tempfile
import unittest
import json
from pathlib import Path

from src.episode import apply_japanese_rate, load_episode, load_settings


class EpisodeTests(unittest.TestCase):
    def test_japanese_rate_defaults_to_110_percent(self) -> None:
        self.assertEqual(
            '<speak><prosody rate="110%">日本語</prosody></speak>',
            apply_japanese_rate("<speak>日本語</speak>", {}),
        )

    def test_japanese_rate_uses_profile_and_rejects_invalid_values(self) -> None:
        self.assertIn(
            'rate="125%"',
            apply_japanese_rate("<speak>日本語</speak>", {"profiles": {"ja": {"rate": "125%"}}}),
        )
        with self.assertRaisesRegex(ValueError, "rate"):
            apply_japanese_rate("<speak>日本語</speak>", {"profiles": {"ja": {"rate": "fast"}}})

    def test_load_settings_accepts_jsonc_comments_and_trailing_commas(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.jsonc"
            path.write_text(
                '{\n  // shared audio settings\n  "audio": {"url": "https://example.com",},\n}',
                encoding="utf-8",
            )

            settings = load_settings(path)

        self.assertEqual("https://example.com", settings["audio"]["url"])

    def test_episode_does_not_require_shared_audio_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episode.json"
            path.write_text(
                '{"dialogue": [{"speaker": "man"}, {"speaker": "woman"}]}',
                encoding="utf-8",
            )

            episode = load_episode(path)

        self.assertEqual(["man", "woman"], [line["speaker"] for line in episode["dialogue"]])

    def test_episode_rejects_speakers_other_than_man_or_woman(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episode.json"
            path.write_text(
                '{"dialogue": [{"speaker": "emma"}]}', encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "man, woman"):
                load_episode(path)

    def test_episode_schema_limits_speakers_to_man_and_woman(self) -> None:
        schema_path = Path(__file__).parents[1] / "assets" / "episode.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        self.assertEqual(
            ["man", "woman"],
            schema["$defs"]["dialogueLine"]["properties"]["speaker"]["enum"],
        )
