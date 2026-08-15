import unittest

from src.episode import apply_japanese_rate


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
