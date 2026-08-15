from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


def pls(language: str, name: str = "term") -> str:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<lexicon version="1.0" xmlns="http://www.w3.org/2005/01/pronunciation-lexicon"
         xml:lang="{language}">
  <lexeme><grapheme>{name}</grapheme><alias>replacement</alias></lexeme>
</lexicon>'''


class FakePolly:
    def __init__(self) -> None:
        self.put_calls: list[dict[str, str]] = []

    def put_lexicon(self, **kwargs: str) -> None:
        self.put_calls.append(kwargs)


class LexiconTests(unittest.TestCase):
    def test_japanese_rate_defaults_to_110_percent(self) -> None:
        self.assertEqual(
            '<speak><prosody rate="110%">日本語</prosody></speak>',
            main.apply_japanese_rate("<speak>日本語</speak>", {}),
        )

    def test_japanese_rate_uses_profile_and_rejects_invalid_values(self) -> None:
        audio = {"profiles": {"ja": {"rate": "125%"}}}
        self.assertIn('rate="125%"', main.apply_japanese_rate("<speak>日本語</speak>", audio))
        with self.assertRaisesRegex(ValueError, "rate"):
            main.apply_japanese_rate(
                "<speak>日本語</speak>",
                {"profiles": {"ja": {"rate": "fast"}}},
            )

    def test_pls_option_can_be_repeated(self) -> None:
        with patch("sys.argv", ["main.py", "episode.json", "--pls", "one.pls", "--pls", "two.pls"]):
            args = main.parse_args()

        self.assertEqual([Path("one.pls"), Path("two.pls")], args.pls)

    def test_registers_lexicons_in_path_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            custom = Path(directory) / "custom.pls"
            default = Path(directory) / "aws-terms-ja.pls"
            custom.write_text(pls("ja-JP", "custom"), encoding="utf-8")
            default.write_text(pls("ja-JP", "default"), encoding="utf-8")

            polly = FakePolly()
            registered = main.register_lexicons(polly, [custom, default])

        self.assertEqual(2, len(polly.put_calls))
        self.assertEqual(
            [main._lexicon_name_from_path(custom), main._lexicon_name_from_path(default)],
            [item["name"] for item in registered],
        )
        self.assertEqual(
            [item["name"] for item in registered],
            main.lexicon_names_for_language(registered, "ja-JP"),
        )
        self.assertEqual([], main.lexicon_names_for_language(registered, "en-US"))

    def test_rejects_more_than_five_lexicons_for_one_language(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for index in range(6):
                path = Path(directory) / f"rules-{index}.pls"
                path.write_text(pls("ja-JP", str(index)), encoding="utf-8")
                paths.append(path)

            polly = FakePolly()
            with self.assertRaisesRegex(ValueError, "At most 5"):
                main.register_lexicons(polly, paths)

        self.assertEqual([], polly.put_calls)

    def test_cache_key_changes_when_lexicon_changes(self) -> None:
        common = {
            "ssml": "<speak>test</speak>",
            "voice_id": "Takumi",
            "engine": "neural",
            "output_format": "mp3",
            "sample_rate": "24000",
            "language_code": "ja-JP",
        }
        self.assertNotEqual(
            main.create_cache_key(**common, lexicon_cache_tokens=["rules:old"]),
            main.create_cache_key(**common, lexicon_cache_tokens=["rules:new"]),
        )


if __name__ == "__main__":
    unittest.main()
