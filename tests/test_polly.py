import tempfile
import unittest
from pathlib import Path

from src import polly


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


class PollyTests(unittest.TestCase):
    def test_registers_lexicons_in_path_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            custom = Path(directory) / "custom.pls"
            default = Path(directory) / "aws-terms-ja.pls"
            custom.write_text(pls("ja-JP", "custom"), encoding="utf-8")
            default.write_text(pls("ja-JP", "default"), encoding="utf-8")
            client = FakePolly()
            registered = polly.register_lexicons(client, [custom, default])

        self.assertEqual(2, len(client.put_calls))
        self.assertEqual(
            [polly._lexicon_name_from_path(custom), polly._lexicon_name_from_path(default)],
            [item["name"] for item in registered],
        )
        self.assertEqual(
            [item["name"] for item in registered],
            polly._lexicon_names(registered, "ja-JP"),
        )
        self.assertEqual([], polly._lexicon_names(registered, "en-US"))

    def test_rejects_more_than_five_lexicons_for_one_language(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for index in range(6):
                path = Path(directory) / f"rules-{index}.pls"
                path.write_text(pls("ja-JP", str(index)), encoding="utf-8")
                paths.append(path)

            client = FakePolly()
            with self.assertRaisesRegex(ValueError, "At most 5"):
                polly.register_lexicons(client, paths)

        self.assertEqual([], client.put_calls)

    def test_cache_key_changes_when_lexicon_changes(self) -> None:
        common = {
            "ssml": "<speak>test</speak>", "voice_id": "Takumi", "engine": "neural",
            "output_format": "mp3", "sample_rate": "24000", "language_code": "ja-JP",
        }
        self.assertNotEqual(
            polly.create_cache_key(**common, lexicon_cache_tokens=["rules:old"]),
            polly.create_cache_key(**common, lexicon_cache_tokens=["rules:new"]),
        )
