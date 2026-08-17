import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from src.tools import build_prompt


class BuildPromptTests(unittest.TestCase):
    def test_main_renders_service_and_schema_to_stdout(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch("builtins.input", return_value="AWS Lambda"),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            self.assertEqual(0, build_prompt.main())

        self.assertIn("AWS Lambda", stdout.getvalue())
        self.assertIn('"title": "AWS English Podcast Episode"', stdout.getvalue())
        self.assertNotIn("{{AWS_SERVICE}}", stdout.getvalue())
        self.assertNotIn("{{EPISODE_SCHEMA}}", stdout.getvalue())
        self.assertEqual("AWSサービス名を入力してください: ", stderr.getvalue())

    def test_main_rejects_blank_service_name(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch("builtins.input", return_value="  "),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            self.assertEqual(1, build_prompt.main())

        self.assertEqual("", stdout.getvalue())
        self.assertIn("ERROR: AWSサービス名を入力してください。", stderr.getvalue())

    def test_main_rejects_end_of_input(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch("builtins.input", side_effect=EOFError),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            self.assertEqual(1, build_prompt.main())

        self.assertEqual("", stdout.getvalue())
        self.assertIn("ERROR: AWSサービス名を入力してください。", stderr.getvalue())
