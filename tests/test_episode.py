import tempfile
import unittest
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
            path.write_text('{"dialogue": []}', encoding="utf-8")

            episode = load_episode(path)

        self.assertEqual([], episode["dialogue"])
