import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


class FakeGuidePolly(FakePolly):
    def __init__(self) -> None:
        super().__init__()
        self.synthesize_calls: list[dict[str, str]] = []

    def synthesize_speech(self, **kwargs: str) -> dict[str, object]:
        self.synthesize_calls.append(kwargs)
        return {"AudioStream": FakeAudioStream()}


class FakeAudioStream:
    def read(self) -> bytes:
        return b"guide audio"

    def close(self) -> None:
        pass


class FakeSession:
    def __init__(self, client: FakeGuidePolly) -> None:
        self._client = client

    def client(self, name: str) -> FakeGuidePolly:
        self.last_client_name = name
        return self._client


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

    def test_generates_and_caches_all_guides_in_the_required_work_directories(self) -> None:
        guides = {
            "0-introduction": "Topics: %s",
            "1-bilingual": "Bilingual",
            "2-slow": "Slow",
            "3-shadowing": "Shadowing",
            "4-normal": "Normal",
            "5-conclusion": "Conclusion",
        }
        episode = {
            "audio": {
                "outputFormat": "mp3",
                "sampleRate": "24000",
                "voices": {"guide": {"languageCode": "ja-JP", "voiceId": "Kazuha", "engine": "neural"}},
                "profiles": {"guide": {"rate": "110%"}},
                "guides": guides,
            },
            "dialogue": [],
            "english_learning": {"keywords": ["S3", "CloudFront"]},
        }
        client = FakeGuidePolly()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(polly, "create_aws_session", return_value=FakeSession(client)),
                patch.object(polly, "verify_credentials"),
            ):
                paths = polly.generate_dialogue_audio(
                    episode,
                    root / "episode" / ".work",
                    shared_work_dir=root / ".work",
                    rule_paths=[],
                )
                polly.generate_dialogue_audio(
                    episode,
                    root / "episode" / ".work",
                    shared_work_dir=root / ".work",
                    rule_paths=[],
                )

            self.assertEqual(6, len(client.synthesize_calls))
            self.assertEqual("Kazuha", client.synthesize_calls[0]["VoiceId"])
            self.assertEqual("ja-JP", client.synthesize_calls[0]["LanguageCode"])
            self.assertIn("Topics: S3, CloudFront", client.synthesize_calls[0]["Text"])
            self.assertEqual(root / "episode" / ".work" / "guide_0-introduction.mp3", paths["0-introduction"])
            self.assertEqual(root / ".work" / "guide_1-bilingual.mp3", paths["1-bilingual"])
            self.assertTrue(Path(str(paths["0-introduction"]) + ".sha256").exists())

    def test_rejects_missing_required_guide_before_calling_polly(self) -> None:
        episode = {
            "audio": {"guides": {"0-introduction": "Topics: %s"}},
            "dialogue": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "1-bilingual"):
                polly.generate_dialogue_audio(
                    episode,
                    Path(directory) / "episode",
                    shared_work_dir=Path(directory) / "shared",
                    rule_paths=[],
                )

    def test_uses_speaker_specific_japanese_voices(self) -> None:
        episode = {
            "audio": {
                "outputFormat": "mp3",
                "sampleRate": "24000",
                "voices": {
                    "woman": {"languageCode": "en-US", "voiceId": "Joanna", "engine": "generative"},
                    "man": {"languageCode": "en-US", "voiceId": "Matthew", "engine": "generative"},
                    "woman-ja": {"languageCode": "ja-JP", "voiceId": "Tomoko", "engine": "neural"},
                    "man-ja": {"languageCode": "ja-JP", "voiceId": "Takumi", "engine": "neural"},
                    "guide": {"languageCode": "ja-JP", "voiceId": "Kazuha", "engine": "neural"},
                },
                "profiles": {
                    "ja": {"rate": "110%"}, "slow": {"rate": "85%"}, "guide": {"rate": "110%"},
                },
                "guides": {
                    "0-introduction": "Topics: %s", "1-bilingual": "Bilingual", "2-slow": "Slow",
                    "3-shadowing": "Shadowing", "4-normal": "Normal", "5-conclusion": "Conclusion",
                },
            },
            "dialogue": [
                {"id": "001", "speaker": "woman", "en": {"ssml": "<speak>Hello</speak>"}, "ja": {"ssml": "<speak>こんにちは</speak>"}},
                {"id": "002", "speaker": "man", "en": {"ssml": "<speak>Hi</speak>"}, "ja": {"ssml": "<speak>やあ</speak>"}},
            ],
            "english_learning": {"keywords": ["S3"]},
        }
        client = FakeGuidePolly()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(polly, "create_aws_session", return_value=FakeSession(client)),
                patch.object(polly, "verify_credentials"),
            ):
                polly.generate_dialogue_audio(
                    episode,
                    root / "episode" / ".work",
                    shared_work_dir=root / ".work",
                    rule_paths=[],
                )

        self.assertEqual(
            ["Joanna", "Joanna", "Tomoko", "Matthew", "Matthew", "Takumi", *["Kazuha"] * 6],
            [call["VoiceId"] for call in client.synthesize_calls],
        )
        self.assertIn('rate="85%"', client.synthesize_calls[1]["Text"])
